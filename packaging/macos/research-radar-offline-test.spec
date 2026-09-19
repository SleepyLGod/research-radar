# -*- mode: python ; coding: utf-8 -*-
"""Test-only frozen engine. Never used by production bundle assembly."""

from pathlib import Path

root = Path(SPECPATH).parents[1]
analysis = Analysis(
    [str(root / "tests/fixtures/offline_frozen/entry.py")],
    pathex=[str(root / "src"), str(root / "tests/fixtures")],
    binaries=[],
    datas=[(str(root / "tests/fixtures/offline_frozen/reader.json"), "offline_frozen")],
    hiddenimports=["cryptography", "keyring.backends.chainer", "keyring.backends.macOS",
                   "keyring.backends.null", "PIL", "pypdf", "yaml"],
    hookspath=[], hooksconfig={}, runtime_hooks=[], excludes=[], noarchive=False, optimize=0,
)
archive = PYZ(analysis.pure)
executable = EXE(
    archive, analysis.scripts, [], exclude_binaries=True,
    name="research-radar-offline-test", debug=False, bootloader_ignore_signals=False,
    strip=False, upx=False, console=True, target_arch="arm64", codesign_identity=None,
    entitlements_file=None,
)
collection = COLLECT(
    executable, analysis.binaries, analysis.datas, strip=False, upx=False,
    name="research-radar-offline-test",
)
engine_app = BUNDLE(
    collection,
    name="ResearchRadarOfflineEngine.app",
    bundle_identifier="ai.research-radar.offline-engine",
    info_plist={"LSUIElement": True},
)
