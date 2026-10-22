"""Shared settings. Change only with both people agreeing."""
import os
from pathlib import Path

from dotenv import load_dotenv

REPO_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(REPO_ROOT / ".env")

CULL_ROOT = Path(os.getenv("CULL_ROOT", REPO_ROOT / "demo")).resolve()
SHOOT_DIR = CULL_ROOT / "shoot"
PREVIEW_DIR = CULL_ROOT / "previews"
WORK_DIR = CULL_ROOT / "work"
THUMB_DIR = WORK_DIR / "thumbs"

_scores = os.getenv("SCORES_PATH")
SCORES_PATH = (REPO_ROOT / _scores).resolve() if _scores and not Path(_scores).is_absolute() \
    else Path(_scores) if _scores else WORK_DIR / "scores.json"

# Overrides live beside scores.json, never inside it, so fixtures stay clean.
OVERRIDES_PATH = SCORES_PATH.with_name(SCORES_PATH.stem + ".overrides.json")

# Instruction agent: "anthropic" or "presets". Unset means anthropic when a key is present.
LLM_PROVIDER = os.getenv("LLM_PROVIDER") or ("anthropic" if os.getenv("ANTHROPIC_API_KEY")
                                             else "presets")
ANTHROPIC_AGENT_MODEL = os.getenv("ANTHROPIC_AGENT_MODEL", "claude-opus-5-5")
# low | medium | high | xhigh | max. Plans are a short translation task.
ANTHROPIC_EFFORT = os.getenv("ANTHROPIC_EFFORT", "low")

MAX_WORKERS = int(os.getenv("MAX_WORKERS", "6"))
MIN_FACE_WIDTH = float(os.getenv("MIN_FACE_WIDTH", "0.025"))
MIN_SHARPNESS = float(os.getenv("MIN_SHARPNESS", "170"))
# A gap longer than this between consecutive frames starts a new moment.
MOMENT_GAP_SECONDS = float(os.getenv("MOMENT_GAP_SECONDS", "90"))
# Coverage skips moments with fewer total frames than this (coverage rule's
# "min_frames" overrides it per plan).
COVERAGE_MIN_FRAMES = int(os.getenv("COVERAGE_MIN_FRAMES", "1"))

LABEL_BY_TAG = {
    "group": "Green",
    "dance floor": "Blue",
    "candid": "Yellow",
    "couple": "Purple",
    "food": "Red",
}


def label_for(tags):
    for tag in tags or []:
        if tag in LABEL_BY_TAG:
            return LABEL_BY_TAG[tag]
    return None
