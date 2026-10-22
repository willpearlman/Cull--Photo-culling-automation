"""Local scene tags: tag rules, shipped prompt vectors, preprocessing, scoring."""
import numpy as np
from PIL import Image

from cull import scenes


def test_face_count_rules():
    s = {}
    assert scenes.tags_for(1, s) == ["portrait"]
    assert scenes.tags_for(2, s) == ["couple"]
    assert scenes.tags_for(3, s) == ["group"]  # rekog's rule left 3 faces untagged
    assert scenes.tags_for(5, s) == ["group"]


def test_exclusive_genre_tags_keep_only_the_best_moment():
    s = {"ceremony": 0.05, "reception": 0.09, "first kiss": -0.1, "rings": 0.02, "details": -0.3}
    tags = scenes.tags_for(2, s, genre_tags=["ceremony", "reception", "first kiss", "rings", "details"],
                           exclusive=["ceremony", "reception", "first kiss"])
    assert tags == ["couple", "reception", "rings"]


def test_wedding_vocabulary():
    assert scenes.genre_tags("wedding") == [
        "getting ready", "ceremony", "rings", "first kiss", "family formals", "couple portraits",
        "first dance", "reception", "details"]
    assert scenes.genre_tags("event") == []
    assert set(scenes.exclusive_tags("wedding")) < set(scenes.genre_tags("wedding"))
    assert scenes.tag_vocab("wedding")[:4] == ["group", "couple", "portrait", "candid"]


def test_score_tags_respect_thresholds_and_detail_needs_no_faces():
    s = {"crowd": 0.1, "indoor": 0.02, "outdoor": -0.02, "detail": 0.05, "food": -0.1,
         "dance floor": 0.0}
    assert scenes.tags_for(0, s) == ["group", "detail", "indoor"]
    assert "detail" not in scenes.tags_for(1, s)
    assert "detail" not in scenes.tags_for(0, {**s, "detail": scenes.THRESHOLDS["detail"]})


def test_genre_tags_are_appended_only_when_asked():
    s = {"ceremony": 0.2, "reception": -0.1}
    assert scenes.tags_for(2, s, genre_tags=["ceremony", "reception"]) == ["couple", "ceremony"]
    assert scenes.tags_for(2, s, genre_tags=["ceremony"], genre_threshold=0.3) == ["couple"]
    assert scenes.tags_for(2, s) == ["couple"]


def test_shipped_vectors_cover_every_prompt_in_vocab():
    data = np.load(scenes.EMBED_PATH)
    shipped = set(data["prompts"].tolist())
    assert set(scenes._all_prompts()) <= shipped, "edit vocab.json, then run --build-vocab"
    norms = np.linalg.norm(data["embeddings"], axis=1)
    assert np.allclose(norms, 1.0, atol=1e-4)


def test_pixels_are_224_chw_in_minus_one_to_one(tmp_path):
    p = tmp_path / "x.jpg"
    Image.new("RGB", (640, 480), (255, 0, 0)).save(p)
    arr = scenes._pixels(p)
    assert arr.shape == (3, 224, 224)
    assert arr.min() >= -1.0 and arr.max() <= 1.0
    assert arr[0].mean() > 0.9 and arr[1].mean() < -0.9  # red channel high, green low


def test_score_is_yes_minus_no(monkeypatch):
    vecs = {"y": np.array([1.0, 0.0]), "n": np.array([0.0, 1.0])}
    monkeypatch.setattr(scenes, "_prompt_vectors", lambda: vecs)
    images = np.array([[1.0, 0.0], [0.0, 1.0]])
    out = scenes.scores(images, {"t": {"yes": ["y"], "no": ["n"]}})
    assert out["t"].tolist() == [1.0, -1.0]
