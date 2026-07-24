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

# Measured empirically: PermissionRequest fires ~10ms before PreToolUse for
# the same tool call. Both are async, so the pet's 300ms poll loop can easily
# never observe "waiting" at all before it's overwritten — not just miss
# seeing it briefly, miss it entirely. Enforce a minimum age on disk before
# any write is allowed to overwrite it. This only delays the async hook's
# own subprocess, never Claude's actual tool call.
#
# A plain "check age then write" isn't enough: two hook invocations are
# separate processes that can both check the file before either has written,
# racing straight past the hold. mkdir is atomic on any POSIX filesystem, so
# it doubles as a portable lock (no flock dependency) serializing check+write
# across concurrent hook processes for the same session.
MIN_HOLD_SECONDS=1.2
LOCK_MAX_WAIT_SECONDS=5

acquire_lock() {
  local lock_dir="$1" waited=0
  while ! mkdir "$lock_dir" 2>/dev/null; do
    sleep 0.02
    waited=$(python3 -c "print($waited + 0.02)")
    if python3 -c "exit(0 if $waited > $LOCK_MAX_WAIT_SECONDS else 1)"; then
      rmdir "$lock_dir" 2>/dev/null || true  # stale lock from a crashed process
    fi
  done
}

read_current_state() {
  [ -f "$STATE_FILE" ] || return 0
  python3 -c "
import json
try:
    print(json.load(open('$STATE_FILE')).get('state', ''))
except Exception:
    pass
"
}

# skip_if (optional 3rd arg): if the state on disk is currently this value,
# don't write at all. Used so PreToolUse can't prematurely clear "waiting" —
# it fires before the user has actually approved the permission prompt, so
# only PostToolUse/PostToolUseFailure (which can only fire after the tool
# truly ran) are trusted to move on from "waiting".
write_state() {
  local state="$1" tool="$2" skip_if="${3:-}"
  local tmp lock_dir="${STATE_FILE}.lock"

  acquire_lock "$lock_dir"

  if [ -n "$skip_if" ] && [ "$(read_current_state)" = "$skip_if" ]; then
    rmdir "$lock_dir" 2>/dev/null || true
    return 0
  fi

  if [ -f "$STATE_FILE" ]; then
    python3 -c "
import json, time
try:
    with open('$STATE_FILE') as f:
        prev_ts = json.load(f).get('ts_precise')
except Exception:
    prev_ts = None
if prev_ts is not None:
    remaining = $MIN_HOLD_SECONDS - (time.time() - float(prev_ts))
    if remaining > 0:
        time.sleep(remaining)
"
  fi

  local ts_precise
  ts_precise=$(python3 -c "import time; print(time.time())")
  tmp="$(mktemp "${STATE_FILE}.XXXXXX")"
  printf '{"state":"%s","tool":"%s","ts":%s,"ts_precise":%s}\n' "$state" "$tool" "$(date +%s)" "$ts_precise" > "$tmp"
  mv "$tmp" "$STATE_FILE"

  rmdir "$lock_dir" 2>/dev/null || true
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
    write_state "editing" "$TOOL" "waiting"
    ;;
  post)
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
