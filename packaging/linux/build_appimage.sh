#!/usr/bin/env bash
# Build groupwatch-<version>-x86_64.AppImage from the PyInstaller onedir output.
# Expects dist/groupwatch/ to exist (run PyInstaller first). Used by CI; also works locally.
set -euo pipefail

VERSION="${1:?usage: build_appimage.sh <version>}"
VERSION="${VERSION#v}"
[[ "$VERSION" =~ ^[0-9]+\.[0-9]+ ]] || VERSION="0.0.0-dev"

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT"

[[ -d dist/groupwatch ]] || { echo "dist/groupwatch missing — run PyInstaller first" >&2; exit 1; }

APPDIR="build/AppDir"
rm -rf "$APPDIR"
mkdir -p "$APPDIR/usr/bin"
cp -r dist/groupwatch "$APPDIR/usr/bin/groupwatch"
ln -s usr/bin/groupwatch/groupwatch "$APPDIR/AppRun"
cp packaging/linux/groupwatch.desktop "$APPDIR/groupwatch.desktop"
cp assets/icon.png "$APPDIR/groupwatch.png"

TOOL="build/appimagetool-x86_64.AppImage"
if [[ ! -x "$TOOL" ]]; then
    echo "Downloading appimagetool..."
    curl -fL -o "$TOOL" \
        https://github.com/AppImage/appimagetool/releases/download/continuous/appimagetool-x86_64.AppImage
    chmod +x "$TOOL"
fi

# --appimage-extract-and-run: avoids needing FUSE on headless CI runners.
ARCH=x86_64 "$TOOL" --appimage-extract-and-run "$APPDIR" "dist/groupwatch-${VERSION}-x86_64.AppImage"
echo "Built dist/groupwatch-${VERSION}-x86_64.AppImage"
