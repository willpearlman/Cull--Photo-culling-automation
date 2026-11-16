"""Ingest stage: extract embedded previews, read EXIF, group bursts.

Exposes run(images, cached) per contracts.md. pipeline.py owns the cache file;
this module only computes and returns rows for newly seen images.

Speed: exiftool is slow per file, so it runs once per RAW (metadata plus the position of the
embedded preview) in several processes at once. Python then copies the preview bytes straight
out of the RAW. exiftool extracts a preview itself only when that direct read fails.
"""
from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import imagehash
from exiftool import ExifToolHelper
from exiftool.exceptions import ExifToolExecuteError
from PIL import Image

from . import config

log = logging.getLogger("cull.ingest")

# New burst when the time gap exceeds this, or the phash distance exceeds PHASH_MAX.
BURST_GAP_S = 2.0
PHASH_MAX = 10

# Files per exiftool execute call, and flags that silence warnings/minor errors.
CHUNK = 50
# exiftool processes reading metadata at once. More than 4 measured no faster.
META_PROCESSES = 4
THUMB_SIZE = (400, 400)  # grid thumbnail, served by /thumb
_QUIET = ["-q", "-q", "-m"]
_META_TAGS = [
    "DateTimeOriginal", "SubSecTimeOriginal", "Orientation",
    "ExposureTime", "ISO", "FocalLength", "Model",
]
# Where the embedded preview JPEG sits inside the RAW file.
_OFFSET_TAGS = ["PreviewImageStart", "PreviewImageLength"]

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


def _tag(tags: dict, name: str):
    """A tag's value whatever group exiftool reports it under (EXIF:, MakerNotes:, ...)."""
    for key, value in tags.items():
        if key == name or key.endswith(":" + name):
            return value
    return None


def _read_meta(files: list[Path]) -> dict[Path, dict]:
    """{resolved path: tags} for every file, from several stay-open exiftool processes."""
    chunks = [files[i:i + CHUNK] for i in range(0, len(files), CHUNK)]
    n = min(META_PROCESSES, len(chunks))

    def worker(mine):
        out = {}
        # Small chunks plus -q -q -m keep stderr tiny so the pipe buffer never fills
        # (PyExifTool deadlocks on Windows if it does).
        with ExifToolHelper(executable=config.EXIFTOOL) as et:
            for chunk in mine:
                for tags in et.get_tags([str(p) for p in chunk],
                                        tags=_META_TAGS + _OFFSET_TAGS, params=_QUIET):
                    src = tags.get("SourceFile")
                    if src:
                        out[Path(src).resolve()] = tags
        return out

    meta: dict[Path, dict] = {}
    with ThreadPoolExecutor(max_workers=n) as pool:
        for part in pool.map(worker, [chunks[i::n] for i in range(n)]):
            meta.update(part)
    return meta


def _copy_preview(src: Path, tags: dict, preview: Path) -> bool:
    """Copy the embedded preview JPEG straight out of the RAW. False if it is not where the
    tags say, so the caller can fall back to exiftool."""
    try:
        start = int(_tag(tags, "PreviewImageStart"))
        length = int(_tag(tags, "PreviewImageLength"))
        with open(src, "rb") as fh:
            fh.seek(start)
            data = fh.read(length)
    except (TypeError, ValueError, OSError):
        return False
    if length < 4 or len(data) != length or data[:2] != b"\xff\xd8":
        return False
    tmp = preview.with_suffix(".part")
    tmp.write_bytes(data)
    tmp.replace(preview)
    return True


def _extract_with_exiftool(files: list[Path]) -> None:
    """The slow path: exiftool writes each file's preview into PREVIEW_DIR."""
    with ExifToolHelper(executable=config.EXIFTOOL) as et:
        for start in range(0, len(files), CHUNK):
            chunk = files[start:start + CHUNK]
            try:
                et.execute(
                    *_QUIET, "-b", "-PreviewImage",
                    "-w", str(config.PREVIEW_DIR / "%f.jpg"),
                    *[str(p) for p in chunk],
                )
            except ExifToolExecuteError as exc:  # e.g. a file with no preview
                log.warning("ingest: preview chunk at %d had errors: %s", start, exc.stderr)


