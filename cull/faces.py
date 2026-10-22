"""Local faces stage: face count, closed eyes, smiles. Offline replacement for rekog's face fields.

YuNet (OpenCV Zoo, MIT) finds every face on the preview, including small faces in group
shots. Each kept face is cropped and run through MediaPipe Face Landmarker (Apache 2.0),
whose blendshapes give eyeBlink and mouthSmile scores in [0, 1].

Returns the contract fields plus `faces`, the raw per-face scores, so thresholds can be
re-tuned from the cache without re-running the models.
"""
from __future__ import annotations

import logging
import threading
from concurrent.futures import ThreadPoolExecutor

import cv2
import numpy as np

from cull import config, models

log = logging.getLogger(__name__)

DETECT_SCORE = 0.6          # YuNet confidence floor
RELATIVE_FACE_WIDTH = 0.25  # same filter as rekog: fraction of the largest face's width
CROP_MARGIN = 0.5           # context around the box on each side, as a fraction of its size
CROP_SIZE = 256             # landmarker input, small faces are upscaled to this
BLINK_THRESHOLD = 0.5       # mean of eyeBlinkLeft/Right above this = eyes closed
SMILE_THRESHOLD = 0.5       # mean of mouthSmileLeft/Right above this = smiling

_local = threading.local()
# Every landmarker opened, so run() can close them. Left to __del__ they close during
# interpreter shutdown, after mediapipe's C library is gone, and print a traceback.
_opened = []
_opened_lock = threading.Lock()


def _models():
    """Per-thread detector and landmarker (neither is safe to share across threads)."""
    if not hasattr(_local, "detector"):
        import mediapipe as mp
        from mediapipe.tasks.python import BaseOptions, vision
        _local.mp = mp
        _local.detector = cv2.FaceDetectorYN.create(
            str(models.path("yunet")), "", (320, 320), DETECT_SCORE, 0.3, 5000)
        _local.landmarker = vision.FaceLandmarker.create_from_options(
            vision.FaceLandmarkerOptions(
                base_options=BaseOptions(model_asset_path=str(models.path("landmarker"))),
                running_mode=vision.RunningMode.IMAGE,
                num_faces=1,
                min_face_detection_confidence=0.3,
                output_face_blendshapes=True))
        with _opened_lock:
            _opened.append(_local.landmarker)
    return _local.detector, _local.landmarker, _local.mp


def close():
    """Close every landmarker. Threads that call detect() again open fresh ones."""
    with _opened_lock:
        for landmarker in _opened:
            landmarker.close()
        _opened.clear()
    if hasattr(_local, "detector"):
        del _local.detector, _local.landmarker


def _crop(rgb, box):
    """Square crop around a face box with margin, padded at the frame edge, resized."""
    x, y, w, h = box
    side = max(w, h) * (1 + 2 * CROP_MARGIN)
    cx, cy = x + w / 2, y + h / 2
    x0, y0 = int(round(cx - side / 2)), int(round(cy - side / 2))
    s = int(round(side))
    pad = max(0, -x0, -y0, x0 + s - rgb.shape[1], y0 + s - rgb.shape[0])
    if pad:
        rgb = cv2.copyMakeBorder(rgb, pad, pad, pad, pad, cv2.BORDER_CONSTANT)
        x0, y0 = x0 + pad, y0 + pad
    crop = rgb[y0:y0 + s, x0:x0 + s]
    interp = cv2.INTER_CUBIC if s < CROP_SIZE else cv2.INTER_AREA
    return np.ascontiguousarray(cv2.resize(crop, (CROP_SIZE, CROP_SIZE), interpolation=interp))


def _expression(landmarker, mp, crop):
    """(blink, smile) means for the face in the crop, or (None, None) if none is found."""
    result = landmarker.detect(mp.Image(image_format=mp.ImageFormat.SRGB, data=crop))
    if not result.face_blendshapes:
        return None, None
    s = {c.category_name: c.score for c in result.face_blendshapes[0]}
    blink = (s["eyeBlinkLeft"] + s["eyeBlinkRight"]) / 2
    smile = (s["mouthSmileLeft"] + s["mouthSmileRight"]) / 2
    return round(blink, 3), round(smile, 3)


def detect(preview_path):
    """Raw kept faces for one preview: [{w, score, blink, smile}], w as a fraction of width."""
    detector, landmarker, mp = _models()
    bgr = cv2.imread(str(preview_path))
    if bgr is None:
        raise ValueError("preview unreadable")
    h, w = bgr.shape[:2]
    detector.setInputSize((w, h))
    _, found = detector.detect(bgr)
    boxes = [] if found is None else [(f[:4], float(f[14])) for f in found]
    widths = [float(b[2]) / w for b, _ in boxes]
    floor = max(config.MIN_FACE_WIDTH, RELATIVE_FACE_WIDTH * max(widths, default=0))
    rgb = cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)
    faces = []
    for (box, score), fw in zip(boxes, widths):
        if fw < floor:
            continue
        blink, smile = _expression(landmarker, mp, _crop(rgb, box))
        faces.append({"w": round(fw, 4), "score": round(score, 3), "blink": blink, "smile": smile})
    return faces


def summarize(faces, blink_threshold=BLINK_THRESHOLD, smile_threshold=SMILE_THRESHOLD):
    """Contract fields from raw faces. A face the landmarker could not read counts as open."""
    return {
        "face_count": len(faces),
        "eyes_closed_count": sum((f["blink"] or 0) > blink_threshold for f in faces),
        "smile_count": sum((f["smile"] or 0) > smile_threshold for f in faces),
    }


def _blurry(image):
    sharpness = image.get("sharpness")
    return sharpness is not None and sharpness < config.MIN_SHARPNESS


def _process(image):
    if _blurry(image):
        return {**summarize([]), "faces": []}
    try:
        faces = detect(config.CULL_ROOT / image["preview"])
        return {**summarize(faces), "faces": faces}
    except Exception as exc:  # a failed image never stops the stage
        return {**summarize([]), "faces": [], "error": f"{type(exc).__name__}: {str(exc)[:80]}"}


def run(images, cached):
    todo = [im for im in images if im["path"] not in cached]
    if not todo:
        return {}
    models.path("yunet"), models.path("landmarker")  # download once, before threads start
    try:
        with ThreadPoolExecutor(max_workers=config.MAX_WORKERS) as pool:
            results = list(pool.map(_process, todo))
    finally:
        close()
    out ={im["path"]: res for im, res in zip(todo, results)}
    errors = sum("error" in r for r in out.values())
    log.info("faces: %d images, %d skipped blurry, %d errors",
             len(todo), sum(_blurry(im) for im in todo), errors)
    return out
