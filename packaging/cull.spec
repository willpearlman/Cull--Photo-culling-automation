# PyInstaller spec for the Windows app. Build with packaging\build.ps1 (it runs this).
#
# One folder (dist\Cull\Cull.exe + _internal), no console window. Bundles the UI, fixtures, the
# three models the app runs, and exiftool. Never bundles .env (it holds the developer's API key)
# or the development-only models (SigLIP text model and tokenizer, used by --build-vocab).
import os
from pathlib import Path

from PyInstaller.utils.hooks import collect_all, collect_submodules

REPO = Path(SPECPATH).parent
EXIFTOOL_DIR = Path(os.environ.get("EXIFTOOL_DIR",
                                   r"C:\Users\willp\AppData\Local\Programs\ExifTool"))
RUNTIME_MODELS = ["face_detection_yunet_2023mar.onnx", "face_landmarker.task",
                  "siglip_vision_quantized.onnx"]

datas = [(str(REPO / "static"), "static"), (str(REPO / "fixtures"), "fixtures")]
datas += [(str(REPO / "models" / m), "models") for m in RUNTIME_MODELS]
datas += [(str(EXIFTOOL_DIR / "exiftool_files"), "exiftool/exiftool_files"),
          (str(EXIFTOOL_DIR / "ExifTool.exe"), "exiftool")]
binaries, hiddenimports = [], []
for pkg in ("mediapipe", "onnxruntime", "webview"):
    d, b, h = collect_all(pkg)
    datas, binaries, hiddenimports = datas + d, binaries + b, hiddenimports + h
hiddenimports += collect_submodules("uvicorn") + collect_submodules("cull")

a = Analysis(
    [str(REPO / "packaging" / "cull_app.py")],
    pathex=[str(REPO)],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    excludes=["tkinter", "pytest", "tokenizers", "IPython", "jupyter"],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name="Cull", console=False,
          upx=False, icon=None)
coll = COLLECT(exe, a.binaries, a.datas, name="Cull", upx=False)
