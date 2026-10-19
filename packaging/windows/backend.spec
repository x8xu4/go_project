# -*- mode: python ; coding: utf-8 -*-
"""Native Windows x64 onedir build for the LogosGo backend.

Run only with Windows Python/PyInstaller. Immutable model, config, corpus, and
KataGo runtimes are staged separately by the Windows application pipeline.
"""

from pathlib import Path


PROJECT_ROOT = Path(SPECPATH).resolve().parents[1]

PROJECT_MODULES = [
    "analysis_logic",
    "backend_startup",
    "directional_explanation",
    "explanation_classifier",
    "explanation_features",
    "logos_engine",
    "review_selection",
    "review_summary",
    "runtime_paths",
    "runtime_processes",
    "sgf_utils",
    "structured_explanation",
]

analysis = Analysis(
    [str(PROJECT_ROOT / "server.py")],
    pathex=[str(PROJECT_ROOT)],
    binaries=[],
    datas=[],
    hiddenimports=PROJECT_MODULES,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        "flask_cors",
        "matplotlib",
        "PIL",
        "pytest",
        "tkinter",
    ],
    noarchive=False,
    optimize=0,
)

pyz = PYZ(analysis.pure)

executable = EXE(
    pyz,
    analysis.scripts,
    [],
    exclude_binaries=True,
    name="logosgo_backend",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=True,
)

bundle = COLLECT(
    executable,
    analysis.binaries,
    analysis.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="logosgo_backend",
)
