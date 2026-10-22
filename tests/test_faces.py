"""Local faces stage: summary thresholds, crop geometry, model download integrity."""
import numpy as np
import pytest

from cull import config, faces


def test_summarize_counts_by_threshold_and_treats_unread_as_open():
    raw = [{"w": 0.1, "score": 0.9, "blink": 0.9, "smile": 0.7},
           {"w": 0.1, "score": 0.9, "blink": 0.2, "smile": 0.6},
           {"w": 0.1, "score": 0.9, "blink": None, "smile": None}]
    assert faces.summarize(raw) == {"face_count": 3, "eyes_closed_count": 1, "smile_count": 2}
    assert faces.summarize(raw, blink_threshold=0.95, smile_threshold=0.65) == {
        "face_count": 3, "eyes_closed_count": 0, "smile_count": 1}


def test_crop_pads_faces_at_the_frame_edge():
    rgb = np.full((100, 200, 3), 255, dtype=np.uint8)
    crop = faces._crop(rgb, (0, 0, 40, 40))  # top-left corner, margin runs off the frame
    assert crop.shape == (faces.CROP_SIZE, faces.CROP_SIZE, 3)
    assert crop[0, 0].tolist() == [0, 0, 0]  # padding
    assert crop[faces.CROP_SIZE // 2, faces.CROP_SIZE // 2].tolist() == [255, 255, 255]  # face


def test_blurry_frames_are_skipped_without_running_models(monkeypatch):
    monkeypatch.setattr(faces, "detect", lambda _: pytest.fail("models should not run"))
    out = faces._process({"path": "a", "preview": "a.jpg", "sharpness": config.MIN_SHARPNESS - 1})
    assert out == {"face_count": 0, "eyes_closed_count": 0, "smile_count": 0, "faces": []}


def test_download_with_wrong_checksum_is_rejected(tmp_path, monkeypatch):
    from cull import models
    monkeypatch.setattr(models, "MODEL_DIR", tmp_path)
    monkeypatch.setattr(models.urllib.request, "urlretrieve",
                        lambda url, dst: dst.write_bytes(b"not the model"))
    with pytest.raises(RuntimeError, match="does not match"):
        models.path("yunet")
    assert not any(tmp_path.iterdir())  # nothing half-written is left behind
