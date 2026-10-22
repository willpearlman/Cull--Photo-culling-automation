"""Build fixtures/taste_basis.npz: the fixed feature reduction personal taste learns in.

    python tools/build_taste_basis.py shoot2 shoot3 demo

Unsupervised: uses only image vectors and hand features (no ratings, no picks). PCA of the
SigLIP vectors to K components, then the mean and spread of the reduced features so they can
be standardized the same way on every machine.
"""
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from cull import aesthetic, personal  # noqa: E402

DATA = Path(r"C:\Users\willp\cull-data")


def main(shoots):
    x = np.vstack([aesthetic.features(personal.shoot_rows(DATA / s / "work")) for s in shoots])
    n_emb = x.shape[1] - len(aesthetic.EXTRA_FEATURES)
    emb = x[:, :n_emb]
    emb_mean = emb.mean(0)
    _, sv, vt = np.linalg.svd(emb - emb_mean, full_matrices=False)
    comps = vt[:personal.K]
    z = np.hstack([(emb - emb_mean) @ comps.T, x[:, n_emb:]])
    np.savez_compressed(personal.BASIS_PATH, emb_mean=emb_mean.astype(np.float32),
                        components=comps.astype(np.float32), feat_mean=z.mean(0).astype(np.float32),
                        feat_std=(z.std(0) + 1e-6).astype(np.float32), shoots=np.array(shoots))
    explained = (sv[:personal.K] ** 2).sum() / (sv ** 2).sum()
    print(f"{len(x)} frames from {', '.join(shoots)}: {personal.K} components explain "
          f"{explained:.0%} of image-vector variance -> {personal.BASIS_PATH}")


if __name__ == "__main__":
    main(sys.argv[1:] or ["shoot2", "shoot3", "demo"])