def write_thumb(im: Image.Image, dst: Path) -> None:
    """Save the grid thumbnail of an opened preview."""
    im.thumbnail(THUMB_SIZE)
    im.convert("RGB").save(dst, "JPEG")


def _hash_and_thumb(preview: Path):
    """The preview's phash (None if unreadable). Also writes the grid thumbnail from the same
    decode, so the grid never builds thumbnails while the photographer scrolls."""
    try:
        with Image.open(preview) as im:
            phash = imagehash.phash(im)
            thumb = config.THUMB_DIR / preview.name
            if not thumb.exists():
                write_thumb(im, thumb)
            return phash
    except (OSError, ValueError):
        return None


def run(images: list[dict], cached: dict) -> dict:
    """images: merged rows so far. cached: {path: row} already ingested.

    Returns {path: {ingest fields}} for ARW files not already in cache.
    """
    config.PREVIEW_DIR.mkdir(parents=True, exist_ok=True)
    config.THUMB_DIR.mkdir(parents=True, exist_ok=True)

    arw_files = sorted(config.SHOOT_DIR.glob("*.ARW"))
    todo = [p for p in arw_files if _rel(p) not in cached]
    if not todo:
        log.info("ingest: nothing new (%d already cached)", len(cached))
        return {}

    meta_by_path = _read_meta(todo)
    log.info("ingest: metadata for %d/%d", len(meta_by_path), len(todo))

    def preview_of(src: Path) -> Path:
        return config.PREVIEW_DIR / f"{src.stem}.jpg"

    def orientation(src: Path):
        tags = meta_by_path.get(src.resolve(), {})
        return tags.get("EXIF:Orientation") or tags.get("Orientation")

    def copy(src: Path) -> bool:
        ok = _copy_preview(src, meta_by_path.get(src.resolve(), {}), preview_of(src))
        if ok:
            _rotate_preview(preview_of(src), orientation(src))
        return ok

    # Only write previews that are missing: an existing one is already upright.
    need_preview = [p for p in todo if not preview_of(p).exists()]
    with ThreadPoolExecutor(max_workers=config.MAX_WORKERS) as pool:
        copied = list(pool.map(copy, need_preview))
        slow = [p for p, ok in zip(need_preview, copied) if not ok]
        if slow:
            log.info("ingest: exiftool extracts %d previews", len(slow))
            _extract_with_exiftool(slow)
            for src in slow:
                if preview_of(src).exists():
                    _rotate_preview(preview_of(src), orientation(src))
        have = [p for p in todo if preview_of(p).exists()]
        hashes = dict(zip(have, pool.map(lambda p: _hash_and_thumb(preview_of(p)), have)))
    log.info("ingest: previews %d/%d", len(have), len(todo))

    rows: dict[str, dict] = {}
    by_key: list[tuple[tuple[str, int], str, Path]] = []
    for src in todo:
        tags = meta_by_path.get(src.resolve(), {})
        rel = _rel(src)
        preview = config.PREVIEW_DIR / f"{src.stem}.jpg"
        preview_rel = _rel(preview) if preview.exists() else None
        rows[rel] = {
            "path": rel,
            "preview": preview_rel,
            "capture_time": _capture_iso(tags),
            "exposure_time": tags.get("EXIF:ExposureTime") or tags.get("ExposureTime"),
            "iso": tags.get("EXIF:ISO") or tags.get("ISO"),
            "focal_length": tags.get("EXIF:FocalLength") or tags.get("FocalLength"),
            "model": tags.get("EXIF:Model") or tags.get("Model"),
        }
        by_key.append((_capture_key(tags), rel, hashes.get(src)))

    # Bursts: sort by capture time then filename, split on time gap or phash jump.
    by_key.sort(key=lambda t: (t[0][0], t[1]))
    burst_n = 0
    prev_key: tuple[str, int] | None = None
    prev_hash = None
    for key, rel, cur_hash in by_key:
        new_burst = prev_key is None
        if prev_key is not None:
            gap = _seconds_between(prev_key, key)
            hash_jump = (
                prev_hash is not None
                and cur_hash is not None
                and (prev_hash - cur_hash) > PHASH_MAX
            )
            if (gap is not None and gap > BURST_GAP_S) or hash_jump:
                new_burst = True
            prev_hash = cur_hash if cur_hash is not None else prev_hash
        else:
            prev_hash = cur_hash
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
