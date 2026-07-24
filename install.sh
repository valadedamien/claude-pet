#!/usr/bin/env bash
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PET_DIR="$HOME/.claude/pet"
SETTINGS="$HOME/.claude/settings.json"

if [[ "$(uname)" != "Darwin" ]]; then
  echo "Claude Pet ne fonctionne que sur macOS pour l'instant." >&2
  exit 1
fi

if ! command -v python3 >/dev/null; then
  echo "python3 est requis. Installe-le (ex: brew install python3) puis relance ce script." >&2
  exit 1
fi

echo "==> Copie des fichiers dans $PET_DIR"
mkdir -p "$PET_DIR"
cp "$REPO_DIR/src/pet.html" "$PET_DIR/pet.html"
cp "$REPO_DIR/src/pet_app.py" "$PET_DIR/pet_app.py"
cp "$REPO_DIR/src/update_state.sh" "$PET_DIR/update_state.sh"
cp "$REPO_DIR/src/start_pet.sh" "$PET_DIR/start_pet.sh"
chmod +x "$PET_DIR/update_state.sh" "$PET_DIR/start_pet.sh"

echo "==> Environnement Python dédié (venv, pour ne pas toucher à ton python système)"
if [[ ! -d "$PET_DIR/venv" ]]; then
  python3 -m venv "$PET_DIR/venv"
fi
"$PET_DIR/venv/bin/python3" -m pip install --upgrade pip -q
"$PET_DIR/venv/bin/python3" -m pip install -q pywebview

echo "==> Installation des hooks Claude Code (les tiens existants sont préservés)"
python3 "$REPO_DIR/src/install_hooks.py" install "$SETTINGS"

echo ""
echo "C'est bon ! Ouvre (ou relance) 'claude' dans un terminal pour voir apparaître ton pet."
echo "Pour désinstaller : $REPO_DIR/uninstall.sh"
