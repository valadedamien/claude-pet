#!/usr/bin/env python3
import argparse
import glob
import json
import os
import subprocess
import time

import AppKit
import webview
from PyObjCTools import AppHelper
from webview.platforms.cocoa import BrowserView


def _accepts_first_mouse(self, event):
    # Without this, a click on the pet while it isn't the active app only
    # focuses the window (NSView's default acceptsFirstMouse is NO) instead of
    # also delivering the mouseDown that easy_drag needs to start the drag, so
    # dragging would take two clicks: one to focus, one to actually move it.
    return True


BrowserView.WebKitHost.acceptsFirstMouse_ = _accepts_first_mouse

HIT_ALPHA_THRESHOLD = 16  # 0-255; pixels this transparent or more let clicks pass through


class ClickThroughController:
    """Lets clicks pass through the fully-transparent pixels of the frameless
    pet window (the badge overhang, the margins around the sprite) to
    whatever's behind it, instead of the whole rectangular window swallowing
    every click just because it's technically the window's bounds.

    NSView.hitTest_ returning nil only stops OUR view from claiming a point —
    it doesn't make the window server route the click through to the window
    behind us. The actual mechanism is NSWindow.ignoresMouseEvents, toggled
    live: a global NSEvent monitor sees mouseMoved events when the cursor is
    over one of our (currently pass-through) transparent pixels — global
    monitors only see events *not* addressed to our own app, which is exactly
    what happens while ignoresMouseEvents is on — and a local monitor sees
    them once the cursor re-enters an opaque pixel and events start being
    addressed to us again. Both paths sample a cached alpha snapshot of the
    last rendered frame to decide which side of the threshold the cursor is
    currently on.
    """

    def __init__(self, window):
        self.pywebview_window = window
        self.ns_window = None
        self.webview = None
        self.alpha_rep = None
        self.alpha_size = (0, 0)
        self._monitors = []

    def install(self):
        if not self.pywebview_window.events.shown.wait(10):
            return
        bv = BrowserView.instances.get(self.pywebview_window.uid)
        if bv is None:
            return
        self.ns_window = bv.window
        self.webview = bv.webview
        self.ns_window.setAcceptsMouseMovedEvents_(True)
        mask = AppKit.NSEventMaskMouseMoved
        self._monitors.append(
            AppKit.NSEvent.addLocalMonitorForEventsMatchingMask_handler_(mask, self._on_move)
        )
        self._monitors.append(
            AppKit.NSEvent.addGlobalMonitorForEventsMatchingMask_handler_(mask, self._on_move)
        )
        self.request_snapshot()

    def request_snapshot(self):
        if self.webview is None:
            return
        AppHelper.callAfter(self._take_snapshot)

    def _take_snapshot(self):
        def done(image, error):
            if image is None:
                return
            rep = AppKit.NSBitmapImageRep.imageRepWithData_(image.TIFFRepresentation())
            if rep is None:
                return
            self.alpha_rep = rep
            self.alpha_size = (rep.pixelsWide(), rep.pixelsHigh())

        try:
            self.webview.takeSnapshotWithConfiguration_completionHandler_(None, done)
        except Exception:
            pass

    def _on_move(self, event):
        self._update_passthrough()
        return event

    def _update_passthrough(self):
        if self.ns_window is None or self.alpha_rep is None:
            return
        frame = self.ns_window.frame()
        if frame.size.width <= 0 or frame.size.height <= 0:
            return
        screen_point = AppKit.NSEvent.mouseLocation()
        local_x = screen_point.x - frame.origin.x
        local_y_from_bottom = screen_point.y - frame.origin.y
        if not (0 <= local_x < frame.size.width and 0 <= local_y_from_bottom < frame.size.height):
            self.ns_window.setIgnoresMouseEvents_(True)
            return

        # WebKitHost is a flipped view (origin top-left, y down), and the
        # cached bitmap's rows run top-down too, so flip the bottom-up
        # window-frame y before sampling it.
        view_y = frame.size.height - local_y_from_bottom

        rep_w, rep_h = self.alpha_size
        if rep_w <= 0 or rep_h <= 0:
            return
        px = min(max(int(local_x * rep_w / frame.size.width), 0), rep_w - 1)
        py = min(max(int(view_y * rep_h / frame.size.height), 0), rep_h - 1)
        color = self.alpha_rep.colorAtX_y_(px, py)
        alpha = int(color.alphaComponent() * 255) if color is not None else 0
        self.ns_window.setIgnoresMouseEvents_(alpha < HIT_ALPHA_THRESHOLD)


SESSIONS_DIR = os.path.expanduser("~/.claude/pet/sessions")
HTML_FILE = os.path.expanduser("~/.claude/pet/pet.html")
CONFIG_FILE = os.path.expanduser("~/.claude/pet/config.json")

BASE_WIDTH, BASE_HEIGHT = 170, 235  # extra height leaves room for the settings popup above the badge
HIDDEN_WIDTH, HIDDEN_HEIGHT = 170, 100  # collapsed size: just the badge row + skin dot (+ popup room)
SCALE_STEPS = [0.75, 0.9, 1.0, 1.15, 1.3, 1.5]
DEFAULT_SCALE_INDEX = SCALE_STEPS.index(1.0)


