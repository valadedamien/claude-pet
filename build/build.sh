#!/usr/bin/env bash
# Builds src/pet_app.py into a standalone Claude Pet.app bundle (no Python
# needed on the machine that runs it), then zips it for a GitHub Release.
#
# Uses an isolated build venv with ONLY py2app + pywebview installed —
# py2app's static analysis chokes if PyInstaller is also present in the same
# environment (it tries to resolve webview's PyInstaller hook files as if
# they were importable submodules).
set -euo pipefail

BUILD_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV_DIR="$BUILD_DIR/.build-venv"

echo "==> Environnement de build isolé"
if [[ ! -d "$VENV_DIR" ]]; then
  python3 -m venv "$VENV_DIR"
fi
"$VENV_DIR/bin/python3" -m pip install -q --upgrade pip
"$VENV_DIR/bin/python3" -m pip install -q pywebview py2app

echo "==> Build (py2app)"
cd "$BUILD_DIR"
rm -rf build dist
"$VENV_DIR/bin/python3" setup.py py2app

echo "==> Compression"
cd dist
rm -f Claude-Pet-macos-arm64.zip
zip -qr Claude-Pet-macos-arm64.zip pet_app.app
cd "$BUILD_DIR"

echo ""
echo "Bundle: $BUILD_DIR/dist/pet_app.app"
echo "Archive: $BUILD_DIR/dist/Claude-Pet-macos-arm64.zip"
