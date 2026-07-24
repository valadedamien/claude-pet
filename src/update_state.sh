#!/usr/bin/env bash
set -euo pipefail

EVENT="$1"
SESSIONS_DIR="$HOME/.claude/pet/sessions"
mkdir -p "$SESSIONS_DIR"

IN=$(cat)

# Uses python3 (already a hard dependency for the pywebview app) instead of
# jq, so installing this doesn't add a separate Homebrew dependency.
json_get() {
  python3 -c "
import json, sys
d = json.load(sys.stdin)
print($1)
" <<< "$IN"
}

SESSION_ID=$(json_get "d.get('session_id', 'unknown')")
STATE_FILE="$SESSIONS_DIR/state_${SESSION_ID}.json"
CLAUDE_PID_FILE="$SESSIONS_DIR/claude_${SESSION_ID}.pid"
PET_PID_FILE="$SESSIONS_DIR/pet_${SESSION_ID}.pid"

write_state() {
  local state="$1" tool="$2"
  local tmp
  tmp="$(mktemp "${STATE_FILE}.XXXXXX")"
  printf '{"state":"%s","tool":"%s","ts":%s}\n' "$state" "$tool" "$(date +%s)" > "$tmp"
  mv "$tmp" "$STATE_FILE"
}

# Walk up the process tree from this script's parent looking for the actual
# `claude` CLI process, rather than assuming a fixed hop count — hook
# commands may or may not go through an intermediate shell depending on how
# Claude Code spawns them.
find_claude_pid() {
  local p="$PPID"
  for _ in 1 2 3 4 5; do
    [ -z "$p" ] && break
    local comm
    comm=$(ps -o comm= -p "$p" 2>/dev/null | xargs)
    if [ "$comm" = "claude" ]; then
      echo "$p"
      return 0
    fi
    p=$(ps -o ppid= -p "$p" 2>/dev/null | tr -d ' ')
  done
  echo "$PPID"
}

case "$EVENT" in
  prompt)
    write_state "editing" ""
    ;;
  pre)
    TOOL=$(json_get "d.get('tool_name', '?')")
    write_state "editing" "$TOOL"
    ;;
  fail)
    TOOL=$(json_get "d.get('tool_name', '?')")
    write_state "sad" "$TOOL"
    ;;
  waiting)
    write_state "waiting" ""
    ;;
  done)
    write_state "done" ""
    ;;
  start)
    find_claude_pid > "$CLAUDE_PID_FILE"
    write_state "idle" ""
    if [ ! -f "$PET_PID_FILE" ] || ! kill -0 "$(cat "$PET_PID_FILE" 2>/dev/null)" 2>/dev/null; then
      ~/.claude/pet/start_pet.sh "$SESSION_ID"
    fi
    ;;
  end)
    if [ -f "$PET_PID_FILE" ]; then
      kill "$(cat "$PET_PID_FILE" 2>/dev/null)" 2>/dev/null || true
    fi
    rm -f "$STATE_FILE" "$CLAUDE_PID_FILE" "$PET_PID_FILE"
    ;;
esac
