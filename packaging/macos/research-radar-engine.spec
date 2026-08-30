# -*- mode: python ; coding: utf-8 -*-

from pathlib import Path

project_root = Path(SPECPATH).parents[1]
hidden_imports = [
    "cryptography",
    "keyring.backends.chainer",
    "keyring.backends.macOS",
    "keyring.backends.null",
    "PIL",
    "pypdf",
    "yaml",
]

analysis = Analysis(
    [str(project_root / "packaging/macos/engine_entry.py")],
    pathex=[str(project_root / "src")],
    binaries=[],
    datas=[],
    hiddenimports=hidden_imports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=1,
)
python_archive = PYZ(analysis.pure)
executable = EXE(
    python_archive,
    analysis.scripts,
    [],
    exclude_binaries=True,
    name="research-radar-engine",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=True,
    target_arch="arm64",
    codesign_identity=None,
    entitlements_file=None,
)
collection = COLLECT(
    executable,
    analysis.binaries,
    analysis.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="research-radar-engine",
)
engine_app = BUNDLE(
    collection,
    name="ResearchRadarEngine.app",
    bundle_identifier="com.researchradar.engine",
    info_plist={"LSUIElement": True},
)
