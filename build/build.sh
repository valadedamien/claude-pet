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

echo "==> Nettoyage des chemins locaux dans Info.plist"
# py2app records the build venv's own interpreter path (an absolute path
# under this machine's home directory) in PythonInfoDict.PythonExecutable —
# purely informational metadata, unused at runtime, but it leaks the local
# username/folder structure into a binary that gets publicly distributed.
/usr/libexec/PlistBuddy -c "Set :PythonInfoDict:PythonExecutable python3" dist/pet_app.app/Contents/Info.plist

# Every bundled module's .pyc cache also embeds the absolute build path as
# its recorded source filename (for tracebacks) — same leak, much wider
# blast radius (hundreds of files, including third-party deps). Every one
# ships its .py source right next to the cache, so deleting is safe: Python
# recompiles on first import, baking in only the *installing* user's own
# path from then on, never this machine's.
find dist/pet_app.app -type d -name "__pycache__" -exec rm -rf {} +

echo "==> Compression"
cd dist
rm -f Claude-Pet-macos-arm64.zip
zip -qr Claude-Pet-macos-arm64.zip pet_app.app
cd "$BUILD_DIR"

echo ""
echo "Bundle: $BUILD_DIR/dist/pet_app.app"
echo "Archive: $BUILD_DIR/dist/Claude-Pet-macos-arm64.zip"
