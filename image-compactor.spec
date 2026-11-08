# -*- mode: python ; coding: utf-8 -*-

import sys
from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files, collect_submodules
from PyInstaller.utils.win32.versioninfo import (
    FixedFileInfo,
    StringFileInfo,
    StringStruct,
    StringTable,
    VarFileInfo,
    VarStruct,
    VSVersionInfo,
)

ROOT = Path.cwd()
PROJECT_ROOT = ROOT.parent
sys.path.insert(0, str(PROJECT_ROOT))

from image_compactor import __version__ as APP_VERSION

_parts = [int(part) for part in APP_VERSION.split(".") if part.isdigit()]
while len(_parts) < 4:
    _parts.append(0)
_major, _minor, _build, _revision = _parts[:4]

_version_info = VSVersionInfo(
    ffi=FixedFileInfo(
        filevers=(_major, _minor, _build, _revision),
        prodvers=(_major, _minor, _build, _revision),
        mask=0x3F,
        flags=0x0,
        OS=0x40004,
        fileType=0x1,
        subtype=0x0,
        date=(0, 0),
    ),
    kids=[
        StringFileInfo(
            [
                StringTable(
                    "040904B0",
                    [
                        StringStruct("CompanyName", "Image Compactor"),
                        StringStruct("FileDescription", "Image Compactor"),
                        StringStruct("FileVersion", APP_VERSION),
                        StringStruct("InternalName", "image-compactor"),
                        StringStruct("OriginalFilename", "image-compactor.exe"),
                        StringStruct("ProductName", "Image Compactor"),
                        StringStruct("ProductVersion", APP_VERSION),
                    ],
                )
            ]
        ),
        VarFileInfo([VarStruct("Translation", [0x0409, 1200])]),
    ],
)

_encoder_dir = ROOT / "build" / "encoder"
if not (_encoder_dir / "avifenc.exe").is_file():
    raise SystemExit(
        "Bundled avifenc missing. Run build.ps1 without -SkipEncoderBuild first."
    )

_datas = [
    (str(_encoder_dir), "avifenc"),
    *collect_data_files("tkinterdnd2"),
]
_hiddenimports = [
    *collect_submodules(
        "image_compactor",
        filter=lambda name: not name.startswith("image_compactor.tests"),
    ),
    *collect_submodules("tkinterdnd2"),
    "tkinterdnd2",
    "tkinterdnd2.TkinterDnD",
]

a = Analysis(
    ["main.py"],
    pathex=[str(PROJECT_ROOT)],
    binaries=[],
    datas=_datas,
    hiddenimports=_hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="image-compactor",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    version=_version_info,
)
