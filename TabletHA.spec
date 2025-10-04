# -*- mode: python ; coding: utf-8 -*-
"""
PyInstaller spec file for Tablet-HA Application
This creates a standalone executable with all dependencies bundled
"""

import sys
import os
from pathlib import Path
from PyInstaller.utils.hooks import collect_data_files, collect_dynamic_libs

block_cipher = None

# Get the path to the virtual environment's Python DLL
venv_path = Path('.venv')
if venv_path.exists():
    python_dll_path = venv_path / 'Scripts'
else:
    python_dll_path = Path(sys.executable).parent

# Additional data files to include
added_files = [
    ('config.json', '.'),
    ('README.md', '.'),
    ('QUICKSTART.md', '.'),
    ('DETECTION_MODES.md', '.'),
    ('CONFIGURE.md', '.'),
    ('UPDATE_SYSTEM.md', '.'),
]

# Collect MediaPipe data files
added_files += collect_data_files('mediapipe')

# Additional binaries (DLLs)
added_binaries = []

# Collect any additional DLLs from the virtual environment
if venv_path.exists():
    dll_dirs = [
        venv_path / 'Scripts',
        venv_path / 'Lib' / 'site-packages' / 'PyQt6' / 'Qt6' / 'bin',
    ]
    for dll_dir in dll_dirs:
        if dll_dir.exists():
            for dll_file in dll_dir.glob('*.dll'):
                added_binaries.append((str(dll_file), '.'))

# Hidden imports that PyInstaller might miss
hidden_imports = [
    'PyQt6.QtCore',
    'PyQt6.QtGui',
    'PyQt6.QtWidgets',
    'PyQt6.QtWebEngineWidgets',
    'PyQt6.QtWebEngineCore',
    'PyQt6.sip',
    'cv2',
    'mediapipe',
    'paho.mqtt.client',
    'screen_brightness_control',
    'PIL',
    'PIL._tkinter_finder',
    'numpy',
    'numpy.core._multiarray_umath',
    'requests',
    'urllib3',
    'certifi',
    'charset_normalizer',
    'idna',
    'packaging',
    'packaging.version',
]

a = Analysis(
    ['main.py'],
    pathex=[],
    binaries=added_binaries,
    datas=added_files,
    hiddenimports=hidden_imports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        'tkinter',
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
    name='TabletHA',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,  # Disable UPX compression to avoid DLL issues
    console=True,  # Enable console to see errors
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=None,  # Add icon='icon.ico' if you have an icon file
    uac_admin=False,
    uac_uiaccess=False,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,  # Disable UPX to avoid DLL loading issues
    upx_exclude=[],
    name='TabletHA',
)
