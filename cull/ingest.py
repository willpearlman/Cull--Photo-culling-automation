"""Ingest stage: extract embedded previews, read EXIF, group bursts.

Exposes run(images, cached) per contracts.md. pipeline.py owns the cache file;
this module only computes and returns rows for newly seen images.
"""
from __future__ import annotations

import logging
from pathlib import Path

import imagehash
from exiftool import ExifToolHelper
from PIL import Image

from . import config

log = logging.getLogger("cull.ingest")

# New burst when the time gap exceeds this, or the phash distance exceeds PHASH_MAX.
BURST_GAP_S = 2.0
PHASH_MAX = 10

# ARW Orientation tag value -> degrees to rotate the preview counter-clockwise
# so it ends up upright. Pillow rotate is counter-clockwise.
_ROTATE = {1: 0, 3: 180, 6: 270, 8: 90}


def _rel(path: Path) -> str:
    """CULL_ROOT-relative POSIX path (forward slashes)."""
    try:
        return path.resolve().relative_to(config.CULL_ROOT).as_posix()
    except ValueError:
        return path.as_posix()


def _capture_key(tags: dict) -> tuple[str, int]:
    """Sort key: (DateTimeOriginal, SubSecTimeOriginal). Whole seconds for Sony."""
    dto = tags.get("EXIF:DateTimeOriginal") or tags.get("DateTimeOriginal") or ""
    sub = tags.get("EXIF:SubSecTimeOriginal") or tags.get("SubSecTimeOriginal")
    try:
        sub_i = int(str(sub)) if sub not in (None, "") else 0
    except (TypeError, ValueError):
        sub_i = 0
    return (str(dto), sub_i)


def _capture_iso(tags: dict) -> str | None:
    """EXIF 'YYYY:MM:DD HH:MM:SS' (+ optional subsec) -> ISO 8601 string."""
    dto = tags.get("EXIF:DateTimeOriginal") or tags.get("DateTimeOriginal")
    if not dto:
        return None
    date_part, _, time_part = str(dto).partition(" ")
    date_iso = date_part.replace(":", "-")
    sub = tags.get("EXIF:SubSecTimeOriginal") or tags.get("SubSecTimeOriginal")
    try:
        sub_i = int(str(sub)) if sub not in (None, "") else 0
    except (TypeError, ValueError):
        sub_i = 0
    millis = f".{sub_i:03d}" if sub_i else ".000"
    return f"{date_iso}T{time_part}{millis}"


def _rotate_preview(preview_path: Path, orientation) -> None:
    try:
        deg = _ROTATE.get(int(orientation), 0)
    except (TypeError, ValueError):
        deg = 0
    if not deg:
        return
    try:
        with Image.open(preview_path) as im:
            im.rotate(deg, expand=True).save(preview_path, quality=92)
    except (OSError, ValueError) as exc:
        log.warning("rotate failed for %s: %s", preview_path.name, exc)


def _phash(preview_path: Path):
    try:
        with Image.open(preview_path) as im:
            return imagehash.phash(im)
    except (OSError, ValueError):
        return None


def run(images: list[dict], cached: dict) -> dict:
    """images: merged rows so far. cached: {path: row} already ingested.

    Returns {path: {ingest fields}} for ARW files not already in cache.
    """
    config.PREVIEW_DIR.mkdir(parents=True, exist_ok=True)

    arw_files = sorted(config.SHOOT_DIR.glob("*.ARW"))
    todo = [p for p in arw_files if _rel(p) not in cached]
    if not todo:
        log.info("ingest: nothing new (%d already cached)", len(cached))
        return {}

    with ExifToolHelper() as et:
        # One stay-open process extracts every preview to previews/%f.jpg.
        et.execute(
            "-b",
            "-PreviewImage",
            "-w",
            str(config.PREVIEW_DIR / "%f.jpg"),
            "-ext",
            "ARW",
            str(config.SHOOT_DIR),
        )
        meta = et.get_tags(
            [str(p) for p in todo],
            tags=[
                "DateTimeOriginal",
                "SubSecTimeOriginal",
                "Orientation",
                "ExposureTime",
                "ISO",
                "FocalLength",
                "Model",
            ],
        )

    rows: dict[str, dict] = {}
    by_key: list[tuple[tuple[str, int], str, Path]] = []
    for src, tags in zip(todo, meta):
        rel = _rel(src)
        preview = config.PREVIEW_DIR / f"{src.stem}.jpg"
        if preview.exists():
            _rotate_preview(preview, tags.get("EXIF:Orientation") or tags.get("Orientation"))
            preview_rel = _rel(preview)
        else:
            preview_rel = None
        rows[rel] = {
            "path": rel,
            "preview": preview_rel,
            "capture_time": _capture_iso(tags),
            "exposure_time": tags.get("EXIF:ExposureTime") or tags.get("ExposureTime"),
            "iso": tags.get("EXIF:ISO") or tags.get("ISO"),
            "focal_length": tags.get("EXIF:FocalLength") or tags.get("FocalLength"),
            "model": tags.get("EXIF:Model") or tags.get("Model"),
        }
        by_key.append((_capture_key(tags), rel, preview))

    # Bursts: sort by capture time then filename, split on time gap or phash jump.
    by_key.sort(key=lambda t: (t[0][0], t[1]))
    burst_n = 0
    prev_key: tuple[str, int] | None = None
    prev_hash = None
    for key, rel, preview in by_key:
        new_burst = prev_key is None
        if prev_key is not None:
            gap = _seconds_between(prev_key, key)
            cur_hash = _phash(preview)
            hash_jump = (
                prev_hash is not None
                and cur_hash is not None
                and (prev_hash - cur_hash) > PHASH_MAX
            )
            if (gap is not None and gap > BURST_GAP_S) or hash_jump:
                new_burst = True
            prev_hash = cur_hash if cur_hash is not None else prev_hash
        else:
            prev_hash = _phash(preview)
        if new_burst:
            burst_n += 1
        rows[rel]["burst_id"] = f"B{burst_n:03d}"
        prev_key = key

    log.info("ingest: %d new images, %d bursts", len(rows), burst_n)
    return rows


def _seconds_between(a: tuple[str, int], b: tuple[str, int]) -> float | None:
    """Approximate seconds between two (datetime, subsec) keys."""
    from datetime import datetime

    def parse(k):
        try:
            dt = datetime.strptime(k[0], "%Y:%m:%d %H:%M:%S")
        except (ValueError, TypeError):
            return None
        return dt.timestamp() + (k[1] / 1000.0 if k[1] else 0.0)

    ta, tb = parse(a), parse(b)
    if ta is None or tb is None:
        return None
    return abs(tb - ta)
