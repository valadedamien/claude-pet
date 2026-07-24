#!/usr/bin/env python3
import argparse
import glob
import json
import os
import subprocess
import time

import webview

SESSIONS_DIR = os.path.expanduser("~/.claude/pet/sessions")
HTML_FILE = os.path.expanduser("~/.claude/pet/pet.html")

POLL_INTERVAL = 0.3
MIN_DISPLAY_SECONDS = 1.2  # floor so a fast state change (e.g. waiting -> editing
                           # on an instant permission approval) stays visible
DONE_TIMEOUT = 15  # "done" auto-reverts to idle after this many seconds of no activity
WATCHDOG_EVERY = 10  # check claude liveness every N poll ticks (~3s)

BASE_X, BASE_Y = 60, 60
CASCADE_STEP = 36
CASCADE_WRAP = 8

# Same muted pastel tone as the original design's terracotta body, just
# rotated around the hue wheel — slot 0 keeps the original color.
SKIN_COLORS = ["#D37B5E", "#5E9BD3", "#7ED35E", "#C25ED3", "#D3B85E", "#5ED3B0"]


def read_state(state_file):
    try:
        with open(state_file) as f:
            data = json.load(f)
        return data.get("state", "idle"), data.get("tool", ""), data.get("ts", 0)
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return "idle", "", 0


def claude_still_alive(claude_pid_file):
    try:
        with open(claude_pid_file) as f:
            pid = int(f.read().strip())
        os.kill(pid, 0)
        return True
    except (FileNotFoundError, ValueError, ProcessLookupError, PermissionError):
        return False


def cleanup(session_id):
    for path in (
        os.path.join(SESSIONS_DIR, f"state_{session_id}.json"),
        os.path.join(SESSIONS_DIR, f"claude_{session_id}.pid"),
        os.path.join(SESSIONS_DIR, f"pet_{session_id}.pid"),
    ):
        try:
            os.remove(path)
        except OSError:
            pass


def poll_loop(window, session_id, skin):
    state_file = os.path.join(SESSIONS_DIR, f"state_{session_id}.json")
    claude_pid_file = os.path.join(SESSIONS_DIR, f"claude_{session_id}.pid")

    last_pushed = None
    last_push_time = 0.0
    skin_sent = False
    ticks = 0

    def resolved_state():
        state, tool, ts = read_state(state_file)
        idle_for = time.time() - ts if ts else 0
        if state == "done" and idle_for > DONE_TIMEOUT:
            state = "idle"
        return state, tool

    def push(state, tool):
        nonlocal last_pushed, last_push_time
        try:
            window.evaluate_js(f"window.setPetState({json.dumps(state)}, {json.dumps(tool or '')})")
        except Exception:
            pass
        last_pushed = (state, tool)
        last_push_time = time.time()

    while True:
        ticks += 1
        if ticks % WATCHDOG_EVERY == 0 and not claude_still_alive(claude_pid_file):
            cleanup(session_id)
            try:
                window.destroy()
            except Exception:
                pass
            return

        if not skin_sent:
            try:
                window.evaluate_js(f"window.setPetSkin({json.dumps(skin)})")
                skin_sent = True
            except Exception:
                pass

        state, tool = resolved_state()
        if (state, tool) != last_pushed:
            elapsed = time.time() - last_push_time
            if elapsed < MIN_DISPLAY_SECONDS:
                time.sleep(MIN_DISPLAY_SECONDS - elapsed)
                state, tool = resolved_state()  # pick up whatever's current once the floor has passed
            if (state, tool) != last_pushed:
                push(state, tool)

        time.sleep(POLL_INTERVAL)


def session_slot(session_id):
    """How many other pets are already alive when this one starts. Drives
    both the cascade position and the color tint, so the Nth concurrent pet
    is both offset on screen and visually distinct."""
    others = [
        p for p in glob.glob(os.path.join(SESSIONS_DIR, "pet_*.pid"))
        if os.path.basename(p) != f"pet_{session_id}.pid"
    ]
    alive = 0
    for path in others:
        try:
            with open(path) as f:
                os.kill(int(f.read().strip()), 0)
            alive += 1
        except (FileNotFoundError, ValueError, ProcessLookupError, PermissionError):
            pass
    return alive


def cascade_position(slot):
    wrapped = slot % CASCADE_WRAP
    return BASE_X + wrapped * CASCADE_STEP, BASE_Y + wrapped * CASCADE_STEP


def skin_color(slot):
    return SKIN_COLORS[slot % len(SKIN_COLORS)]


def find_owning_app_pid(start_pid, max_hops=15):
    """Walk up the process tree from a CLI pid to the nearest ancestor that
    is a real macOS app bundle (Terminal, iTerm, VS Code, etc.) — that's the
    process System Events can actually bring to the front."""
    pid = start_pid
    for _ in range(max_hops):
        if pid <= 1:
            return None
        try:
            comm = subprocess.check_output(["ps", "-o", "comm=", "-p", str(pid)], text=True).strip()
        except (subprocess.CalledProcessError, FileNotFoundError):
            return None
        if ".app/Contents/MacOS/" in comm:
            return pid
        try:
            pid = int(subprocess.check_output(["ps", "-o", "ppid=", "-p", str(pid)], text=True).strip())
        except (subprocess.CalledProcessError, ValueError):
            return None
    return None


def focus_pid(pid):
    script = f'tell application "System Events" to set frontmost of (first process whose unix id is {pid}) to true'
    subprocess.run(["osascript", "-e", script], check=False, capture_output=True)


class Api:
    def __init__(self, session_id):
        self.session_id = session_id

    def focus_terminal(self):
        claude_pid_file = os.path.join(SESSIONS_DIR, f"claude_{self.session_id}.pid")
        try:
            with open(claude_pid_file) as f:
                claude_pid = int(f.read().strip())
        except (FileNotFoundError, ValueError):
            return
        app_pid = find_owning_app_pid(claude_pid)
        if app_pid:
            focus_pid(app_pid)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--session", required=True)
    args = parser.parse_args()
    session_id = args.session

    os.makedirs(SESSIONS_DIR, exist_ok=True)
    pet_pid_file = os.path.join(SESSIONS_DIR, f"pet_{session_id}.pid")
    with open(pet_pid_file, "w") as f:
        f.write(str(os.getpid()))

    slot = session_slot(session_id)
    x, y = cascade_position(slot)
    skin = skin_color(slot)

    # Unique title per window: macOS remembers/cascades window frames keyed
    # by title, which fights our explicit x/y for same-titled windows.
    window = webview.create_window(
        f"Claude Pet {session_id[:8]}",
        HTML_FILE,
        js_api=Api(session_id),
        width=140,
        height=195,
        x=x,
        y=y,
        resizable=False,
        frameless=True,
        easy_drag=True,
        on_top=True,
        transparent=True,
    )

    webview.start(poll_loop, (window, session_id, skin))


if __name__ == "__main__":
    main()
