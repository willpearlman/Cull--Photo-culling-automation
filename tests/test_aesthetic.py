"""Local aesthetic stage: ridge head, feature isolation from rekog, shipped head shape, stage output."""
import numpy as np

from cull import aesthetic, scenes


def _row(path, vec, **kw):
    row = {"path": path, "embedding": scenes.pack(vec), "sharpness": 400.0, "exposure_flags": [],
           "faces": [], "scene_scores": {"aesthetic": 0.0, "candid": 0.0}}
    row.update(kw)
    return row


def test_fit_recovers_a_linear_signal():
    rng = np.random.default_rng(0)
    x = rng.normal(size=(300, 10)).astype(np.float32)
    y = 3 * x[:, 0] - 2 * x[:, -1] + 5
    head = aesthetic.fit(x, y, alpha=0.01)
    assert np.abs(aesthetic.predict(head, x) - y).max() < 0.05


def test_face_features_come_from_raw_faces_not_merged_rekog_fields():
    face = {"w": 0.1, "score": 0.9, "blink": 0.9, "smile": 0.8}
    row = _row("a", np.ones(4) / 2, faces=[face, face], face_count=7, eyes_closed_count=0)
    ex = dict(zip(aesthetic.EXTRA_FEATURES, aesthetic.extras(row)))
    assert ex["face_count"] == 2 and ex["eyes_closed"] == 2 and ex["smiles"] == 2


def test_shipped_head_matches_feature_layout():
    head = aesthetic._load_head()
    assert head["w"].shape == (768 + len(aesthetic.EXTRA_FEATURES),)
    assert head["mean"].shape == head["std"].shape == head["w"].shape


def test_run_scores_every_frame_within_range():
    rng = np.random.default_rng(1)
    rows = []
    for i in range(5):
        v = rng.normal(size=768)
        rows.append(_row(f"p{i}", v / np.linalg.norm(v)))
    rows[0]["faces"] = [{"w": 0.1, "score": 0.9, "blink": 0.8, "smile": 0.9}]  # laughing
    rows[1]["scene_scores"]["candid"] = -0.2
    out = aesthetic.run(rows, cached={"p4": {}})
    assert sorted(out) == ["p0", "p1", "p2", "p3"]
    assert all(1.0 <= r["claude_score"] <= 10.0 for r in out.values())
    assert out["p0"]["intentional_eyes_closed"] is True
    assert out["p1"]["candid"] is False and out["p2"]["candid"] is True
    assert out["p0"]["claude_reason"].endswith("1 face, 1 smiling, 1 eyes closed")


def test_rows_without_embedding_are_skipped():
    assert aesthetic.run([{"path": "x"}], cached={}) == {}
