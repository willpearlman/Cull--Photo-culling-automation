"""Per-user settings (not per shoot), stored as JSON in the user's settings folder.

Windows: %APPDATA%\\Cull\\settings.json. macOS: ~/Library/Application Support/Cull/settings.json.
Other: ~/.config/cull/settings.json. CULL_SETTINGS overrides the path (tests, portable installs).
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

LIGHTROOM_MODES = ("classic", "cloud")
DEFAULTS = {"lightroom": None, "recent_shoots": []}


def path() -> Path:
    if os.getenv("CULL_SETTINGS"):
        return Path(os.environ["CULL_SETTINGS"])
    if sys.platform == "win32":
        base = Path(os.getenv("APPDATA") or Path.home() / "AppData" / "Roaming") / "Cull"
    elif sys.platform == "darwin":
        base = Path.home() / "Library" / "Application Support" / "Cull"
    else:
        base = Path.home() / ".config" / "cull"
    return base / "settings.json"


def load() -> dict:
    try:
        stored = json.loads(path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        stored = {}
    out = dict(DEFAULTS)
    out.update({k: v for k, v in stored.items() if k in DEFAULTS})
    if out["lightroom"] not in LIGHTROOM_MODES:
        out["lightroom"] = None
    if not isinstance(out["recent_shoots"], list):
        out["recent_shoots"] = []
    return out


def update(changes: dict) -> dict:
    """Validate and save changes. Raises ValueError for an unknown key or bad value."""
    current = load()
    for key, value in changes.items():
        if key not in DEFAULTS:
            raise ValueError(f"unknown setting {key!r}")
        if key == "lightroom" and value not in LIGHTROOM_MODES:
            raise ValueError(f"lightroom must be one of {LIGHTROOM_MODES}")
        if key == "recent_shoots" and not (
                isinstance(value, list) and all(isinstance(v, str) for v in value)):
            raise ValueError("recent_shoots must be a list of folder paths")
        current[key] = value
    p = path()
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(current, indent=2), encoding="utf-8")
    tmp.replace(p)
    return current
