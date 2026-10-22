"""Personal taste: per-shoot sums follow the final selection, nothing applies below
MIN_OVERRIDES, rejects only lose to kept frames, and the learned shift moves a new shoot's
scores toward what the photographer keeps."""
import numpy as np
import pytest

from cull import aesthetic, personal, scenes


@pytest.fixture(autouse=True)
def store(tmp_path, monkeypatch):
    monkeypatch.setenv("CULL_SETTINGS", str(tmp_path / "settings.json"))


def _rows(n, seed=0, moments=3):
    """Even rows look 'liked' (smiling faces, higher aesthetic score), odd rows do not."""
    rng = np.random.default_rng(seed)
    rows = []
    for i in range(n):
        liked = i % 2 == 0
        v = rng.normal(size=768)
        face = {"w": 0.08, "score": 0.9, "blink": 0.05, "smile": 0.9 if liked else 0.05}
        rows.append({"path": f"p{i}", "group_id": f"G{i % moments}",
                     "embedding": scenes.pack(v / np.linalg.norm(v)),
                     "sharpness": 400.0 + rng.normal(scale=20), "exposure_flags": [],
                     "faces": [face, dict(face)],
                     "scene_scores": {"aesthetic": (0.04 if liked else -0.04) + rng.normal(scale=0.01),
                                      "candid": rng.normal(scale=0.02)}})
    return rows


def _keep_liked(n):
    return {f"p{i}": 5 if i % 2 == 0 else 1 for i in range(n)}


def test_reduce_gives_standardized_hand_features():
    z = personal.reduce(aesthetic.features(_rows(12)))
    assert z.shape == (12, personal.K + len(aesthetic.EXTRA_FEATURES))


def test_no_shift_until_enough_overrides():
    rows = _rows(20)
    assert personal.record("A", rows, {"p0": 5, "p1": 1}) == 0
    assert personal.shift(aesthetic.features(rows)).tolist() == [0.0] * 20
    assert personal.record("A", rows, _keep_liked(10)) == 10


def test_a_reject_with_nothing_kept_in_its_moment_teaches_nothing():
    assert personal.shoot_sums(_rows(6), {"p1": 1}) is None  # no kept frame to lose to
    assert personal.shoot_sums(_rows(6), {"p0": 5, "p3": 1})["overrides"] == 2  # same moment


def test_sums_are_per_shoot_and_replaced_on_rerecord():
    rows = _rows(20)
    personal.record("A", rows, _keep_liked(6))
    personal.record("B", rows, {"p0": 5, "p3": 1})
    ex = personal.load_examples()
    assert ex["A"]["overrides"] == 6 and ex["B"]["overrides"] == 2
    personal.record("A", rows, {})  # all of A cleared
    assert sorted(personal.load_examples()) == ["B"]
    assert "p3" not in str(personal.load_examples())  # sums only, no paths stored


def test_learned_shift_favors_the_liked_look_on_a_new_shoot():
    personal.record("A", _rows(40, seed=1), _keep_liked(40))
    s = personal.shift(aesthetic.features(_rows(40, seed=2)))  # another shoot, never touched
    assert s[0::2].mean() > 0.5 and s[1::2].mean() < -0.5
    assert np.abs(s).max() <= personal.MAX_SHIFT


def test_aesthetic_stage_applies_the_shift_and_keeps_the_base():
    personal.record("A", _rows(40, seed=3), _keep_liked(40))
    out = aesthetic.run(_rows(10, seed=4), cached={})
    gaps = [out[f"p{i}"]["claude_score"] - out[f"p{i}"]["base_score"] for i in range(10)]
    assert np.mean(gaps[0::2]) > 0 > np.mean(gaps[1::2])
