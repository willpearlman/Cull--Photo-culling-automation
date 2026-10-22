"""Benchmark the local scenes cache against rekog scene_tags (benchmark labels, not truth).

    python tools/bench_scenes.py

Per tag: precision, recall, F1 at the shipped threshold, and the best-F1 threshold found by a
sweep (tuned on this one shoot, so treat it as an upper bound). candid is compared with the
taste cache, where Claude labelled candid on the frames it scored.
"""
import json
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from cull import config, scenes  # noqa: E402


def _load(name):
    return json.loads((config.WORK_DIR / name).read_text(encoding="utf-8"))


def _prf(pred, gold):
    tp = int(np.sum(pred & gold)); fp = int(np.sum(pred & ~gold)); fn = int(np.sum(~pred & gold))
    p = tp / (tp + fp) if tp + fp else 0.0
    r = tp / (tp + fn) if tp + fn else 0.0
    return p, r, (2 * p * r / (p + r) if p + r else 0.0), tp, fp, fn


def _line(name, n_gold, s, gold, th):
    p, r, f, tp, fp, fn = _prf(s > th, gold)
    best = max(((_prf(s > t, gold)[2], t) for t in np.linspace(s.min(), s.max(), 200)), default=(0, 0))
    print(f"  {name:12} gold {n_gold:4} | P {p:.2f} R {r:.2f} F1 {f:.2f} (tp {tp} fp {fp} fn {fn})"
          f" | best F1 {best[0]:.2f} at {best[1]:+.4f}")


def main():
    rek, loc, faces, sharp = (_load(n) for n in ("rekog.json", "scenes.json", "faces.json", "local.json"))
    paths = sorted(p for p in rek if p in loc
                   and (sharp.get(p, {}).get("sharpness") or 0) >= config.MIN_SHARPNESS)
    print(f"frames compared: {len(paths)}")

    print("\nFULL TAGS (local faces + local scores vs rekog)")
    for tag in ("group", "couple", "portrait", "dance floor", "food", "detail", "indoor", "outdoor"):
        pred = np.array([tag in loc[p]["scene_tags"] for p in paths])
        gold = np.array([tag in rek[p]["scene_tags"] for p in paths])
        p, r, f, tp, fp, fn = _prf(pred, gold)
        print(f"  {tag:12} gold {gold.sum():4} local {pred.sum():4} | P {p:.2f} R {r:.2f} F1 {f:.2f}")

    print("\nRAW SCORE PER TAG (shipped threshold, then best sweep threshold)")
    for tag, gold_tag in (("indoor", "indoor"), ("outdoor", "outdoor"), ("dance floor", "dance floor"),
                          ("food", "food"), ("detail", "detail")):
        s = np.array([loc[p]["scene_scores"][tag] for p in paths])
        gold = np.array([gold_tag in rek[p]["scene_tags"] for p in paths])
        _line(tag, int(gold.sum()), s, gold, scenes.THRESHOLDS[tag])

    if not (config.WORK_DIR / "taste.json").exists():
        return
    taste = _load("taste.json")
    tp_ =[p for p in paths if p in taste and "error" not in taste[p]]
    s = np.array([loc[p]["scene_scores"]["candid"] for p in tp_])
    gold = np.array([taste[p].get("candid") is True for p in tp_])
    print(f"\nCANDID vs Claude taste labels ({len(tp_)} scored frames)")
    _line("candid", int(gold.sum()), s, gold, 0.0)


if __name__ == "__main__":
    main()
