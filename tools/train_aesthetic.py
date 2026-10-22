"""Train the local aesthetic head on Claude taste scores and report cross-shoot accuracy.

    python tools/train_aesthetic.py shoot2 shoot3 [--save]

Each shoot folder under cull-data needs work/taste.json (labels) plus the local caches
(local, faces, scenes with embeddings). Validation trains on all shoots but one and tests on
the held-out shoot. --save trains on every shoot and writes fixtures/aesthetic_head.npz.
"""
import argparse
import json
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from cull import aesthetic  # noqa: E402

DATA = Path(r"C:\Users\willp\cull-data")
ALPHAS = [0.03, 0.1, 0.3, 1, 3, 10, 30]


def load(shoot):
    work = DATA / shoot / "work"
    caches = [json.loads((work / f).read_text(encoding="utf-8"))
              for f in ("local.json", "faces.json", "scenes.json")]
    taste = json.loads((work / "taste.json").read_text(encoding="utf-8"))
    rows, y = [], []
    for path, t in sorted(taste.items()):
        if t.get("claude_score") is None or any(path not in c for c in caches):
            continue
        row = {"path": path}
        for c in caches:
            row.update(c[path])
        rows.append(row)
        y.append(float(t["claude_score"]))
    return aesthetic.features(rows), np.array(y)


def spearman(a, b):
    ra, rb = np.argsort(np.argsort(a)), np.argsort(np.argsort(b))
    return float(np.corrcoef(ra, rb)[0, 1])


def report(name, pred, y):
    return (f"{name:28} spearman {spearman(pred, y):.3f} | pearson {np.corrcoef(pred, y)[0, 1]:.3f}"
            f" | MAE {np.abs(pred - y).mean():.2f}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("shoots", nargs="+")
    ap.add_argument("--save", action="store_true")
    args = ap.parse_args()
    data = {s: load(s) for s in args.shoots}
    for s, (x, y) in data.items():
        print(f"{s}: {len(y)} labelled frames, mean score {y.mean():.2f}")
    n_emb = next(iter(data.values()))[0].shape[1] - len(aesthetic.EXTRA_FEATURES)
    zs = n_emb + aesthetic.EXTRA_FEATURES.index("zs_aesthetic")
    sh = n_emb + aesthetic.EXTRA_FEATURES.index("log_sharpness")

    best = {}
    for test in args.shoots:
        x_te, y_te = data[test]
        train = [s for s in args.shoots if s != test]
        x_tr = np.vstack([data[s][0] for s in train])
        y_tr = np.concatenate([data[s][1] for s in train])
        print(f"\nTEST {test} (train {', '.join(train)})")
        print("  " + report("baseline: sharpness only", x_te[:, sh], y_te))
        print("  " + report("baseline: zero-shot prompt", x_te[:, zs], y_te))
        extras_only = aesthetic.fit(x_tr[:, n_emb:], y_tr, 1.0)
        extras_only["mean"], extras_only["std"] = extras_only["mean"], extras_only["std"]
        print("  " + report("hand features only", aesthetic.predict(extras_only, x_te[:, n_emb:]), y_te))
        for a in ALPHAS:
            head = aesthetic.fit(x_tr, y_tr, a)
            pred = aesthetic.predict(head, x_te)
            best.setdefault(a, []).append(spearman(pred, y_te))
            print("  " + report(f"full head alpha={a}", pred, y_te))

    alpha = max(best, key=lambda a: np.mean(best[a]))
    print(f"\nbest alpha {alpha} (mean held-out spearman {np.mean(best[alpha]):.3f})")
    if args.save:
        x = np.vstack([d[0] for d in data.values()])
        y = np.concatenate([d[1] for d in data.values()])
        head = aesthetic.fit(x, y, alpha)
        np.savez_compressed(aesthetic.HEAD_PATH, **head, shoots=np.array(args.shoots))
        print(f"saved {aesthetic.HEAD_PATH} (trained on {len(y)} frames)")


if __name__ == "__main__":
    main()
