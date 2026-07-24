#!/usr/bin/env bash
SESSION_ID="${1:?usage: start_pet.sh <session_id>}"
nohup ~/.claude/pet/pet_app.app/Contents/MacOS/pet_app --session "$SESSION_ID" >/dev/null 2>&1 &
disown