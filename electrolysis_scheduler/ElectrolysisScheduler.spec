# -*- mode: python ; coding: utf-8 -*-

# datas=[] below is empty because there are currently no non-.py resource
# files (icons, images, templates, etc.) the app loads at runtime - only
# PyInstaller's automatic import scanning is relied on. If one is ever
# added, it must be listed explicitly here (e.g.
# ('ui/assets/icon.ico', 'ui/assets')) or PyInstaller will silently omit it
# from the build even though `python main.py` still works fine from source.

a = Analysis(
    ['main.py'],
    pathex=[],
    binaries=[],
    datas=[],
    hiddenimports=[],
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
    [],
    exclude_binaries=True,
    name='ElectrolysisScheduler',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='ElectrolysisScheduler',
)
