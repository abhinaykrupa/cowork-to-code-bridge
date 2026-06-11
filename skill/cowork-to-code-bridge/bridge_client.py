"""
bridge_client.py — SINGLE-FILE Cowork-side client for the cowork-to-code bridge.

This is a self-contained, zero-dependency (stdlib-only) copy of the bridge
client, meant to be dropped into a Cowork sandbox with ONE file fetch — no
`pip install`, no package, no outbound network beyond fetching this one file.
(The Cowork sandbox blocks outbound egress and prompts per fetch, so one file =
one prompt.)

It is kept in sync with `cowork_to_code_bridge/client.py`. If you have the full
package installed, prefer `from cowork_to_code_bridge import call_remote`.

Usage in a Cowork session:

    import os
    os.environ["BRIDGE_ROOT"] = "/Users/you/.cowork-to-code-bridge"  # from your Mac's .env
    from bridge_client import call_remote, daemon_alive
    print(daemon_alive())
    r = call_remote("scripts/run_claude.sh",
                    args=["Run the tests and fix failures", "/path/to/repo"],
                    timeout=600, idempotency_key="task-1")
    print(r["exit_code"], r["stdout"])

Or run it directly as a probe:

    BRIDGE_ROOT=/Users/you/.cowork-to-code-bridge python bridge_client.py
    # prints "BRIDGE LIVE" or "DAEMON NOT REACHABLE"
"""
from __future__ import annotations

import json
import os
import time
import uuid
from pathlib import Path
from typing import Any

__version__ = "0.5.1"


def _resolve_bridge_root() -> Path:
    """Find the bridge directory. Order: $BRIDGE_ROOT, $PWD/bridge, ./bridge."""
    env = os.environ.get("BRIDGE_ROOT")
    if env:
        return Path(env)
    cwd_bridge = Path.cwd() / "bridge"
    if cwd_bridge.exists():
        return cwd_bridge
    return Path.cwd() / "bridge"


def _load_token(bridge_root: Path) -> str | None:
    """Load BRIDGE_TOKEN: env var wins, else .env in bridge_root, else None."""
    env_tok = os.environ.get("BRIDGE_TOKEN")
    if env_tok:
        return env_tok
    env_file = bridge_root / ".env"
    if not env_file.exists():
        return None
    for line in env_file.read_text().splitlines():
        if line.strip().startswith("BRIDGE_TOKEN"):
            _, _, v = line.partition("=")
            return v.strip().strip('"').strip("'") or None
    return None


def call_remote(
    script: str,
    args: list[str | int | float] | None = None,
    timeout: int = 60,
    poll_interval: float = 1.0,
    cwd: str | None = None,
    env: dict[str, str] | None = None,
    bridge_root: Path | str | None = None,
    idempotency_key: str | None = None,
    plan: str | None = None,
    max_budget_usd: float | None = None,
) -> dict[str, Any]:
    """Submit a script invocation to the Mac daemon and wait for its result.

    See the full package docs for details. Key points:
      - `script` must be whitelisted on the Mac (e.g. "scripts/run_claude.sh").
      - `idempotency_key` makes retries safe: same key => the daemon runs the
        script once and returns the cached result (annotated idempotent_replay).
      - exit_code -4 = daemon crashed mid-run; treat as indeterminate.
      - `plan` is an optional plain-English description of what the task will do.
        If approve_plan.sh exists on the machine the daemon runs it first.
    Raises TimeoutError if the daemon doesn't respond within timeout + 5s.
    """
    root = Path(bridge_root) if bridge_root else _resolve_bridge_root()
    queue = root / "queue"
    results = root / "results"
    queue.mkdir(parents=True, exist_ok=True)
    results.mkdir(parents=True, exist_ok=True)

    cmd_id = f"{int(time.time())}_{uuid.uuid4().hex[:8]}"
    payload: dict[str, Any] = {
        "id": cmd_id,
        "script": script,
        "args": args or [],
        "timeout": timeout,
        "ts_submitted": time.time(),
    }
    if cwd:
        payload["cwd"] = cwd
    if env:
        payload["env"] = env
    if idempotency_key:
        payload["idempotency_key"] = idempotency_key
    if plan is not None:
        payload["plan"] = plan
    if max_budget_usd is not None:
        payload["max_budget_usd"] = float(max_budget_usd)

    token = _load_token(root)
    if token:
        payload["token"] = token

    cmd_file = queue / f"{cmd_id}.json"
    tmp = cmd_file.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(payload))
    tmp.rename(cmd_file)

    result_file = results / f"{cmd_id}.json"
    deadline = time.time() + timeout + 5
    while time.time() < deadline:
        if result_file.exists():
            try:
                return json.loads(result_file.read_text())
            except json.JSONDecodeError:
                time.sleep(poll_interval)
                continue
        time.sleep(poll_interval)

    raise TimeoutError(
        f"bridge: no result for {cmd_id} within {timeout + 5}s. "
        f"Is the daemon running on the Mac? Check "
        f"`launchctl list | grep cowork-to-code-bridge` on the Mac, and confirm "
        f"BRIDGE_ROOT matches the path in your Mac's ~/.cowork-to-code-bridge/.env."
    )


