"""Shared settings and the paths of the shoot that is open.

Every module reads the shoot paths (CULL_ROOT, SHOOT_DIR, PREVIEW_DIR, WORK_DIR, THUMB_DIR,
SCORES_PATH, OVERRIDES_PATH) from here at call time, so set_shoot() switches shoots while the
app runs.
"""
import hashlib
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

# Packaged app (PyInstaller): code, static files, fixtures and models sit under sys._MEIPASS.
FROZEN = getattr(sys, "frozen", False)
REPO_ROOT = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent.parent))
load_dotenv(REPO_ROOT / ".env")

if sys.platform == "win32":
    APP_DATA = Path(os.getenv("LOCALAPPDATA") or Path.home() / "AppData" / "Local") / "Cull"
elif sys.platform == "darwin":
    APP_DATA = Path.home() / "Library" / "Application Support" / "Cull"
else:
    APP_DATA = Path.home() / ".cache" / "cull"

# exiftool: bundled in the packaged app, from PATH in development.
EXIFTOOL = str(REPO_ROOT / "exiftool" / "exiftool.exe") if FROZEN and sys.platform == "win32" \
    else os.getenv("EXIFTOOL", "exiftool")

# Development: CULL_ROOT in .env opens that shoot at startup. The app starts with none open.
SHOOT_FROM_ENV = bool(os.getenv("CULL_ROOT"))
CULL_ROOT = SHOOT_DIR = PREVIEW_DIR = WORK_DIR = THUMB_DIR = SCORES_PATH = OVERRIDES_PATH = None


def cache_root(raw_dir):
    """Where previews and caches for a RAW folder live: outside it, keyed by its full path."""
    raw_dir = Path(raw_dir).resolve()
    key = hashlib.sha1(str(raw_dir).lower().encode("utf-8")).hexdigest()[:10]
    return APP_DATA / "shoots" / f"{raw_dir.name}-{key}"


def set_shoot(folder):
    """Open a shoot. `folder` is either the folder of RAW files (the app's normal case:
    previews and caches go to cache_root) or a development work folder holding shoot/*.ARW."""
    global CULL_ROOT, SHOOT_DIR, PREVIEW_DIR, WORK_DIR, THUMB_DIR, SCORES_PATH, OVERRIDES_PATH
    folder = Path(folder).resolve()
    if (folder / "shoot").is_dir():
        CULL_ROOT, SHOOT_DIR = folder, folder / "shoot"
    else:
        CULL_ROOT, SHOOT_DIR = cache_root(folder), folder
    PREVIEW_DIR = CULL_ROOT / "previews"
    WORK_DIR = CULL_ROOT / "work"
    THUMB_DIR = WORK_DIR / "thumbs"
    scores = os.getenv("SCORES_PATH")
    SCORES_PATH = (REPO_ROOT / scores).resolve() if scores and not Path(scores).is_absolute() \
        else Path(scores) if scores else WORK_DIR / "scores.json"
    # Overrides live beside scores.json, never inside it, so fixtures stay clean.
    OVERRIDES_PATH = SCORES_PATH.with_name(SCORES_PATH.stem + ".overrides.json")


set_shoot(os.getenv("CULL_ROOT", REPO_ROOT / "demo"))

# Shoot genre: picks the extra scene tags (fixtures/vocab.json) and the agent's tag vocabulary.
# "wedding" or "event" (base tags only).
GENRE = os.getenv("GENRE", "wedding")
# Frames kept when an instruction gives no number.
DEFAULT_KEEP_FRACTION = float(os.getenv("DEFAULT_KEEP_FRACTION", "0.1"))

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
