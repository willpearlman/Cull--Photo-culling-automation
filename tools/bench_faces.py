"""Benchmark the local faces cache against the Rekognition cache (benchmark labels, not truth).

    python tools/bench_faces.py [--sweep]

Compares work/faces.json with work/rekog.json on frames above MIN_SHARPNESS (rekog
skipped blurry frames). --sweep re-thresholds blink and smile from the raw per-face scores.
"""
import argparse
import json
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from cull import config, faces  # noqa: E402


def _load(name):
    return json.loads((config.WORK_DIR / name).read_text(encoding="utf-8"))


def _bucket(n):
    return str(n) if n < 4 else "4+"


def _prf(pairs):
    """Precision, recall, F1 for (local_flag, rekog_flag) pairs."""
    tp = sum(a and b for a, b in pairs)
    fp = sum(a and not b for a, b in pairs)
    fn = sum(b and not a for a, b in pairs)
    p = tp / (tp + fp) if tp + fp else 0.0
    r = tp / (tp + fn) if tp + fn else 0.0
    f = 2 * p * r / (p + r) if p + r else 0.0
    return tp, fp, fn, p, r, f


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sweep", action="store_true")
    args = ap.parse_args()

    rek, loc, sharp = _load("rekog.json"), _load("faces.json"), _load("local.json")
    paths = sorted(p for p in rek if p in loc
                   and (sharp.get(p, {}).get("sharpness") or 0) >= config.MIN_SHARPNESS)
    print(f"frames compared: {len(paths)} (sharp, in both caches)")
    print(f"local errors: {sum('error' in loc[p] for p in paths)}")
    unread = sum(f['blink'] is None for p in paths for f in loc[p]['faces'])
    total = sum(len(loc[p]['faces']) for p in paths)
    print(f"faces the landmarker could not read: {unread} of {total}")

    rc = [rek[p]["face_count"] for p in paths]
    lc = [loc[p]["face_count"] for p in paths]
    diff = [a - b for a, b in zip(lc, rc)]
    n = len(paths)
    print("\nFACE COUNT (local vs rekog)")
    print(f"  exact {sum(d == 0 for d in diff) / n:.1%} | within 1 {sum(abs(d) <= 1 for d in diff) / n:.1%}"
          f" | mean abs diff {sum(map(abs, diff)) / n:.2f} | local higher {sum(d > 0 for d in diff)}"
          f" | local lower {sum(d < 0 for d in diff)}")
    conf = Counter((_bucket(r), _bucket(l)) for r, l in zip(rc, lc))
    keys = ["0", "1", "2", "3", "4+"]
    print("  rows = rekog, cols = local")
    print("        " + "".join(f"{k:>6}" for k in keys))
    for r in keys:
        print(f"  {r:>4}  " + "".join(f"{conf[(r, c)]:>6}" for c in keys))

    def report(bt, st, label):
        s = {p: faces.summarize(loc[p]["faces"], bt, st) for p in paths}
        rows = []
        for field in ("eyes_closed_count", "smile_count"):
            tp, fp, fn, pr, rc_, f = _prf([(s[p][field] > 0, rek[p][field] > 0) for p in paths])
            rows.append(f"{field.split('_')[0]:>6}: P {pr:.2f} R {rc_:.2f} F1 {f:.2f}"
                        f" (tp {tp} fp {fp} fn {fn})")
        print(f"  {label}  " + " | ".join(rows))

    print("\nFRAME HAS ANY CLOSED EYES / ANY SMILE (rekog positives: "
          f"{sum(rek[p]['eyes_closed_count'] > 0 for p in paths)} blink, "
          f"{sum(rek[p]['smile_count'] > 0 for p in paths)} smile)")
    report(faces.BLINK_THRESHOLD, faces.SMILE_THRESHOLD,
           f"blink>{faces.BLINK_THRESHOLD} smile>{faces.SMILE_THRESHOLD}")
    if args.sweep:
        for t in (0.3, 0.4, 0.5, 0.6, 0.7, 0.8):
            report(t, t, f"both>{t}          ")


if __name__ == "__main__":
    main()
