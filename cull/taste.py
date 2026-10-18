"""Taste stage: Claude scores finalist frames. AWS and logic lane (Teammate 3), task 11.

Finalists only (see design.md). One Bedrock Converse call per finalist with the
1024px preview and a forced submit_score tool. Never touches cache files.
"""
import io
import logging
import threading
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor

import boto3
from botocore.config import Config
from PIL import Image

from cull import config

log = logging.getLogger(__name__)

LONG_EDGE = 1024
JPEG_QUALITY = 85
TOP_PER_BURST = 2
MAX_REASON_WORDS = 12

SCORE_SCHEMA = {
    "type": "object",
    "properties": {
        "score": {"type": "integer", "minimum": 1, "maximum": 10,
                  "description": "Keeper quality, 1 (reject) to 10 (portfolio)."},
        "reason": {"type": "string",
                   "description": "12 words or fewer, specific to this frame."},
        "candid": {"type": "boolean",
                   "description": "True if unposed: subjects not posing for the camera."},
        "intentional_eyes_closed": {
            "type": "boolean",
            "description": "True if closed eyes are deliberate (kiss, laughing, prayer, "
                           "embrace), false for a blink or if all eyes are open."},
    },
    "required": ["score", "reason", "candid", "intentional_eyes_closed"],
}

SYSTEM = """You are a senior event photographer culling a client's shoot.
Score each frame as a keeper for the client gallery and call submit_score exactly once.

Score: 9-10 standout (peak expression, strong light and composition); 7-8 solid keeper;
5-6 usable filler; 3-4 weak (awkward expression, cluttered, mistimed); 1-2 reject.
Judge expression, moment, eye contact or connection, light on faces, composition, crop.

Reason: a terse fragment of at most 12 words (hard limit, longer text is cut off).
Name what is specific to THIS frame, e.g.
"Bride mid-laugh, groom looking at her, warm backlight" or
"Man on left mid-blink, others fine, cluttered background".
Never write generic praise like "nice photo" or "good composition"."""

_client = None
_client_lock = threading.Lock()


def _bedrock():
    global _client
    with _client_lock:
        if _client is None:
            _client = boto3.client(
                "bedrock-runtime", region_name=config.AWS_REGION,
                config=Config(retries={"mode": "adaptive", "max_attempts": 6}))
    return _client


def _image_bytes(preview_path):
    with Image.open(preview_path) as img:
        img = img.convert("RGB")
        img.thumbnail((LONG_EDGE, LONG_EDGE))
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=JPEG_QUALITY)
        return buf.getvalue()


def _quality_ok(img):
    sharp = img.get("sharpness")
    return sharp is not None and sharp >= config.MIN_SHARPNESS and not img.get("exposure_flags")


def finalists(images):
    """Sharp, unflagged frames: top 2 per burst by sharpness, plus possible intentional moments."""
    good = [im for im in images if _quality_ok(im)]
    by_burst = defaultdict(list)
    for im in good:
        by_burst[im.get("burst_id") or im["path"]].append(im)
    chosen = set()
    for frames in by_burst.values():
        frames.sort(key=lambda im: (-im["sharpness"], im["path"]))
        chosen.update(im["path"] for im in frames[:TOP_PER_BURST])
    chosen.update(im["path"] for im in good
                  if (im.get("eyes_closed_count") or 0) > 0 and (im.get("face_count") or 0) <= 2)
    return [im for im in images if im["path"] in chosen]


def _short(reason):
    words = str(reason or "").split()
    if len(words) <= MAX_REASON_WORDS:
        return " ".join(words)
    words = words[:MAX_REASON_WORDS]
    # Drop a dangling joiner left by the cut ("...mixed engagement and").
    while words and words[-1].lower().strip(",;") in {"and", "but", "or", "with", "the", "a"}:
        words.pop()
    return " ".join(words).rstrip(",;")


def _context(img):
    faces, closed = img.get("face_count"), img.get("eyes_closed_count")
    if faces is None:
        return "Score this frame."
    return (f"Detector: {faces} face(s), {closed or 0} with eyes closed, "
            f"tags {img.get('scene_tags') or []}. Score this frame.")


def score(img):
    """One Converse call for one image. Returns the taste fields (or an error)."""
    try:
        if not config.BEDROCK_TASTE_MODEL_ID:
            raise RuntimeError("BEDROCK_TASTE_MODEL_ID is not set")
        b = _image_bytes(config.CULL_ROOT / img["preview"])
        resp = _bedrock().converse(
            modelId=config.BEDROCK_TASTE_MODEL_ID,
            system=[{"text": SYSTEM}],
            messages=[{"role": "user", "content": [
                {"image": {"format": "jpeg", "source": {"bytes": b}}},
                {"text": _context(img)},
            ]}],
            toolConfig={
                "tools": [{"toolSpec": {"name": "submit_score",
                                        "description": "Submit the score for this frame.",
                                        "inputSchema": {"json": SCORE_SCHEMA}}}],
                "toolChoice": {"tool": {"name": "submit_score"}},
            },
            inferenceConfig={"maxTokens": 200},
        )
        content = resp["output"]["message"]["content"]
        raw = next((c["toolUse"]["input"] for c in content if "toolUse" in c), None)
        if raw is None:
            raise RuntimeError("model did not call submit_score")
        return {
            "claude_score": max(1, min(10, int(raw.get("score", 5)))),
            "claude_reason": _short(raw.get("reason")),
            "intentional_eyes_closed": raw.get("intentional_eyes_closed") is True,
            "candid": raw.get("candid") is True,
        }
    except Exception as exc:  # a failed image never stops the stage
        return {"claude_score": None, "claude_reason": None,
                "intentional_eyes_closed": False, "candid": False,
                "error": f"{type(exc).__name__}: {str(exc)[:80]}"}


def run(images, cached):
    todo = [im for im in finalists(images) if im["path"] not in cached]
    print(f"taste: {len(todo)} finalists to score ({len(images)} images in)")
    if not todo:
        return {}
    with ThreadPoolExecutor(max_workers=config.MAX_WORKERS) as pool:
        results = list(pool.map(score, todo))
    out = {im["path"]: res for im, res in zip(todo, results)}
    errors = sum("error" in r for r in out.values())
    log.info("taste: %d scored, %d errors", len(out) - errors, errors)
    return out


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    previews = sorted(config.PREVIEW_DIR.glob("*.jpg"))[:3]
    for p in previews:
        rel = p.relative_to(config.CULL_ROOT).as_posix()
        r = score({"path": rel, "preview": rel})
        print(f"{p.name}  score={r['claude_score']}  candid={r['candid']}  "
              f"intentional={r['intentional_eyes_closed']}  reason={r['claude_reason']!r}"
              + (f"  error={r['error']}" if "error" in r else ""))
