---
name: cowork-to-code-bridge
description: Connects Claude Cowork to Claude Code running on the user's own computer (macOS or Linux), so the whole machine is reachable from a Cowork chat. Use this skill whenever the user asks to do something that needs their actual machine and can't be done in the Cowork sandbox — building or running an app, running tests, git push/pull, installing packages, npm/pip/brew/docker, checking the machine's health/RAM/disk/processes, or any task they describe as "on my Mac" or "on my machine/server". Also triggers on "build me an app", "run this on my machine", "use Claude Code on my computer", "connect to my Mac", "check my machine". The bridge hands the task to a real Claude Code agent on the machine; it is idempotent and survives reboots.
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

**If the import fails or the path isn't visible** (e.g. `bridge_client` not found,
or `~/.cowork-to-code-bridge` doesn't exist in your sandbox): the bridge folder
isn't mounted into this session yet. **Request access to the folder**
`~/.cowork-to-code-bridge` (the same way you'd request any directory mount), then
read the `CLAUDE.md` inside it and re-run the connect snippet. This is the most
common first-time blocker — the user's machine is set up, but Cowork just needs
permission to see the folder.

- **BRIDGE LIVE** → the Mac is connected. Proceed.
- **DAEMON NOT REACHABLE** → the Mac side isn't set up (or the daemon is down).
  Tell the user, in plain language, to run **one** command in their Mac's
  Terminal (Spotlight → "Terminal"), then come back:

  ```
  curl -fsSL https://raw.githubusercontent.com/abhinaykrupa/cowork-to-code-bridge/main/install.sh | bash
  ```

  It takes ~30s, sets up the connection, and survives reboots. After they say
  it's done, re-run Step 1. (macOS, Linux, and WSL2 with systemd are supported.
  If they use native Windows without WSL, tell them to install via WSL2 — guide:
  https://github.com/abhinaykrupa/cowork-to-code-bridge/blob/main/docs/WSL.md)

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

**Pass `max_budget_usd` to cap API spend for a task:**

```python
r = call_remote(
    "scripts/run_claude.sh",
    args=["Refactor the auth module", "/path/to/repo"],
    timeout=300, idempotency_key="refactor-auth-1",
    max_budget_usd=2.00,   # agent stops if it hits $2.00 before finishing
)
```

The owner can set `BRIDGE_MAX_BUDGET_USD=5.00` in their launchd/systemd env as a
global ceiling — any per-task budget above the ceiling is silently capped. This
protects against runaway tasks from non-technical users who don't understand API
costs. If neither is set, no spend ceiling is enforced (Claude CLI default).

For tasks that only need read access, request a tighter permission scope:

```python
r = call_remote(
    "scripts/run_claude.sh",
    args=["Summarise the last 10 commits", "/Users/<them>/projects/app"],
    timeout=120, idempotency_key="summarise-1",
    permission_mode="plan",   # read-only: no edits, no shell commands
)
```

Valid `permission_mode` values (least → most permissive): `"plan"`, `"acceptEdits"`,
`"bypassPermissions"`. The daemon enforces the owner's `BRIDGE_PERMISSION_CEILING`
\u2014 a mode above the ceiling is rejected before any script runs. Omit `permission_mode`
to use the owner's global `CLAUDE_FLAGS` unchanged.

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

### Live status ticker (spinner line, no log dump)

For a clean single-line status instead of raw log output, use `on_status`:

```python
def on_status(s):
    SPINNER = "⣾⣽⣻⢿⡿⣟⣯⣷"
    tick = s["elapsed_s"] % len(SPINNER)
    print(f"\r  {SPINNER[tick]} {s['last_line'][:60]}… ({s['elapsed_s']}s)", end="", flush=True)

r = call_remote_streaming(
    "scripts/run_claude.sh",
    args=["Run the tests and fix failures", "/Users/<them>/projects/repo"],
    timeout=600, idempotency_key="test-run-1",
    on_status=on_status,
)
print()  # newline after spinner
print(r["exit_code"]); print(r["stdout"])
```

`on_status` is called every ~2s with `{"elapsed_s": int, "last_line": str, "state": "running"|"done"|"error"}`.
`on_progress` and `on_status` are independent — use either or both.

## Step 3 — quick fixed actions (no agent needed)

For simple, fast system queries, call a ready-made script directly:

| User asks | Call |
|---|---|
| "check my Mac's health" | `call_remote("scripts/mac_health.sh")` |
| "how much RAM / memory?" | `call_remote("scripts/mac_ram.sh")` |
| "disk space?" | `call_remote("scripts/mac_disk.sh")` |
| "what's using CPU?" | `call_remote("scripts/mac_top.sh")` |
| "network status?" | `call_remote("scripts/mac_network.sh")` |
| "what's listening on port 3000?" | `call_remote("scripts/port_check.sh", args=["3000"])` |
| "what Docker containers are running?" | `call_remote("scripts/docker_ps.sh")` |
| "what's the git status of ~/myproject?" | `call_remote("scripts/git_status.sh", args=["/path/to/repo"])` |
| "any outdated packages?" | `call_remote("scripts/pkg_outdated.sh")` |
| "what MCPs do you have on your machine?" | `call_remote("scripts/mcp_audit.sh")` |

For a repeatable custom action, help the user save a small script in
`~/.cowork-to-code-bridge/scripts/` on their Mac, then call it by name.

### Cross-surface MCP audit

There is no built-in Anthropic tool to compare MCPs registered in local Claude
Code vs what a Cowork session can reach (ref: anthropics/claude-code#56353).
`mcp_audit.sh` captures the local side so you can diff it here:

```python
import json

r = call_remote("scripts/mcp_audit.sh")
local = json.loads(r["stdout"])

print(f"Machine: {local['hostname']}  (Claude Code {local['claude_version']})")
print(f"Registered MCPs: {local.get('mcp_count', '?')}")

# If structured JSON is available (Claude Code >= recent version):
for mcp in local.get("mcps", []):
    print(f"  [{mcp.get('scope','?')}] {mcp.get('name','?')}  type={mcp.get('type','?')}")

# If older Claude Code (plain-text fallback):
if "mcps_raw" in local:
    print(local["mcps_raw"])
```

Compare the names in `local["mcps"]` against the connectors/plugins visible in
this Cowork session. Any MCP present locally but absent here is a gap —
the user may need to install the corresponding Cowork plugin or expose the
MCP via the bridge.

## Step 4 — check the inbox (reverse direction: Claude Code → Cowork)

Claude Code on the user's machine can leave requests for a Cowork session in
`BRIDGE_ROOT/to_cowork/`. When the user says "check my inbox", "any requests
from Claude Code?", or "did my machine leave me anything?", look for pending
requests and act on them:

```python
import os, json, glob, time
root = os.environ.get("BRIDGE_ROOT") or os.path.expanduser("~/.cowork-to-code-bridge")
inbox = os.path.join(root, "to_cowork")
replies = os.path.join(root, "cowork_results")
os.makedirs(replies, exist_ok=True)
pending = sorted(glob.glob(os.path.join(inbox, "*.json")))
for p in pending:
    req = json.load(open(p))
    print(req["id"], "→", req["request"])
    # ... do the requested work (it's a plain-English task from the machine) ...
    # then write a reply and archive the request:
    # json.dump({"id": req["id"], "reply": "<what you did>", "ts": time.time()},
    #           open(os.path.join(replies, req["id"] + ".json"), "w"))
    # os.remove(p)
```

**Honest limitation:** this only works while a Cowork session is open and the
user asks to check — there's no way to wake Cowork from the machine. It's an
async hand-off inbox, not a live channel. If the user wants a guaranteed live
exchange, they should just ask here directly.

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
