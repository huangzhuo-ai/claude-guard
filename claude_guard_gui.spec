# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for claude-guard GUI."""

block_cipher = None

a = Analysis(
    ['gui/app.py'],
    pathex=['.'],
    binaries=[],
    datas=[],
    hiddenimports=[
        'winreg',
        'winpty',
        'claude_guard.session_registry',
        'claude_guard.pty_host',
        'claude_guard.idle_detector',
        'claude_guard.supervisor',
        'claude_guard.snapshotter',
        'gui.workers',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=['pytest', 'anaconda'],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name='claude-guard',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,   # 不显示黑框终端窗口
    disable_windowed_traceback=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=None,
)
