---
name: run-on-mac
description: Use this skill when the user asks to do something that has to happen on their Mac, outside the Cowork sandbox — running shell commands, git push/pull, docker, brew, accessing their SSH keys, editing files outside the bind-mount, or anything that needs their local environment. Routes the request through the cowork-to-code-bridge daemon.
---

# run-on-mac skill

The bridge connects Cowork to **Claude Code on the user's Mac**. The headline
capability: hand a free-form task to a local Claude Code agent via
`scripts/run_claude.sh`. You can also run other whitelisted scripts directly for
simple fixed actions. Use this any time the user asks for something that needs
their local machine.

## Hand a task to Claude Code (the main path)

```python
from cowork_to_code_bridge import call_remote

result = call_remote(
    "scripts/run_claude.sh",
    args=["Run the test suite and fix any failures", "/path/to/repo"],
    timeout=600,
    idempotency_key="fix-tests-2026-05-29-a",  # REQUIRED for Claude Code tasks
)
print(result["stdout"])   # what the local Claude Code agent reported back
```

**Always pass an `idempotency_key`** for `run_claude.sh` — a Claude Code task can
edit/commit/push, so if the connection drops and you retry, the key ensures the
daemon returns the cached result instead of running the agent a second time.

`run_claude.sh` runs Claude Code with normal local permissions. If the user wants
to restrict what a Cowork-originated task can do, point them to the
`CLAUDE_FLAGS` block in `~/.cowork-to-code-bridge/scripts/run_claude.sh` (e.g.
`--permission-mode plan` or a tool allowlist).

## Run a fixed script directly (simple actions)

For predictable, repeatable actions you don't need a full agent for:

## When to use this skill

Use `call_remote()` when the user wants:

- Shell commands that need their local environment (`brew install ...`, `gh ...`, `docker ...`)
- Git operations that need their SSH keys (`git push`, `git pull` from private repos)
- Reading/writing files outside the Cowork bind-mount
- Running tools installed only on the Mac (xcode, native apps, Spotlight)
- Anything that would fail with "command not found" or "permission denied" in the Cowork sandbox

## When NOT to use this skill

Don't use the bridge for:

- File operations inside the bind-mounted project (use normal file tools — faster, no daemon roundtrip)
- Read-only API calls that work fine from the sandbox (most HTTP, most MCP servers)
- Anything the user is doing in claude.ai web chat (no bridge there)

## How to call it

```python
from cowork_to_code_bridge import call_remote

result = call_remote(
    script="scripts/git_status.sh",   # must be whitelisted on Mac
    args=["AAQuant"],                  # optional positional args
    timeout=60,                        # max seconds the script can run
)

print(result["exit_code"])  # 0 = success
print(result["stdout"])
print(result["stderr"])
```

## The whitelist constraint

The daemon only runs scripts under `~/.cowork-to-code-bridge/scripts/` on the Mac. You **cannot** call `bash -c "..."` or arbitrary commands. This is intentional — it's the security model.

If the user wants to run something not yet whitelisted:

1. Ask them what they want to run.
2. Help them write a small shell script for it.
3. Tell them to save it as `~/.cowork-to-code-bridge/scripts/<name>.sh` on their Mac and `chmod +x` it.
4. Once they confirm it's saved, call it via `call_remote("scripts/<name>.sh", ...)`.

If the bridge isn't installed yet (`daemon_alive()` returns `False`), follow the setup flow: the user runs **one** `install.sh` curl command on their Mac (that starts the daemon), and you `pip install` the bridge client into the Cowork sandbox so `call_remote` / `daemon_alive` are importable here. There is **no `/plugin` step** — `/plugin` does not work inside Cowork. The full setup is in `skills/setup/SKILL.md`; the user-facing version is in the repo README.

Pre-installed scripts (always available after `install.sh`):

- `scripts/ping.sh` — health check, echoes OK + pwd + timestamp
- `scripts/hello.sh` — example, echoes args

## Error handling

```python
result = call_remote("scripts/foo.sh", timeout=30)

if result["exit_code"] == 0:
    # success
    pass
elif result["exit_code"] == -1:
    # daemon refused — bad script path, token mismatch, or script doesn't exist
    print(f"Daemon refused: {result.get('error')}")
elif result["exit_code"] == -2:
    # script ran but timed out
    print(f"Script exceeded {result.get('error')}")
    print(f"Partial output: {result.get('stdout')}")
elif result["exit_code"] == -3:
    # internal daemon error
    print(f"Daemon error: {result.get('error')}")
else:
    # script's own non-zero exit
    print(f"Script failed: {result['stderr']}")
```

`call_remote()` raises `TimeoutError` if the daemon doesn't respond at all (vs. the script running and timing out). On `TimeoutError`, suggest the user check the daemon: `launchctl list | grep cowork-to-code-bridge`.

## Configuration

The client auto-finds the bridge directory. If it can't:

```python
result = call_remote(
    "scripts/ping.sh",
    bridge_root="/path/to/.cowork-to-code-bridge",  # explicit override
)
```

The `BRIDGE_ROOT` and `BRIDGE_TOKEN` env vars also work for global override.

## What to surface to the user

When you call the bridge, tell the user briefly what you're doing:

> Running `git status` on your Mac via the bridge…

Don't dump the full `result` dict on them unless they ask. Show the relevant output (usually `stdout`) and any failure context.