def call_remote_streaming(script, args=None, timeout=600, poll_interval=1.0,
                          cwd=None, env=None, bridge_root=None,
                          idempotency_key=None, on_progress=None, on_status=None,
                          plan=None, max_budget_usd=None) -> dict[str, Any]:
    """Like call_remote, but streams live output while the task runs.

    The daemon tees the script's output to progress/<id>.log; this polls it and
    calls on_progress(new_text) for each new chunk (or prints it if on_progress
    is None). Use for long tasks (builds, test runs) so they're not blind.
    Returns the same final result dict as call_remote.

    on_status: optional callable receiving status dicts written by the daemon
    every ~2 s to progress/<id>.status.json.  Each dict has:
        elapsed_s  (int)  seconds since the script started
        last_line  (str)  most recent non-empty output line
        state      (str)  "running" | "done" | "error"
        exit_code  (int)  present only when state != "running"
    Called only when the file changes (mtime-gated).
    """
    root = Path(bridge_root) if bridge_root else _resolve_bridge_root()
    queue = root / "queue"; results = root / "results"; progress = root / "progress"
    queue.mkdir(parents=True, exist_ok=True); results.mkdir(parents=True, exist_ok=True)
    cmd_id = f"{int(time.time())}_{uuid.uuid4().hex[:8]}"
    payload: dict[str, Any] = {"id": cmd_id, "script": script, "args": args or [],
                               "timeout": timeout, "ts_submitted": time.time()}
    if cwd: payload["cwd"] = cwd
    if env: payload["env"] = env
    if idempotency_key: payload["idempotency_key"] = idempotency_key
    if plan is not None: payload["plan"] = plan
    if max_budget_usd is not None: payload["max_budget_usd"] = float(max_budget_usd)
    token = _load_token(root)
    if token: payload["token"] = token
    cmd_file = queue / f"{cmd_id}.json"
    tmp = cmd_file.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(payload)); tmp.rename(cmd_file)
    result_file = results / f"{cmd_id}.json"
    progress_file = progress / f"{cmd_id}.log"
    status_file = progress / f"{cmd_id}.status.json"
    emit = on_progress or (lambda chunk: print(chunk, end="", flush=True))
    seen = 0
    last_status_mtime: float = 0.0
    deadline = time.time() + timeout + 5
    while time.time() < deadline:
        try:
            if progress_file.exists():
                data = progress_file.read_text()
                if len(data) > seen:
                    emit(data[seen:]); seen = len(data)
        except OSError:
            pass
        if on_status is not None:
            try:
                mtime = status_file.stat().st_mtime
                if mtime > last_status_mtime:
                    last_status_mtime = mtime
                    on_status(json.loads(status_file.read_text()))
            except (OSError, json.JSONDecodeError):
                pass
        if result_file.exists():
            try:
                return json.loads(result_file.read_text())
            except json.JSONDecodeError:
                time.sleep(poll_interval); continue
        time.sleep(poll_interval)
    raise TimeoutError(f"bridge: no result for {cmd_id} within {timeout + 5}s.")


def call_mcp_tool(
    server: str,
    method: str,
    params: dict | None = None,
    timeout: int = 60,
    bridge_root: str | None = None,
) -> dict:
    """Call a tool on a local stdio MCP server via the bridge proxy.

    The MCP server must be registered on the Mac with mcp_register.sh first.

    Args:
        server:  Name of the registered MCP server (e.g. "filesystem", "postgres").
        method:  MCP JSON-RPC method (e.g. "tools/list", "tools/call").
        params:  Method parameters dict (e.g. {"name": "query", "arguments": {...}}).
        timeout: Seconds to wait for the response.

    Returns:
        The bridge result dict.  r["mcp_response"] contains the parsed JSON-RPC
        response when exit_code == 0.  Check r["mcp_response"].get("error") for
        MCP-level errors.

    Example::

        r = call_mcp_tool("filesystem", "tools/list", {})
        tools = r["mcp_response"]["result"]["tools"]

        r = call_mcp_tool("postgres", "tools/call", {
            "name": "query",
            "arguments": {"sql": "SELECT count(*) FROM users"},
        })
        row = r["mcp_response"]["result"]["content"][0]["text"]
    """
<<<<<<< Updated upstream
    args = ["--server", server, "--method", method]
    if params is not None:
        args += ["--params", json.dumps(params)]
=======
    args = ["--server", server, "--method", method]
    if params is not None:
        args += ["--params", json.dumps(params)]
>>>>>>> Stashed changes
    r = call_remote("scripts/mcp_proxy.sh", args=args, timeout=timeout,
                    bridge_root=bridge_root)
    if r.get("exit_code") == 0 and r.get("stdout"):
        try:
<<<<<<< Updated upstream
            r["mcp_response"] = json.loads(r["stdout"])
=======
            r["mcp_response"] = json.loads(r["stdout"])
>>>>>>> Stashed changes
        except Exception:
            pass
    return r


def daemon_alive(bridge_root: Path | str | None = None, ping_timeout: int = 10) -> bool:
    """Quick health check — submits the ping script and waits for exit_code==0."""
    try:
        r = call_remote("scripts/ping.sh", args=[], timeout=ping_timeout,
                        bridge_root=bridge_root)
        return r.get("exit_code") == 0
    except TimeoutError:
        return False


if __name__ == "__main__":
    # Run directly as a probe: prints LIVE / NOT REACHABLE.
    alive = daemon_alive(ping_timeout=10)
    print("BRIDGE LIVE" if alive else "DAEMON NOT REACHABLE")
    raise SystemExit(0 if alive else 1)
