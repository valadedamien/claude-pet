#!/usr/bin/env bash
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PET_DIR="$HOME/.claude/pet"
SETTINGS="$HOME/.claude/settings.json"

echo "==> Retrait des hooks Claude Code"
python3 "$REPO_DIR/src/install_hooks.py" uninstall "$SETTINGS"

echo "==> Fermeture des pets actifs"
pkill -f "pet_app.app/Contents/MacOS/pet_app --session" 2>/dev/null || true

echo "==> Suppression de $PET_DIR"
rm -rf "$PET_DIR"

echo ""
echo "Claude Pet désinstallé."
