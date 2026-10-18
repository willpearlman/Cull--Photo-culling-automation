"""Rekognition stage: faces, eyes, smiles, and scene tags per preview.

Uses only DetectFaces and DetectLabels. Never touches face collections
(no IndexFaces, SearchFaces, or any collection API).
"""
import io
import json
import logging
import threading
from concurrent.futures import ThreadPoolExecutor

import boto3
from botocore.config import Config
from PIL import Image

from cull import config

log = logging.getLogger(__name__)

LONG_EDGE = 1600
JPEG_QUALITY = 85
MIN_ATTR_CONFIDENCE = 80
RELATIVE_FACE_WIDTH = 0.25  # fraction of the largest face's width

GROUP_LABELS = {"Crowd", "Audience", "Team"}
DANCE_LABELS = {"Dance Pose", "Night Life", "Party", "Disco", "Club", "Dancing"}
FOOD_LABELS = {"Food", "Meal", "Dinner", "Dish", "Cake"}
DETAIL_LABELS = {"Flower", "Jewelry", "Decoration", "Table Setting"}
INDOOR_LABELS = {"Indoors"}
OUTDOOR_LABELS = {"Outdoors", "Nature", "Sky"}

_client = None


_client_lock = threading.Lock()


def _rekognition():
    """One shared client (boto3 clients are thread-safe; creation is not)."""
    global _client
    with _client_lock:
        if _client is None:
            _client = boto3.client(
                "rekognition",
                region_name=config.AWS_REGION,
                config=Config(retries={"mode": "adaptive", "max_attempts": 6}),
            )
    return _client


def _image_bytes(preview_path):
    """Resize to 1600px long edge, JPEG q85 (stays under the 5 MB limit)."""
    with Image.open(preview_path) as img:
        img = img.convert("RGB")
        img.thumbnail((LONG_EDGE, LONG_EDGE))
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=JPEG_QUALITY)
        return buf.getvalue()


def _confident(attr, value):
    return bool(attr) and attr.get("Value") is value and attr.get("Confidence", 0) >= MIN_ATTR_CONFIDENCE


def _face_fields(face_details):
    # Keep faces above the absolute floor AND at least 25% of the largest face,
    # so blurry bystanders behind a subject don't count, but group shots keep everyone.
    widths = [f["BoundingBox"]["Width"] for f in face_details]
    floor = max(config.MIN_FACE_WIDTH, RELATIVE_FACE_WIDTH * max(widths, default=0))
    kept = [f for f in face_details if f["BoundingBox"]["Width"] >= floor]
    return {
        "face_count": len(kept),
        "eyes_closed_count": sum(_confident(f.get("EyesOpen"), False) for f in kept),
        "smile_count": sum(_confident(f.get("Smile"), True) for f in kept),
    }


def _scene_tags(face_count, labels):
    tags = []
    if face_count >= 4 or labels & GROUP_LABELS:
        tags.append("group")
    if face_count == 2:
        tags.append("couple")
    if face_count == 1:
        tags.append("portrait")
    if labels & DANCE_LABELS:
        tags.append("dance floor")
    if labels & FOOD_LABELS:
        tags.append("food")
    if face_count == 0 and labels & DETAIL_LABELS:
        tags.append("detail")
    if labels & INDOOR_LABELS:
        tags.append("indoor")
    if labels & OUTDOOR_LABELS:
        tags.append("outdoor")
    return tags


def _blurry(image):
    sharpness = image.get("sharpness")
    return sharpness is not None and sharpness < config.MIN_SHARPNESS


def _empty():
    return {"face_count": 0, "eyes_closed_count": 0, "smile_count": 0, "scene_tags": []}


def _process(image):
    if _blurry(image):
        return _empty()
    try:
        b = _image_bytes(config.CULL_ROOT / image["preview"])
        client = _rekognition()
        faces = client.detect_faces(Image={"Bytes": b}, Attributes=["ALL"])
        labels = client.detect_labels(Image={"Bytes": b}, MaxLabels=25, MinConfidence=70)
        fields = _face_fields(faces.get("FaceDetails", []))
        names = {lab["Name"] for lab in labels.get("Labels", [])}
        fields["scene_tags"] = _scene_tags(fields["face_count"], names)
        return fields
    except Exception as exc:  # a failed image never stops the stage
        out = _empty()
        out["error"] = f"{type(exc).__name__}: {str(exc)[:80]}"
        return out


def run(images, cached):
    todo = [im for im in images if im["path"] not in cached]
    if not todo:
        return {}
    with ThreadPoolExecutor(max_workers=config.MAX_WORKERS) as pool:
        results = list(pool.map(_process, todo))
    out = {im["path"]: res for im, res in zip(todo, results)}
    errors = sum("error" in r for r in out.values())
    skipped = sum(_blurry(im) for im in todo)
    log.info("rekog: %d images, %d skipped blurry, %d errors", len(todo), skipped, errors)
    return out


if __name__ == "__main__":
    logging.basicConfig(level=logging.WARNING, format="%(message)s")
    log.setLevel(logging.INFO)
    rows = json.loads(config.SCORES_PATH.read_text(encoding="utf-8"))["images"]
    results = run(rows, {})
    for row in rows:
        r = results[row["path"]]
        name = row["path"].rsplit("/", 1)[-1]
        if _blurry(row):
            print(f"{name}  sharpness={row.get('sharpness')}  skipped: blurry")
        else:
            print(f"{name}  sharpness={row.get('sharpness')}  faces={r['face_count']}  "
                  f"eyes_closed={r['eyes_closed_count']}  smiles={r['smile_count']}  "
                  f"tags={r['scene_tags']}" + (f"  error={r['error']}" if "error" in r else ""))