def window_size_for(hidden, scale_index):
    # The pet's CSS transform: scale() grows/shrinks the badge+controls along
    # with the character, in both normal and hidden mode — the window has to
    # scale by the same factor or it clips at larger sizes (hidden mode has
    # no character to make room for by shrinking, so this bit it hardest).
    scale = SCALE_STEPS[scale_index]
    if hidden:
        return round(HIDDEN_WIDTH * scale), round(HIDDEN_HEIGHT * scale)
    return round(BASE_WIDTH * scale), round(BASE_HEIGHT * scale)


def read_config():
    try:
        with open(CONFIG_FILE) as f:
            data = json.load(f)
    except (FileNotFoundError, ValueError, TypeError, json.JSONDecodeError, OSError):
        data = {}
    scale_index = data.get("scale_index", DEFAULT_SCALE_INDEX)
    if not isinstance(scale_index, int) or not (0 <= scale_index < len(SCALE_STEPS)):
        scale_index = DEFAULT_SCALE_INDEX
    hidden = bool(data.get("hidden", False))
    return scale_index, hidden


def write_config(scale_index, hidden):
    try:
        with open(CONFIG_FILE, "w") as f:
            json.dump({"scale_index": scale_index, "hidden": hidden}, f)
    except OSError:
        pass


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


def poll_loop(window, session_id, skin, scale, hidden, click_through):
    state_file = os.path.join(SESSIONS_DIR, f"state_{session_id}.json")
    claude_pid_file = os.path.join(SESSIONS_DIR, f"claude_{session_id}.pid")

    click_through.install()

    last_pushed = None
    last_push_time = 0.0
    skin_sent = False
    scale_sent = False
    hidden_sent = False
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
        click_through.request_snapshot()
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

        if not scale_sent:
            try:
                window.evaluate_js(f"window.setPetScale({json.dumps(scale)})")
                scale_sent = True
            except Exception:
                pass

        if not hidden_sent:
            try:
                window.evaluate_js(f"window.setPetHidden({json.dumps(hidden)})")
                hidden_sent = True
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
    def __init__(self, session_id, scale_index, hidden):
        self.session_id = session_id
        self.scale_index = scale_index
        self.hidden = hidden
        # Set by main() once the window/click-through controller exist — Api
        # has to be constructed before create_window() so it can be passed in
        # as js_api, before either of those objects exist yet.
        self.window = None
        self.click_through = None

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

    def request_snapshot(self):
        if self.click_through is not None:
            self.click_through.request_snapshot()

    def _resize_window_to(self, width, height):
        window = self.window

        def _apply():
            bv = BrowserView.instances.get(window.uid)
            if bv is None:
                return
            ns_window = bv.window
            frame = ns_window.frame()
            new_frame = AppKit.NSMakeRect(
                frame.origin.x - (width - frame.size.width) / 2,
                frame.origin.y - (height - frame.size.height) / 2,
                width,
                height,
            )
            ns_window.setFrame_display_(new_frame, True)

        AppHelper.callAfter(_apply)

    def resize_pet(self, delta):
        new_index = min(max(self.scale_index + delta, 0), len(SCALE_STEPS) - 1)
        if new_index == self.scale_index:
            return
        self.scale_index = new_index
        write_config(self.scale_index, self.hidden)

        scale = SCALE_STEPS[new_index]
        width, height = window_size_for(self.hidden, new_index)
        self._resize_window_to(width, height)
        self.window.evaluate_js(f"window.setPetScale({json.dumps(scale)})")
        if self.click_through is not None:
            self.click_through.request_snapshot()

    def set_pet_hidden(self, hidden):
        hidden = bool(hidden)
        if hidden == self.hidden:
            return
        self.hidden = hidden
        write_config(self.scale_index, self.hidden)

        width, height = window_size_for(hidden, self.scale_index)
        self._resize_window_to(width, height)

        self.window.evaluate_js(f"window.setPetHidden({json.dumps(hidden)})")
        if self.click_through is not None:
            self.click_through.request_snapshot()


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

    scale_index, hidden = read_config()
    scale = SCALE_STEPS[scale_index]
    width, height = window_size_for(hidden, scale_index)

    api = Api(session_id, scale_index, hidden)

    # Unique title per window: macOS remembers/cascades window frames keyed
    # by title, which fights our explicit x/y for same-titled windows.
    window = webview.create_window(
        f"Claude Pet {session_id[:8]}",
        HTML_FILE,
        js_api=api,
        width=width,
        height=height,
        x=x,
        y=y,
        resizable=False,
        frameless=True,
        easy_drag=True,
        on_top=True,
        transparent=True,
    )

    click_through = ClickThroughController(window)
    api.window = window
    api.click_through = click_through
    webview.start(poll_loop, (window, session_id, skin, scale, hidden, click_through))


if __name__ == "__main__":
    main()
