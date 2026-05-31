---
name: cowork-to-code-bridge
description: Connects Claude Cowork to Claude Code running on the user's Mac, so the whole machine is reachable from a Cowork chat. Use this skill whenever the user asks to do something that needs their actual Mac and can't be done in the Cowork sandbox — building or running an app, running tests, git push/pull, installing packages, npm/pip/brew/docker, checking the Mac's health/RAM/disk/processes, or any task they describe as "on my Mac". Also triggers on "build me an app", "run this on my Mac", "use Claude Code on my machine", "connect to my Mac", "check my Mac". The bridge hands the task to a real Claude Code agent on the Mac; it is idempotent and survives reboots.
---

# cowork-to-code-bridge

You are in a Cowork sandbox. This skill lets you reach **Claude Code running on
the user's Mac** through a small local daemon, so tasks that need the real
machine (builds, tests, git, installs, system checks) actually run there and the
results come back here.

The client (`bridge_client.py`) is **already installed next to this file** — it
ships with the skill. **Do NOT fetch or download anything, and do NOT use
`/plugin`.** Just import the client.

## Step 1 — connect (always do this first)

```python
import os, sys, json
SKILL_DIR = os.path.expanduser("~/.claude/skills/cowork-to-code-bridge")
sys.path.insert(0, SKILL_DIR)
# BRIDGE_ROOT is written by the Mac installer into bridge_env.json next to this file.
cfg = os.path.join(SKILL_DIR, "bridge_env.json")
if os.path.exists(cfg):
    os.environ.setdefault("BRIDGE_ROOT", json.load(open(cfg)).get("BRIDGE_ROOT", ""))
from bridge_client import daemon_alive, call_remote
print("BRIDGE LIVE" if daemon_alive(ping_timeout=10) else "DAEMON NOT REACHABLE")
```

- **BRIDGE LIVE** → the Mac is connected. Proceed.
- **DAEMON NOT REACHABLE** → the Mac side isn't set up (or the daemon is down).
  Tell the user, in plain language, to run **one** command in their Mac's
  Terminal (Spotlight → "Terminal"), then come back:

  ```
  curl -fsSL https://raw.githubusercontent.com/abhinaykrupa/cowork-to-code-bridge/main/install.sh | bash
  ```

  It takes ~30s, sets up the connection, and survives reboots. After they say
  it's done, re-run Step 1. (macOS only — if their computer is Windows/Linux,
  this bridge won't work; stop and tell them.)

## Step 2 — hand a task to Claude Code on the Mac (the main use)

For anything open-ended — "build me an app", "run the tests and fix failures",
"set up this project" — delegate to a real Claude Code agent on the Mac:

```python
r = call_remote(
    "scripts/run_claude.sh",
    args=["Build a Flask app with a /health route, install deps, run it, confirm it responds", "/Users/<them>/projects/myapp"],
    timeout=600,
    idempotency_key="build-myapp-2026-05-31-a",   # REQUIRED — see below
)
print(r["exit_code"])
print(r["stdout"])   # what the local Claude Code agent did + reported
```

**Always pass a unique `idempotency_key`** for `run_claude.sh`: a Claude Code task
can edit/commit/push, so if the connection drops and you retry, the key makes the
daemon return the cached result instead of running the agent twice.

### Long tasks — stream live progress (don't wait blind)

Builds and test runs can take minutes. Use `call_remote_streaming` so you see
output as it happens and can relay progress to the user instead of going silent:

```python
from bridge_client import call_remote_streaming
def show(chunk): print(chunk, end="")   # or summarize to the user as it streams
r = call_remote_streaming(
    "scripts/run_claude.sh",
    args=["Set up the project, install deps, run the build", "/Users/<them>/projects/app"],
    timeout=900, idempotency_key="build-app-1", on_progress=show,
)
print(r["exit_code"])
```

Tell the user what's happening as chunks arrive (e.g. "installing deps…",
"running tests…") rather than leaving them waiting. Same final result + same
idempotency guarantees as `call_remote`.

## Step 3 — quick fixed actions (no agent needed)

For simple, fast system queries, call a ready-made script directly:

| User asks | Call |
|---|---|
| "check my Mac's health" | `call_remote("scripts/mac_health.sh")` |
| "how much RAM / memory?" | `call_remote("scripts/mac_ram.sh")` |
| "disk space?" | `call_remote("scripts/mac_disk.sh")` |
| "what's using CPU?" | `call_remote("scripts/mac_top.sh")` |
| "network status?" | `call_remote("scripts/mac_network.sh")` |

For a repeatable custom action, help the user save a small script in
`~/.cowork-to-code-bridge/scripts/` on their Mac, then call it by name.

## Result shape & errors

`call_remote` returns a dict: `exit_code`, `stdout`, `stderr`. Special codes:
- `-1` daemon refused (bad/unknown script, token mismatch)
- `-2` script timed out
- `-3` internal daemon error
- `-4` daemon crashed mid-run — indeterminate, NOT retried (treat as unknown)
- `idempotent_replay: True` → this was a cached result from a same-key retry

Raises `TimeoutError` if the daemon never responds → tell the user to check it's
running (the installer sets it to auto-start; a reboot shouldn't break it).

## What to tell the user
Be brief: "Running that on your Mac via Claude Code…" then show the relevant
output. Don't dump the whole result dict unless asked. Never claim success
without a `BRIDGE LIVE` / `exit_code == 0`.
