"""Local scene tags stage. Offline replacement for rekog's scene_tags.

SigLIP (Google, Apache 2.0) embeds each preview. Each tag in fixtures/vocab.json has yes and
no prompts, and its score is mean similarity to the yes prompts minus mean similarity to the
no prompts. Prompt vectors are built once in development (--build-vocab) and shipped in
fixtures/vocab_embeddings.npz, so the app runs only the vision model.

Face-based tags keep rekog's rule on the faces stage's face_count: 1 face portrait,
2 faces couple, 4+ faces (or a crowd) group, no faces plus a detail score detail.

Returns scene_tags plus `scene_scores`, the raw score per tag, so thresholds can be
re-tuned from the cache, and `embedding`, the image vector (float16, base64) that the
aesthetic stage reuses.

CLI: python -m cull.scenes --build-vocab
"""
from __future__ import annotations

import argparse
import base64
import json
import logging
from concurrent.futures import ThreadPoolExecutor

import numpy as np
from PIL import Image

from cull import config, models

log = logging.getLogger(__name__)

VOCAB_PATH = config.REPO_ROOT / "fixtures" / "vocab.json"
EMBED_PATH = config.REPO_ROOT / "fixtures" / "vocab_embeddings.npz"
SIZE = 224
MAX_TOKENS = 64  # SigLIP is trained on prompts padded to 64 tokens
PAD_ID = 1
BATCH = 16
# Score above which a tag applies. Checked on shoot2 (conference) and demo (travel) with
# tools/bench_scenes.py. Neither shoot has real details, food or dancing, so those cutoffs
# only prove they stay quiet on scenes without them.
THRESHOLDS = {"indoor": 0.0, "outdoor": 0.0, "dance floor": 0.0, "food": 0.0, "detail": 0.01,
              "crowd": 0.0}
GENRE_THRESHOLD = 0.0

_session = None


def vocab(genre=None):
    """{tag: {"yes": [...], "no": [...]}} for the base tags, scored-only tags, and a genre."""
    data = json.loads(VOCAB_PATH.read_text(encoding="utf-8"))
    out = {**data["base"], **data["scored_only"]}
    if genre:
        out.update(data[genre])
    return out


def _all_prompts():
    data = json.loads(VOCAB_PATH.read_text(encoding="utf-8"))
    return sorted({p for k, group in data.items() if not k.startswith("_")
                   for tag in group.values() for p in tag["yes"] + tag["no"]})


def build_vocab():
    """Embed every prompt in vocab.json with the SigLIP text model. Development only."""
    import onnxruntime as ort
    from tokenizers import Tokenizer
    tok = Tokenizer.from_file(str(models.path("siglip_tokenizer")))
    sess = ort.InferenceSession(str(models.path("siglip_text")), providers=["CPUExecutionProvider"])
    prompts = _all_prompts()
    ids = np.full((len(prompts), MAX_TOKENS), PAD_ID, dtype=np.int64)
    for i, p in enumerate(prompts):
        enc = tok.encode(p.lower()).ids[:MAX_TOKENS]
        ids[i, :len(enc)] = enc
    emb = sess.run(["pooler_output"], {"input_ids": ids})[0]
    emb /= np.linalg.norm(emb, axis=1, keepdims=True)
    np.savez_compressed(EMBED_PATH, prompts=np.array(prompts), embeddings=emb.astype(np.float32))
    print(f"vocab: {len(prompts)} prompts -> {EMBED_PATH}")


def _prompt_vectors():
    data = np.load(EMBED_PATH)
    return dict(zip(data["prompts"].tolist(), data["embeddings"]))


def _vision():
    global _session
    if _session is None:
        import onnxruntime as ort
        _session = ort.InferenceSession(str(models.path("siglip_vision")),
                                        providers=["CPUExecutionProvider"])
    return _session


def _pixels(preview_path):
    """SigLIP preprocessing: bicubic resize to 224x224 (no crop), scale to [-1, 1], CHW."""
    with Image.open(preview_path) as im:
        im = im.convert("RGB").resize((SIZE, SIZE), Image.BICUBIC)
    arr = np.asarray(im, dtype=np.float32) / 127.5 - 1.0
    return arr.transpose(2, 0, 1)


def embed(preview_paths):
    """Unit image vectors, one row per preview."""
    with ThreadPoolExecutor(max_workers=config.MAX_WORKERS) as pool:
        pixels = list(pool.map(_pixels, preview_paths))
    out = []
    for i in range(0, len(pixels), BATCH):
        emb = _vision().run(["pooler_output"], {"pixel_values": np.stack(pixels[i:i + BATCH])})[0]
        out.append(emb / np.linalg.norm(emb, axis=1, keepdims=True))
    return np.concatenate(out) if out else np.zeros((0, 768), np.float32)


def scores(image_vecs, tags):
    """{tag: score per image}: mean cos to yes prompts minus mean cos to no prompts."""
    vecs = _prompt_vectors()
    missing = [p for t in tags.values() for p in t["yes"] + t["no"] if p not in vecs]
    if missing:
        raise RuntimeError(f"prompts not embedded, run --build-vocab: {missing[:3]}")
    out = {}
    for tag, t in tags.items():
        yes = np.mean([image_vecs @ vecs[p] for p in t["yes"]], axis=0)
        no = np.mean([image_vecs @ vecs[p] for p in t["no"]], axis=0)
        out[tag] = yes - no
    return out


def pack(vec):
    """Image vector -> compact cache string (float16, base64)."""
    return base64.b64encode(np.asarray(vec, dtype=np.float16).tobytes()).decode("ascii")


def unpack(text):
    """Cache string -> float32 unit vector."""
    return np.frombuffer(base64.b64decode(text), dtype=np.float16).astype(np.float32)


def tags_for(face_count, s, genre_tags=(), thresholds=None, genre_threshold=GENRE_THRESHOLD):
    """scene_tags from face_count and one image's {tag: score}, in rekog's tag order."""
    th = {**THRESHOLDS, **(thresholds or {})}
    on = {t for t in th if s.get(t, -1) > th[t]}
    tags = []
    if face_count >= 4 or "crowd" in on:
        tags.append("group")
    if face_count == 2:
        tags.append("couple")
    if face_count == 1:
        tags.append("portrait")
    tags += [t for t in ("dance floor", "food") if t in on]
    if face_count == 0 and "detail" in on:
        tags.append("detail")
    tags += [t for t in ("indoor", "outdoor") if t in on]
    tags += [t for t in genre_tags if s.get(t, -1) > genre_threshold]
    return tags


def run(images, cached, genre=None):
    todo = [im for im in images if im["path"] not in cached and im.get("preview")]
    if not todo:
        return {}
    tags = vocab(genre)
    genre_tags = list(vocab(genre).keys() - vocab().keys()) if genre else []
    vecs = embed([config.CULL_ROOT / im["preview"] for im in todo])
    s = scores(vecs, tags)
    out = {}
    for i, im in enumerate(todo):
        row = {t: round(float(v[i]), 4) for t, v in s.items()}
        out[im["path"]] = {"scene_tags": tags_for(im.get("face_count") or 0, row, genre_tags),
                           "scene_scores": row, "embedding": pack(vecs[i])}
    log.info("scenes: %d images", len(out))
    return out


if __name__ == "__main__":
    ap = argparse.ArgumentParser(prog="cull.scenes")
    ap.add_argument("--build-vocab", action="store_true")
    if ap.parse_args().build_vocab:
        build_vocab()
