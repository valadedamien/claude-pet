#!/usr/bin/env bash
SESSION_ID="${1:?usage: start_pet.sh <session_id>}"
nohup ~/.claude/pet/venv/bin/python3 ~/.claude/pet/pet_app.py --session "$SESSION_ID" >/dev/null 2>&1 &
disown