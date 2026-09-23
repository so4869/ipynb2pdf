# -*- mode: python ; coding: utf-8 -*-
# PyInstaller spec: build with  `pyinstaller ipynb2pdf.spec`
import os
from PyInstaller.utils.hooks import collect_all, collect_submodules, collect_data_files

block_cipher = None
here = os.path.abspath(os.getcwd())

datas = [(os.path.join(here, "resources"), "resources")]
hiddenimports = []
binaries = []
for pkg in ("nbformat", "jsonschema", "jsonschema_specifications", "referencing", "fastjsonschema", "svglib", "reportlab"):
    try:
        d, b, h = collect_all(pkg)
        datas += d; binaries += b; hiddenimports += h
    except Exception:
        pass
hiddenimports += collect_submodules("mistune")
hiddenimports += collect_submodules("pygments.lexers")
hiddenimports += collect_submodules("pygments.styles")
hiddenimports += ["matplotlib.backends.backend_agg", "PIL.ImageFont", "PIL.ImageDraw", "tkinter", "tkinter.filedialog", "tkinter.messagebox"]

a = Analysis(
    ["run.py"],
    pathex=[here],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    runtime_hooks=[],
    excludes=["scipy", "pandas", "IPython", "jupyter_client", "jupyter_core", "notebook", "PyQt5", "PyQt6", "PySide2", "PySide6",
              "wx", "pytest", "sphinx", "numpy.testing", "matplotlib.tests", "pymupdf", "fitz"],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)
pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)
exe = EXE(
    pyz, a.scripts, a.binaries, a.zipfiles, a.datas, [],
    name="ipynb2pdf",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=True,
    disable_windowed_traceback=False,
    icon=None,
)
