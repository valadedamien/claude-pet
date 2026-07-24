#!/usr/bin/env bash
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PET_DIR="$HOME/.claude/pet"
SETTINGS="$HOME/.claude/settings.json"
RELEASE_URL="https://github.com/valadedamien/claude-pet/releases/latest/download/Claude-Pet-macos-arm64.zip"

if [[ "$(uname)" != "Darwin" ]]; then
  echo "Claude Pet ne fonctionne que sur macOS pour l'instant." >&2
  exit 1
fi
if [[ "$(uname -m)" != "arm64" ]]; then
  echo "Le binaire fourni est pour Apple Silicon (arm64) uniquement." >&2
  exit 1
fi
if ! command -v python3 >/dev/null; then
  echo "python3 est requis (pour les hooks — pas pour l'appli elle-même). Installe-le (ex: brew install python3) puis relance." >&2
  exit 1
fi

echo "==> Copie des fichiers dans $PET_DIR"
mkdir -p "$PET_DIR"
cp "$REPO_DIR/src/pet.html" "$PET_DIR/pet.html"
cp "$REPO_DIR/src/update_state.sh" "$PET_DIR/update_state.sh"
cp "$REPO_DIR/src/start_pet.sh" "$PET_DIR/start_pet.sh"
chmod +x "$PET_DIR/update_state.sh" "$PET_DIR/start_pet.sh"

echo "==> Téléchargement de l'application (binaire autonome, aucune dépendance Python pour la faire tourner)"
TMP_ZIP="$(mktemp /tmp/claude-pet-XXXXXX.zip)"
curl -fL --progress-bar "$RELEASE_URL" -o "$TMP_ZIP"
rm -rf "$PET_DIR/pet_app.app"
unzip -q "$TMP_ZIP" -d "$PET_DIR"
rm -f "$TMP_ZIP"
# Defensive: plain curl downloads aren't quarantined like browser downloads,
# but strip the flag anyway in case it ends up set some other way.
xattr -dr com.apple.quarantine "$PET_DIR/pet_app.app" 2>/dev/null || true

echo "==> Installation des hooks Claude Code (les tiens existants sont préservés)"
python3 "$REPO_DIR/src/install_hooks.py" install "$SETTINGS"

echo ""
echo "C'est bon ! Ouvre (ou relance) 'claude' dans un terminal pour voir apparaître ton pet."
echo "Pour désinstaller : $REPO_DIR/uninstall.sh"
