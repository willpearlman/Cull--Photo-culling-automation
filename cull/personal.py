"""Personal taste: learn from the photographer's overrides, per user, across shoots.

Learns from the photographer's final selection, recorded at export: every kept frame (5) and
every frame they rejected (1). Each is a relative judgment inside a moment. A kept frame beats
the other usable frames in its moment and anything rejected there; a rejected frame loses to
what was kept in its moment (only that: rejects are Cull's high scorers, so pairing them against
ordinary frames teaches that worse is better).

Frames are compared on the aesthetic hand features (sharpness, exposure, faces, closed eyes,
smiles, face size, zero-shot aesthetic and candid scores), standardized by
fixtures/taste_basis.npz. A ridge model on the pairwise differences gives a direction of
preference. aesthetic.run adds the resulting shift, SHIFT_SCALE points per standard deviation,
capped at MAX_SHIFT, to every frame of every later shoot.

Only running sums are stored, per shoot (beside settings.json, in taste_examples.json): no frame
features or paths. Re-recording a shoot replaces its sums. Evaluated on shoot2 leave-one-moment-
out (tools/eval_personal.py): held-out AUC of Will's five-stars 0.537 -> 0.575.
"""
from __future__ import annotations

import json
import logging

import numpy as np

from cull import aesthetic, config, settings

log = logging.getLogger(__name__)

BASIS_PATH = config.REPO_ROOT / "fixtures" / "taste_basis.npz"
# Image-vector components. 0 = the 8 hand features only. A basis built across shoots spends its
# components telling shoots apart (conference vs travel), not frames within a moment, and lost
# most of the held-out gain (tools/eval_personal.py).
K = 0
ALPHA = 10.0
MIN_OVERRIDES = 8
SHIFT_SCALE = 1.0  # points per standard deviation of the learned preference
MAX_SHIFT = 2.0

_basis = None


def _dir():
    return settings.path().parent


def examples_path():
    return _dir() / "taste_examples.json"


def _load_basis():
    global _basis
    if _basis is None:
        data = np.load(BASIS_PATH)
        _basis = {k: data[k] for k in ("emb_mean", "components", "feat_mean", "feat_std")}
    return _basis


def reduce(x):
    """(n, 776) aesthetic features -> (n, K + 8) standardized taste features."""
    b = _load_basis()
    n_emb = b["emb_mean"].shape[0]
    z = np.hstack([(x[:, :n_emb] - b["emb_mean"]) @ b["components"].T, x[:, n_emb:]])
    return (z - b["feat_mean"]) / b["feat_std"]


def load_examples():
    try:
        return json.loads(examples_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _save_examples(examples):
    p = examples_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(examples), encoding="utf-8")
    tmp.replace(p)


_rows_cache = {}


def shoot_rows(work_dir):
    """Merged local/faces/scenes/moments cache rows for one shoot (read-only), reloaded only
    when the scenes cache changes. Used to turn overrides into features."""
    scenes_file = work_dir / "scenes.json"
    try:
        stamp = scenes_file.stat().st_mtime
    except OSError:
        return []
    key = str(work_dir)
    if key not in _rows_cache or _rows_cache[key][0] != stamp:
        caches = []
        for name in ("local.json", "faces.json", "scenes.json", "moments.json"):
            try:
                caches.append(json.loads((work_dir / name).read_text(encoding="utf-8")))
            except (OSError, ValueError):
                caches.append({})
        rows = []
        for path in caches[2]:
            row = {"path": path}
            for c in caches:
                row.update(c.get(path) or {})
            rows.append(row)
        _rows_cache[key] = (stamp, rows)
    return _rows_cache[key][1]


def _usable(row):
    """Frames a kept frame is compared against. Badly exposed frames stay in: without them the
    model never sees a kept frame beat one, so it cannot learn that exposure matters."""
    return (row.get("sharpness") or 0) >= config.MIN_SHARPNESS


def shoot_sums(rows, overrides):
    """Running sums for one shoot: pairwise A, b over override pairs, and frame moments C, m, n
    for scaling. None when no override can be paired."""
    rows = [r for r in rows if r.get("embedding")]
    idx = {r["path"]: i for i, r in enumerate(rows)}
    chosen = {p: v for p, v in overrides.items() if p in idx and v in (1, 5)}
    if not chosen:
        return None
    z = reduce(aesthetic.features(rows))
    group = [r.get("group_id") for r in rows]
    d_all, w_all, frames = [], [], set()
    for p, v in chosen.items():
        i = idx[p]
        kept = [idx[q] for q, u in chosen.items() if u == 5 and group[idx[q]] == group[i]]
        if v == 5:
            # A kept frame beats the moment's other usable frames and anything rejected there.
            others = [j for j, r in enumerate(rows) if group[j] == group[i] and j != i
                      and _usable(r) and r["path"] not in chosen]
            others += [idx[q] for q, u in chosen.items() if u == 1 and group[idx[q]] == group[i]]
        else:
            # A reject only loses to what was kept in its moment. Pairing it against every
            # ordinary frame taught "lower quality is better", since rejects are Cull's high scorers.
            others = kept
        if not others:
            continue
        sign = 1.0 if v == 5 else -1.0
        d_all.append(sign * (z[i] - z[others]))
        w_all.append(np.ones(len(others)))  # unweighted beat per-override balancing (0.575 vs 0.542)
        frames.update([i, *others])
    if not d_all:
        return None
    d, w = np.vstack(d_all), np.concatenate(w_all)
    zf = z[sorted(frames)]
    return {"A": (d.T * w) @ d, "b": (d.T * w).sum(1), "C": zf.T @ zf, "m": zf.sum(0),
            "n": len(zf), "overrides": len(chosen)}


def record(shoot, rows, overrides):
    """Replace this shoot's sums with ones built from its current overrides, then report how
    many overrides the model now learns from (0 below MIN_OVERRIDES)."""
    examples = load_examples()
    sums = shoot_sums(rows, overrides)
    if sums is None:
        examples.pop(shoot, None)
    else:
        examples[shoot] = {k: (v.tolist() if isinstance(v, np.ndarray) else v)
                           for k, v in sums.items()}
    _save_examples(examples)
    return _model(examples)["overrides"] if _model(examples) else 0


def _model(examples=None):
    examples = load_examples() if examples is None else examples
    if not examples:
        return None
    total = sum(e["overrides"] for e in examples.values())
    if total < MIN_OVERRIDES:
        return None
    a = sum(np.array(e["A"]) for e in examples.values())
    b = sum(np.array(e["b"]) for e in examples.values())
    w = np.linalg.solve(a + ALPHA * np.eye(len(b)), b)
    n = sum(e["n"] for e in examples.values())
    mu = sum(np.array(e["m"]) for e in examples.values()) / n
    cov = sum(np.array(e["C"]) for e in examples.values()) / n - np.outer(mu, mu)
    sd = float(np.sqrt(max(w @ cov @ w, 1e-12)))
    return {"w": w, "center": float(mu @ w), "sd": sd, "overrides": total}


def shift(x):
    """Learned score change per row of aesthetic features, 0 until enough overrides exist."""
    model = _model()
    if model is None:
        return np.zeros(len(x), dtype=np.float32)
    s = (reduce(x) @ model["w"] - model["center"]) / model["sd"]
    return np.clip(SHIFT_SCALE * s, -MAX_SHIFT, MAX_SHIFT).astype(np.float32)
