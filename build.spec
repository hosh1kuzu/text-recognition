# PyInstaller spec for TextRecog. Use `pyinstaller build.spec` (NOT --onefile).
#
# PaddlePaddle ships ~200 MB of native DLLs (mklml, libiomp5, mkldnn, ...) that
# PyInstaller's --onefile mode unpacks to %TEMP% on every cold start, taking
# 5-15 seconds. --onedir avoids that and gets bundling right by default.
#
# This spec collects PaddleOCR / PaddlePaddle data files and binaries
# explicitly. After building, smoke-test on a clean Windows VM (no Python
# installed) to catch missing VC++ runtime DLLs.

# -*- mode: python ; coding: utf-8 -*-

import glob
import importlib.util
import os
import sys

from PyInstaller.utils.hooks import (
    collect_data_files,
    collect_dynamic_libs,
    collect_submodules,
    copy_metadata,
)

block_cipher = None

datas = []
binaries = []
hiddenimports = []

_paddleocr_spec = importlib.util.find_spec("paddleocr")
if _paddleocr_spec is None or not _paddleocr_spec.submodule_search_locations:
    raise RuntimeError("paddleocr package not found")
_paddleocr_dir = next(iter(_paddleocr_spec.submodule_search_locations))
if _paddleocr_dir not in sys.path:
    sys.path.append(_paddleocr_dir)
_paddleocr_e2e_utils_dir = os.path.join(_paddleocr_dir, "ppocr", "utils", "e2e_utils")

# Conda stashes libffi (a runtime dep of _ctypes) and other CRT-adjacent DLLs
# in <env>\Library\bin instead of DLLs\, and PyInstaller's binary scanner does
# not search there. Without ffi-*.dll the built exe dies on `import ctypes`.
_conda_bin = os.path.join(sys.prefix, "Library", "bin")
if os.path.isdir(_conda_bin):
    for pattern in ("ffi-*.dll", "libffi-*.dll"):
        for dll in glob.glob(os.path.join(_conda_bin, pattern)):
            binaries.append((dll, "."))

# PaddleOCR uses dict files and config YAMLs from package data, AND walks its
# own source tree via __file__ at init time (e.g. paddleocr/tools/__init__.py).
# include_py_files=True drops the .py sources to disk alongside the PYZ archive
# so those filesystem lookups succeed.
datas += collect_data_files(
    "paddleocr",
    include_py_files=True,
    excludes=[
        "**/ppstructure/**",
        "**/tools/train.py",
        "**/tools/eval.py",
        "**/tools/infer_table.py",
        "**/tools/infer_kie.py",
        "**/tools/infer_kie_token_ser.py",
        "**/tools/infer_kie_token_ser_re.py",
        "**/tools/infer_sr.py",
        "**/tools/test_hubserving.py",
    ],
)
datas += copy_metadata("paddleocr")

# PaddlePaddle itself ships native DLLs and config files.
datas += collect_data_files("paddle", include_py_files=True)
binaries += collect_dynamic_libs("paddle")

# Cython ships .cpp / .pyx prelude files under Cython/Utility/ that some
# PaddleOCR deps (scikit-image / pyclipper) read at runtime for inline compile.
# Without these, OCR init fails with a bare path to CppSupport.cpp.
datas += collect_data_files(
    "Cython",
    include_py_files=True,
    excludes=["**/Tests/**", "**/tests/**"],
)

# Common hidden imports for the OCR-only Paddle stack. Do not collect the
# top-level paddleocr package: importing it pulls in PP-Structure, docx export,
# table recovery, and other modules unused by TextRecog.
hiddenimports += collect_submodules("ppocr")
hiddenimports += [
    "cv2",
    "paddle",
    "tools.infer.predict_cls",
    "tools.infer.predict_det",
    "tools.infer.predict_rec",
    "tools.infer.predict_system",
    "tools.infer.utility",
    "extract_textpoint_fast",
    "extract_textpoint_slow",
    "skimage.io._plugins.matplotlib_plugin",
    "skimage.io._plugins.pil_plugin",
    "imghdr",
]

a = Analysis(
    ["main.py"],
    pathex=["src", _paddleocr_dir, _paddleocr_e2e_utils_dir],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        "tkinter",
        "matplotlib",
        "PyQt5",
        "PyQt6",
        "PySide2",
    ],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)
pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="TextRecog",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="TextRecog",
)
