"""Does learning from overrides improve scores on frames it has not seen?

    python tools/eval_personal.py

Leave-one-moment-out on shoot2 (the only shoot with Will's real picks, truth.json). For each
moment holding five-stars: simulate a cull of the other moments (Cull picks 26, the
photographer force-picks the five-stars Cull missed and force-rejects Cull's picks they did
not want), learn from those overrides only, then measure on the held-out moment how often a
five-star outscores another frame (AUC), before and after the learned shift. Then applies
everything learned on shoot2 to shoot3 to show how much a different shoot moves.
"""
import json
import os
import sys
import tempfile
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ["CULL_SETTINGS"] = str(Path(tempfile.mkdtemp()) / "settings.json")  # never the real one
from cull import aesthetic, personal, solver  # noqa: E402

DATA = Path(r"C:\Users\willp\cull-data")
PLAN = {"target": 26, "rules": [
    {"type": "filter", "max_eyes_closed": 0, "allow_intentional": True, "min_sharpness": 170,
     "drop_exposure_flags": True},
    {"type": "dedupe_bursts", "keep": 1},
    {"type": "coverage", "by": "group_id", "min_per_group": 1},
    {"type": "cap", "by": "group_id", "max_per_group": 3}]}


def load(shoot):
    work = DATA / shoot / "work"
    rows = {r["path"]: r for r in personal.shoot_rows(work)}
    moments = json.loads((work / "moments.json").read_text(encoding="utf-8"))
    for p, r in rows.items():
        r.update(moments.get(p) or {})
    rows = [rows[p] for p in sorted(rows)]
    x = aesthetic.features(rows)
    base = np.clip(aesthetic.predict(aesthetic._load_head(), x), 1, 10)
    images = [{**r, "claude_score": float(b),
               "eyes_closed_count": sum((f["blink"] or 0) > 0.5 for f in r.get("faces") or [])}
              for r, b in zip(rows, base)]
    return images, x, base


def auc(scores, positive):
    pos, neg = scores[positive], scores[~positive]
    if not len(pos) or not len(neg):
        return None
    return float((pos[:, None] > neg[None, :]).mean() + 0.5 * (pos[:, None] == neg[None, :]).mean())


def main():
    images, x, base = load("shoot2")
    truth = set(json.loads((DATA / "shoot2" / "truth.json").read_text(encoding="utf-8")))
    stem = np.array([Path(i["path"]).stem for i in images])
    is_truth = np.isin(stem, list(truth))
    groups = np.array([i["group_id"] for i in images])
    picks = set(solver.run_plan(images, PLAN)["picks"])
    test_moments = sorted(set(groups[is_truth]))
    print(f"shoot2: {len(images)} frames, {is_truth.sum()} five-stars in {len(test_moments)} moments")

    for alpha in (1, 10, 100):
        personal.ALPHA = alpha
        before, after, pairs, n_overrides = [], [], 0, []
        for g in test_moments:
            train = groups != g
            # The photographer's final selection in the training moments: every frame they kept
            # (their five-stars) and every Cull pick they rejected.
            overrides = {}
            for i, img in enumerate(images):
                if not train[i]:
                    continue
                if is_truth[i]:
                    overrides[img["path"]] = 5
                elif img["path"] in picks:
                    overrides[img["path"]] = 1
            n_overrides.append(personal.record("shoot2", images, overrides))
            held = ~train
            shifted = np.clip(base + personal.shift(x), 1, 10)
            a0, a1 = auc(base[held], is_truth[held]), auc(shifted[held], is_truth[held])
            if a0 is None:
                continue
            w = is_truth[held].sum() * (~is_truth[held]).sum()
            before.append(a0 * w)
            after.append(a1 * w)
            pairs += w
        print(f"alpha {alpha:>3}: held-out AUC {sum(before) / pairs:.3f} -> {sum(after) / pairs:.3f}"
              f" | overrides per fold {min(n_overrides)}-{max(n_overrides)}")

    personal.ALPHA = 10
    overrides ={img["path"]: 5 for img, t in zip(images, is_truth) if t and img["path"] not in picks}
    overrides.update({p: 1 for p in picks if Path(p).stem not in truth})
    n = personal.record("shoot2", images, overrides)
    images3, x3, base3 = load("shoot3")
    s = personal.shift(x3)
    shifted3 = np.clip(base3 + s, 1, 10)
    p0 = set(solver.run_plan(images3, {**PLAN, "target": 40})["picks"])
    for img, v in zip(images3, shifted3):
        img["claude_score"] = float(v)
    p1 = set(solver.run_plan(images3, {**PLAN, "target": 40})["picks"])
    rho = np.corrcoef(np.argsort(np.argsort(base3)), np.argsort(np.argsort(shifted3)))[0, 1]
    print(f"\nshoot3 after learning from all {n} shoot2 overrides (alpha {personal.ALPHA:g}):")
    print(f"  shift: mean |shift| {np.abs(s).mean():.2f} pts, max {np.abs(s).max():.2f},"
          f" {np.mean(np.abs(s) >= personal.MAX_SHIFT - 1e-6):.0%} at the cap")
    print(f"  rank correlation base vs shifted {rho:.3f} | Cull's 40 picks changed: {len(p0 - p1)}")


if __name__ == "__main__":
    main()
