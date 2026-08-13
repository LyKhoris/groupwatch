# PyInstaller spec for groupwatch.
# Run from the repo root:  pyinstaller --noconfirm packaging/groupwatch.spec
# Output: dist/groupwatch/ (onedir) — the Windows installer and AppImage wrap this.
import os
import sys

# Paths in a spec file resolve relative to the spec's own directory.
ROOT = os.path.abspath(os.path.join(SPECPATH, ".."))

a = Analysis(
    [os.path.join(ROOT, "src/groupwatch/__main__.py")],
    pathex=[os.path.join(ROOT, "src")],
    binaries=[],
    datas=[(os.path.join(ROOT, "assets"), "assets")],
    hiddenimports=[],
    hookspath=[],
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="groupwatch",
    debug=False,
    strip=False,
    upx=False,
    console=False,  # tray app — no console window on Windows
    icon=os.path.join(ROOT, "assets/icon.ico") if sys.platform == "win32" else None,
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name="groupwatch",
)
