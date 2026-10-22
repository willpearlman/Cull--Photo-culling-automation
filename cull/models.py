"""Model files for the local stages: one registry, downloaded once, checked against pinned hashes.

Every entry names its license. Only add a model whose weights allow commercial use.
"""
from __future__ import annotations

import hashlib
import logging
import threading
import urllib.request

from cull import config

log = logging.getLogger(__name__)

MODEL_DIR = config.REPO_ROOT / "models"
_SIGLIP = ("https://huggingface.co/Xenova/siglip-base-patch16-224/resolve/"
           "4649052661e53c7000355844105f8a1792088239/")

# name -> (filename, official URL, sha256). License in the comment above each entry.
MODELS = {
    # YuNet face detector, OpenCV Zoo. MIT.
    "yunet": ("face_detection_yunet_2023mar.onnx",
              "https://github.com/opencv/opencv_zoo/raw/main/models/face_detection_yunet/"
              "face_detection_yunet_2023mar.onnx",
              "8f2383e4dd3cfbb4553ea8718107fc0423210dc964f9f4280604804ed2552fa4"),
    # MediaPipe Face Landmarker (BlazeFace, Face Mesh V2, Blendshape V2). Apache 2.0.
    "landmarker": ("face_landmarker.task",
                   "https://storage.googleapis.com/mediapipe-models/face_landmarker/"
                   "face_landmarker/float16/latest/face_landmarker.task",
                   "64184e229b263107bc2b804c6625db1341ff2bb731874b0bcc2fe6544e0bc9ff"),
    # Google SigLIP base patch16-224, ONNX conversion by Xenova. Apache 2.0.
    # Only the vision model runs in the app. Text model + tokenizer build tag vectors in dev.
    "siglip_vision": ("siglip_vision_quantized.onnx", _SIGLIP + "onnx/vision_model_quantized.onnx",
                      "ef14a954f3d57e1806666432bd9785004c1dc27100aa260eee0cb0f10a5de058"),
    "siglip_text": ("siglip_text_quantized.onnx", _SIGLIP + "onnx/text_model_quantized.onnx",
                    "ad0329b1f35acc66d8953ff2559ce358da8eb0a7011794cf951523d63a4dbce2"),
    "siglip_tokenizer": ("siglip_tokenizer.json", _SIGLIP + "tokenizer.json",
                         "4a17c975210be5ab4c36b47d8dae4eefb866dbfb1e676e394aad85dc30a3ae08"),
}

_lock = threading.Lock()


def path(name):
    """Local path of a model file, downloaded on first use. A hash mismatch is rejected."""
    filename, url, sha256 = MODELS[name]
    dst = MODEL_DIR / filename
    with _lock:
        if not dst.exists():
            MODEL_DIR.mkdir(parents=True, exist_ok=True)
            tmp = dst.with_suffix(dst.suffix + ".part")
            log.info("downloading %s", url)
            urllib.request.urlretrieve(url, tmp)
            got = hashlib.sha256(tmp.read_bytes()).hexdigest()
            if sha256 is None:
                log.warning("%s has no pinned sha256 yet: %s", filename, got)
            elif got != sha256:
                tmp.unlink()
                raise RuntimeError(f"{filename}: sha256 {got} does not match the pinned model")
            tmp.replace(dst)
    return dst
