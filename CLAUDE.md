# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

Claude Pet: a floating pixel-art companion (macOS, Apple Silicon only) that reacts in real time to Claude Code's own hook events. It is not a conventional app you build/test/run — it's a small hooks integration (bash + Python) paired with a compiled pywebview window, distributed as a GitHub Release binary that `install.sh` downloads.

## Commands

There is no test suite, linter, or build step for iterating on most of the code — `pet.html`, `update_state.sh`, `install_hooks.py`, and `start_pet.sh` are plain files copied verbatim by `install.sh`.

- **Deploy local changes for manual testing** (fastest loop):
  ```bash
  ./uninstall.sh && ./install.sh
  ```
  This purges old hook entries from `~/.claude/settings.json` and reinstalls from the current working tree — necessary whenever `install_hooks.py`'s `HOOK_EVENTS` mapping changes, since a plain re-`install.sh` only adds/updates keys already in that dict, it never removes a hook event that was dropped from it.

- **Simulate a single hook event without waiting for the real trigger**:
  ```bash
  echo '{"session_id":"<id>","hook_event_name":"PreToolUse","tool_name":"Bash"}' | ~/.claude/pet/update_state.sh pre
  cat ~/.claude/pet/sessions/state_<id>.json
  ```
  Valid second args to `update_state.sh`: `prompt`, `pre`, `post`, `fail`, `waiting`, `done`, `start`, `end` (see the hook mapping table below).

- **Rebuild the compiled app** (only needed when `src/pet_app.py` changes — `pet.html`/`update_state.sh` don't require this):
  ```bash
  ./build/build.sh   # -> build/dist/Claude-Pet-macos-arm64.zip
  gh release create vX.Y.Z build/dist/Claude-Pet-macos-arm64.zip --title "..." --notes "..."
  ```
  `install.sh` always pulls the *latest* GitHub Release, so a new release is the only way an updated `pet_app.py` reaches anyone (including re-testing locally: reinstall via `./install.sh` re-downloads it).

- **Build tool is py2app, not PyInstaller** — PyInstaller compiles `pet_app.py` fine but the pywebview window silently never appears once frozen (no exception, just zero windows created); py2app works. `build/build.sh` builds in an isolated venv (`build/.build-venv/`) containing only `pywebview` + `py2app` — py2app's static analyzer breaks if PyInstaller is installed alongside (it tries to resolve webview's bundled PyInstaller hook files as importable submodules).

## Architecture

**Data flow**: Claude Code hook fires → `update_state.sh <arg>` (installed at `~/.claude/pet/`) reads the hook's JSON off stdin → writes `~/.claude/pet/sessions/state_<session_id>.json` → the compiled `pet_app.py` process for that session polls the file every 300ms and pushes changes into `pet.html`'s `window.setPetState()` via `pywebview.evaluate_js`.

**One pet process per Claude Code session**, not one global pet. `session_id` comes from the hook payload. Per-session files live in `~/.claude/pet/sessions/`: `state_<id>.json`, `pet_<id>.pid` (the pywebview process), `claude_<id>.pid` (the actual `claude` CLI process, used by a watchdog to self-close if the session dies without a clean `SessionEnd`). `pet_app.py`'s `session_slot()` counts other live sessions to pick a cascade window position and one of 6 skin colors (`SKIN_COLORS`) — both a function of "how many other pets are already running", not the session id itself.

**Hook → state mapping** (`src/install_hooks.py` `HOOK_EVENTS` dict + `src/update_state.sh` case statement — keep these two in sync when changing either):

| Hook event | `update_state.sh` arg | State written |
|---|---|---|
| `UserPromptSubmit` | `prompt` | `editing` |
| `PreToolUse` | `pre` | `editing`, **unless current state is `waiting`** (see below) |
| `PostToolUse` | `post` | `editing` |
| `PostToolUseFailure` | `fail` | `sad` |
| `PermissionRequest` | `waiting` | `waiting` |
| `Stop` | `done` | `done` (auto-reverts to `idle` after `DONE_TIMEOUT`=15s, in `pet_app.py`) |
| `SessionStart` | `start` | `idle`; also records the `claude` PID and launches the window if not already running |
| `SessionEnd` | `end` | closes the window, deletes this session's files |

`editing` persists for the entire turn (not just around one tool call) — `PostToolUse` writes the same `editing` state rather than reverting to `idle`, so multiple tool calls in a row don't flicker.

**Two non-obvious races, both fixed in `update_state.sh`, don't undo them without re-verifying empirically**:
1. `PermissionRequest` fires ~10ms before `PreToolUse` for the same tool call (measured directly with a timing log; don't trust hook-ordering claims from docs or agent lookups without re-checking — they were wrong/contradictory when this was investigated). Both hooks are separate async processes, so a naive "check age then write" still races: process B can read the file before process A finishes writing. Writes are serialized with an `mkdir`-based lock (`${STATE_FILE}.lock` — atomic on any POSIX filesystem, no `flock` dependency), and a state must be `MIN_HOLD_SECONDS` old before anything is allowed to overwrite it, so the pet's 300ms poll loop can't miss it entirely.
2. `PreToolUse` fires *before* the user actually approves a permission prompt, not after — confirmed by testing with a real approval delay. So `PreToolUse` cannot be trusted to mean "the tool is now running": `write_state`'s `skip_if` parameter makes the `pre` case a no-op whenever the current state is already `waiting`, and only `post`/`fail` (which can only fire after the tool truly executed) are allowed to clear it.

**pet_app.py's own `MIN_DISPLAY_SECONDS`** (currently 1.2s) is a second, independent floor on the read side: even if a state change is observed, it won't be pushed to the UI until the previously-pushed state has been visible for at least that long. Both floors were bumped from ~0.5s to 1.2s because the shorter value read as a flicker to a human, not because of a technical constraint.

**Rendering** (`src/pet.html`): a single SVG containing every state's body/eyes/decorations as sibling `<g data-only="state1,state2,...">` blocks; `setState()` just toggles `display` on whichever blocks match the current key and swaps the CSS animation class on `#anim-group`. States are pure CSS `steps()` keyframes (deliberately non-interpolated, for the pixel-art feel). The white pixel outline around the character is an SVG filter (`feMorphology` dilate + flood + merge), not a stroke. Skin color is a CSS custom property (`--skin-color`) set at runtime via `window.setPetSkin()`, kept separate from state-driven colors (badge/eyes/accents) so recoloring per session doesn't affect legibility of the state itself.

**Click-to-focus**: `pet_app.py` exposes a `js_api` (`Api.focus_terminal`) that pet.html calls on click. It walks up the process tree from the session's recorded `claude` PID (`find_owning_app_pid`) until it finds an ancestor whose `comm` path contains `.app/Contents/MacOS/` — that's the actual GUI app (Terminal/iTerm/VS Code/etc.) — then uses `osascript`/System Events to bring it to the front.

**Idempotent hook install** (`src/install_hooks.py`): every hook entry this project owns is tagged by the literal `update_state.sh` command path in `MARKER`. `install()`/`uninstall()` only ever touch entries matching that marker, so a user's own hooks (e.g. an unrelated `rtk` hook on `PreToolUse`) are left untouched. Settings are always backed up (`settings.json.claude-pet-backup-<timestamp>.json`) before being rewritten.
