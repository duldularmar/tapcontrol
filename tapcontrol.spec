# -*- mode: python ; coding: utf-8 -*-
# PyInstaller spec: build a standalone TapControl.exe
#   pyinstaller tapcontrol.spec
import sys
from PyInstaller.utils.hooks import collect_submodules

hiddenimports = collect_submodules("tapcontrol") + [
    "sounddevice", "soundfile", "numpy", "scipy.signal",
    "PySide6.QtWidgets", "PySide6.QtGui", "PySide6.QtCore",
]

a = Analysis(
    ["main.py"],
    pathex=[],
    binaries=[],
    datas=[],
    hiddenimports=hiddenimports,
    hookspath=[],
    runtime_hooks=[],
    excludes=["tkinter", "matplotlib"],
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="TapControl",
    debug=False,
    strip=False,
    upx=False,
    console=False,          # windowed app: no console flash
    icon=None,
)
