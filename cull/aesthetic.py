"""Local aesthetic stage. Offline replacement for the Claude taste stage.

A ridge regression head (fixtures/aesthetic_head.npz) predicts a 1 to 10 keeper score from the
SigLIP image vector (scenes stage) plus sharpness, exposure and face features (faces stage).
The head is trained by tools/train_aesthetic.py on Claude's taste scores from past shoots.
On top of it, cull/personal.py adds a shift learned from this photographer's overrides.

Fills the taste fields: claude_score (1 to 10, one decimal, every frame), claude_reason (a
template, no LLM), candid (SigLIP zero-shot), intentional_eyes_closed (a closed-eyed face that
is also smiling, e.g. laughing).
"""
from __future__ import annotations

import logging
import math

import numpy as np

from cull import config, faces, scenes

log = logging.getLogger(__name__)

HEAD_PATH = config.REPO_ROOT / "fixtures" / "aesthetic_head.npz"
CANDID_THRESHOLD = -0.05  # SigLIP candid score; F1 0.94 against Claude's labels on shoot2
EXTRA_FEATURES = ["log_sharpness", "exposure_flag", "face_count", "eyes_closed", "smiles",
                  "max_face_width", "zs_aesthetic", "zs_candid"]

_head = None


def extras(row):
    """Hand features for one merged row, in EXTRA_FEATURES order. Faces come from the raw
    faces-stage list, so rekog values merged into the row never leak in."""
    raw = row.get("faces") or []
    s = faces.summarize(raw)
    zs = row.get("scene_scores") or {}
    return [
        math.log1p(float(row.get("sharpness") or 0.0)),
        1.0 if row.get("exposure_flags") else 0.0,
        float(min(s["face_count"], 10)),
        float(s["eyes_closed_count"]),
        float(s["smile_count"]),
        max((f["w"] for f in raw), default=0.0),
        float(zs.get("aesthetic", 0.0)),
        float(zs.get("candid", 0.0)),
    ]


def features(rows):
    """(n, 768 + len(EXTRA_FEATURES)) matrix: image vector, then raw hand features."""
    vecs = np.stack([scenes.unpack(r["embedding"]) for r in rows])
    return np.hstack([vecs, np.array([extras(r) for r in rows], dtype=np.float32)])


def fit(x, y, alpha):
    """Ridge regression: every column centered (so the intercept is unpenalized), hand features
    also scaled to unit variance. Returns the head as a dict."""
    n_emb = x.shape[1] - len(EXTRA_FEATURES)
    mean = x.mean(0)
    std = np.concatenate([np.ones(n_emb), x[:, n_emb:].std(0) + 1e-6])
    z = (x - mean) / std
    y_mean = y.mean()
    w = np.linalg.solve(z.T @ z + alpha * np.eye(z.shape[1]), z.T @ (y - y_mean))
    return {"w": w.astype(np.float32), "b": np.float32(y_mean), "mean": mean.astype(np.float32),
            "std": std.astype(np.float32), "alpha": np.float32(alpha)}


def predict(head, x):
    return ((x - head["mean"]) / head["std"]) @ head["w"] + head["b"]


def _load_head():
    global _head
    if _head is None:
        data = np.load(HEAD_PATH)
        _head = {k: data[k] for k in data.files}
    return _head


def reason(row, score):
    """Short template reason from the measured features (no LLM)."""
    s = faces.summarize(row.get("faces") or [])
    parts = ["strong frame" if score >= 6.5 else "solid frame" if score >= 5 else "weaker frame"]
    if s["face_count"]:
        parts.append(f"{s['face_count']} face{'s' if s['face_count'] > 1 else ''}")
        if s["smile_count"]:
            parts.append(f"{s['smile_count']} smiling")
        if s["eyes_closed_count"]:
            parts.append(f"{s['eyes_closed_count']} eyes closed")
    if row.get("exposure_flags"):
        parts.append(", ".join(row["exposure_flags"]))
    return ", ".join(parts).capitalize()


def _intentional(row):
    return any((f["blink"] or 0) > faces.BLINK_THRESHOLD and (f["smile"] or 0) > faces.SMILE_THRESHOLD
               for f in row.get("faces") or [])


def run(images, cached):
    todo = [im for im in images if im["path"] not in cached and im.get("embedding")]
    if not todo:
        return {}
    from cull import personal  # imports this module, so load it at call time
    x = features(todo)
    base = np.clip(predict(_load_head(), x), 1.0, 10.0)
    pred = np.clip(base + personal.shift(x), 1.0, 10.0)
    out = {}
    for im, b, p in zip(todo, base, pred):
        score = round(float(p), 1)
        out[im["path"]] = {
            "claude_score": score,
            "base_score": round(float(b), 1),  # before the photographer's learned shift
            "claude_reason": reason(im, score),
            "candid": (im.get("scene_scores") or {}).get("candid", -1.0) > CANDID_THRESHOLD,
            "intentional_eyes_closed": _intentional(im),
        }
    log.info("aesthetic: %d images", len(out))
    return out
