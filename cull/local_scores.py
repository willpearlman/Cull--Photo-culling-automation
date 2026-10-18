"""Local scoring stage: sharpness (max per-tile Laplacian variance) and exposure clipping.

Exposes run(images, cached) per contracts.md. Reads preview JPEGs only.
"""
from __future__ import annotations

import logging

import cv2
import numpy as np

from . import config

log = logging.getLogger("cull.local_scores")

LONG_EDGE = 1000
CLIP_FRACTION = 0.05  # > 5% of pixels clipped flags under/over exposure
TILES = 4  # sharpness = max Laplacian variance over a TILES x TILES grid


def _resize_gray(path):
    img = cv2.imread(str(path), cv2.IMREAD_GRAYSCALE)
    if img is None:
        return None
    h, w = img.shape[:2]
    scale = LONG_EDGE / max(h, w)
    if scale < 1.0:
        img = cv2.resize(img, (max(1, int(w * scale)), max(1, int(h * scale))),
                         interpolation=cv2.INTER_AREA)
    return img


def _score(path) -> dict:
    gray = _resize_gray(path)
    if gray is None:
        return {"sharpness": None, "exposure_flags": [], "error": "preview unreadable"}
    # Sharpest tile, not the whole frame: shallow-DOF portraits have smooth
    # backgrounds that drag a whole-frame variance down even when the subject is sharp.
    lap = cv2.Laplacian(gray, cv2.CV_64F)
    h, w = lap.shape
    sharpness = max(
        float(lap[r * h // TILES:(r + 1) * h // TILES, c * w // TILES:(c + 1) * w // TILES].var())
        for r in range(TILES) for c in range(TILES)
    )
    total = gray.size
    flags = []
    if np.count_nonzero(gray == 0) / total > CLIP_FRACTION:
        flags.append("underexposed")
    if np.count_nonzero(gray == 255) / total > CLIP_FRACTION:
        flags.append("overexposed")
    return {"sharpness": round(sharpness, 1), "exposure_flags": flags}


def run(images: list[dict], cached: dict) -> dict:
    """images: merged rows so far (each has path + preview). cached: already scored.

    Returns {path: {sharpness, exposure_flags}} for images not in cache.
    """
    rows: dict[str, dict] = {}
    for img in images:
        path = img.get("path")
        if not path or path in cached:
            continue
        preview = img.get("preview")
        if not preview:
            rows[path] = {"sharpness": None, "exposure_flags": [], "error": "no preview"}
            continue
        preview_path = config.CULL_ROOT / preview
        rows[path] = _score(preview_path)
    log.info("local_scores: scored %d images", len(rows))
    return rows
