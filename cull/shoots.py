"""Open a shoot and process it in the background, with progress the UI can poll.

One job at a time. open_folder() switches config to the folder, then a thread runs every
pipeline stage and merge. status() reports the state, current stage and overall progress
(weighted by each stage's share of a measured run: 749 frames, 143 s).
"""
from __future__ import annotations

import threading
import time
from pathlib import Path

from cull import config, pipeline, settings

RAW_EXTENSIONS = (".arw",)
# Share of total time per stage, from the shoot2 fresh run (ingest 67 s, scenes 41 s, ...).
WEIGHTS = {"ingest": 0.47, "local": 0.05, "faces": 0.19, "scenes": 0.28, "moments": 0.003,
           "aesthetic": 0.005, "merge": 0.002}
STAGE_NAMES = {"ingest": "Reading RAW files", "local": "Checking sharpness and exposure",
               "faces": "Finding faces and blinks", "scenes": "Recognizing scenes",
               "moments": "Grouping moments", "aesthetic": "Scoring frames",
               "merge": "Finishing"}
MAX_RECENT = 8

_lock = threading.Lock()
_status = {"state": "idle", "folder": None, "frames": 0, "stage": None, "label": "",
           "progress": 0.0, "message": "", "started": None}


def count_raws(folder):
    return sum(1 for p in Path(folder).iterdir() if p.suffix.lower() in RAW_EXTENSIONS)


def status():
    with _lock:
        out = dict(_status)
    out["elapsed"] = round(time.time() - out["started"], 1) if out["started"] else 0
    return out


def mark_ready(folder):
    """A shoot that is already processed (e.g. opened from .env in development)."""
    with _lock:
        _status.update(state="ready", folder=str(folder), progress=1.0, stage=None, label="",
                       message="", started=None)


def _set(**kw):
    with _lock:
        _status.update(kw)


def _remember(folder):
    recent = [f for f in settings.load().get("recent_shoots", []) if f != folder]
    settings.update({"recent_shoots": [folder, *recent][:MAX_RECENT]})


def open_folder(folder):
    """Validate the folder, switch to it and start processing. Raises ValueError for a bad
    folder and RuntimeError while another shoot is still processing."""
    folder = Path(folder).expanduser()
    if not folder.is_dir():
        raise ValueError(f"Not a folder: {folder}")
    raw_dir = folder / "shoot" if (folder / "shoot").is_dir() else folder
    n = count_raws(raw_dir)
    if n == 0:
        raise ValueError("No Sony RAW (.ARW) files in that folder.")
    with _lock:
        if _status["state"] == "running":
            raise RuntimeError("Another shoot is still being processed.")
        _status.update(state="running", folder=str(folder), frames=n, stage=None,
                       label="Starting", progress=0.0, message="", started=time.time())
    config.set_shoot(folder)
    try:
        _remember(str(folder))
    except Exception:
        pass  # recent list is a convenience
    threading.Thread(target=_run, daemon=True, name="cull-pipeline").start()


def _run():
    done = 0.0
    try:
        for stage in [*pipeline.STAGE_ORDER, "merge"]:
            _set(stage=stage, label=STAGE_NAMES[stage], progress=round(done, 3))
            if stage == "merge":
                pipeline.merge(None)
            else:
                pipeline.run_stage(stage, None, raise_errors=True)
            done += WEIGHTS[stage]
        _set(state="ready", stage=None, label="", progress=1.0)
    except Exception as exc:
        _set(state="error", message=f"{STAGE_NAMES.get(_status['stage'], 'Processing')} failed: "
                                    f"{type(exc).__name__}: {str(exc)[:200]}")
