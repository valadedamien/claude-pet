#!/usr/bin/env python3
"""Idempotently add/remove Claude Pet's hooks in ~/.claude/settings.json
without touching any other hooks already configured there (e.g. a personal
rtk hook on Bash). Entries are tagged by the literal update_state.sh path,
so re-running install is safe and uninstall only ever removes our own."""
import json
import os
import shutil
import sys
from datetime import datetime, timezone

MARKER = "/.claude/pet/update_state.sh"

# Maps each Claude Code hook event to the update_state.sh argument it should fire.
HOOK_EVENTS = {
    "PreToolUse": "pre",
    "PostToolUse": "post",
    "PostToolUseFailure": "fail",
    "Notification": "waiting",
    "Stop": "done",
    "SessionStart": "start",
    "SessionEnd": "end",
}


def hook_command(event_arg):
    return f"~/.claude/pet/update_state.sh {event_arg}"


def is_ours(entry):
    if not isinstance(entry, dict):
        return False
    hooks = entry.get("hooks")
    if not isinstance(hooks, list):
        return False
    return any(isinstance(h, dict) and MARKER in h.get("command", "") for h in hooks)


def backup(path):
    if not os.path.exists(path):
        return None
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    backup_path = f"{path}.claude-pet-backup-{ts}.json"
    shutil.copy2(path, backup_path)
    return backup_path


def load_settings(path):
    if not os.path.exists(path):
        return {}
    with open(path) as f:
        return json.load(f)


def write_settings(path, settings):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = f"{path}.tmp.{os.getpid()}"
    with open(tmp, "w") as f:
        json.dump(settings, f, indent=2)
        f.write("\n")
    os.replace(tmp, path)


def install(path):
    settings = load_settings(path)
    hooks = settings.setdefault("hooks", {})
    for event, arg in HOOK_EVENTS.items():
        entries = hooks.setdefault(event, [])
        if not isinstance(entries, list):
            print(f"hooks.{event} is not a list, skipping that event.", file=sys.stderr)
            continue
        entries[:] = [e for e in entries if not is_ours(e)]
        entries.append({
            "hooks": [{
                "type": "command",
                "command": hook_command(arg),
                "async": True,
            }]
        })
    bpath = backup(path)
    write_settings(path, settings)
    print(f"Hooks installed in {path}" + (f" (backup: {bpath})" if bpath else ""))


def uninstall(path):
    settings = load_settings(path)
    hooks = settings.get("hooks")
    if not isinstance(hooks, dict):
        print("No hooks to remove.")
        return
    for event in list(hooks.keys()):
        entries = hooks[event]
        if not isinstance(entries, list):
            continue
        cleaned = [e for e in entries if not is_ours(e)]
        if cleaned:
            hooks[event] = cleaned
        else:
            del hooks[event]
    if not hooks:
        settings.pop("hooks", None)
    bpath = backup(path)
    write_settings(path, settings)
    print(f"Hooks removed from {path}" + (f" (backup: {bpath})" if bpath else ""))


if __name__ == "__main__":
    if len(sys.argv) != 3 or sys.argv[1] not in ("install", "uninstall"):
        print("Usage: install_hooks.py <install|uninstall> <settings.json path>", file=sys.stderr)
        sys.exit(1)
    (install if sys.argv[1] == "install" else uninstall)(sys.argv[2])
