# Cowork-side usage examples

After the Mac daemon is installed and the client is importable:

## Health check

```python
from cowork_to_code_bridge import daemon_alive
assert daemon_alive(), "Daemon not responding — check launchctl on Mac"
```

## Hand a task to Claude Code on the Mac (the main use)

```python
from cowork_to_code_bridge import call_remote

r = call_remote(
    script="scripts/run_claude.sh",
    args=["Run the test suite and fix any failures", "/Users/me/myrepo"],
    timeout=600,
    idempotency_key="fix-tests-2026-05-29-a",  # REQUIRED — tasks have side effects
)
print(f"exit={r['exit_code']}")
print(r["stdout"])          # what the local Claude Code agent reported
print(r.get("idempotent_replay"))  # True if this was a cached retry, not a re-run
```

A retry with the same `idempotency_key` returns the cached result instead of
running Claude Code twice — safe after a dropped connection or `TimeoutError`.

## Run a fixed script with args (simple actions)

```python
from cowork_to_code_bridge import call_remote

r = call_remote(
    script="scripts/git_status.sh",
    args=["/Users/me/myrepo"],
    timeout=30,
)
print(f"exit={r['exit_code']}")
print(r["stdout"])
```

## Run with extra environment

```python
r = call_remote(
    script="scripts/deploy.sh",
    args=["staging"],
    env={"DEPLOY_TOKEN": "..."},
    timeout=300,
)
```

## Override bridge location

By default the client looks in `$BRIDGE_ROOT` then `./bridge`. If your Cowork bind-mount lives elsewhere:

```python
r = call_remote(
    "scripts/ping.sh",
    bridge_root="/sessions/abc123/mnt/myproject/bridge",
)
```

Or set once for the session:

```python
import os
os.environ["BRIDGE_ROOT"] = "/sessions/abc123/mnt/myproject/bridge"
```
