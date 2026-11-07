# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller 打包配置：生成单文件 ``dist/labpbr2bedrock.exe``。"""

from pathlib import Path

ROOT = Path(SPECPATH)

a = Analysis(
    [str(ROOT / "exe_entry.py")],
    pathex=[str(ROOT / "src")],
    binaries=[],
    datas=[
        (str(ROOT / "src" / "labpbr2bedrock" / "data"), "labpbr2bedrock/data"),
    ],
    hiddenimports=[],
    hookspath=[],
    runtime_hooks=[],
    excludes=[
        "tkinter",
        "matplotlib",
        "scipy",
        "pandas",
        "pytest",
        "IPython",
    ],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="labpbr2bedrock",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=str(ROOT / "assets" / "icon.ico"),
    version=str(ROOT / "assets" / "version_info.txt"),
)
