"""
client.py — Cowork-side helper to invoke whitelisted scripts on the user's Mac
via the polling bridge (queue/ + results/).

Requires the daemon to be running on the Mac (see daemon.py + install.sh).

Usage from a Cowork session:

    from cowork_to_code_bridge import call_remote
    r = call_remote(
        script="scripts/hello.sh",
        args=[],
        timeout=120,
    )
    print(r["exit_code"], r["stdout"])

Configuration (env vars):

    BRIDGE_ROOT   Directory containing queue/, results/, processed/.
                  Defaults to the parent of this package's install dir, or
                  $PWD/bridge if that doesn't look right. Override explicitly
                  in Cowork — the bind-mount path varies per session.
    BRIDGE_TOKEN  Shared secret matching the daemon's token. Read from .env
                  in BRIDGE_ROOT if not set in environment.
"""
from __future__ import annotations

import json
import os
import time
import uuid
from pathlib import Path
from typing import Any


def _resolve_bridge_root() -> Path:
    """Find the bind-mounted bridge directory.

    Resolution order:
      1. $BRIDGE_ROOT env var (explicit, recommended in Cowork)
      2. $PWD/bridge (the convention in projects using this lib)
      3. Parent of this package's install dir + /bridge
    """
    env = os.environ.get("BRIDGE_ROOT")
    if env:
        return Path(env)
    cwd_bridge = Path.cwd() / "bridge"
    if cwd_bridge.exists():
        return cwd_bridge
    # Fall back to package-relative (only useful for tests)
    return Path(__file__).resolve().parents[3] / "bridge"


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


def queue_task(
    script: str,
    args: list[str | int | float] | None = None,
    timeout: int = 60,
    cwd: str | None = None,
    env: dict[str, str] | None = None,
    bridge_root: Path | str | None = None,
    idempotency_key: str | None = None,
    plan: str | None = None,
    max_budget_usd: float | None = None,
    permission_scope: str | None = None,
    model_tier: str | None = None,
    effort: str | None = None,
) -> dict[str, Any]:
    """Queue a task WITHOUT waiting for result (async, non-blocking).

    Args:
        Same as call_remote, but returns immediately after queuing.

    Returns:
        Dict with keys: task_id (str), status (str "queued"), timestamp (float).
        Use poll_task_result(task_id) later to check for completion.

    This is useful when calling from environments with short timeouts (e.g., 45s
    bash sandbox). Queue the task, return immediately, then poll later.
    """
    root = Path(bridge_root) if bridge_root else _resolve_bridge_root()
    queue = root / "queue"
    queue.mkdir(parents=True, exist_ok=True)

    task_id = f"{int(time.time())}_{uuid.uuid4().hex[:8]}"
    payload: dict[str, Any] = {
        "id": task_id,
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
    if permission_scope is not None:
        payload["permission_scope"] = str(permission_scope)
    if model_tier is not None:
        payload["model_tier"] = str(model_tier).strip().lower()
    if effort is not None:
        payload["effort"] = str(effort).strip().lower()

    token = _load_token(root)
    if token:
        payload["token"] = token

    # Atomic write to queue
    task_file = queue / f"{task_id}.json"
    tmp = task_file.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(payload))
    tmp.rename(task_file)

    return {
        "task_id": task_id,
        "status": "queued",
        "timestamp": payload["ts_submitted"],
    }


# Braille spinner frames — same set Claude Code uses for its own ticker.
_SPINNER_FRAMES = "⣾⣽⣻⢿⡿⣟⣯⣷"


def format_status_line(
    status: dict[str, Any],
    *,
    verb: str = "Working",
    show_last_line: bool = False,
) -> str:
    """Render a daemon status dict into a human-facing ticker line.

    Produces strings like ``⣾ Working… 42s elapsed`` from the
    ``progress/<id>.status.json`` payload the daemon writes (see
    ``poll_task_result`` / ``call_remote(on_status=...)``).

    Args:
        status: a status dict with at least ``elapsed_s`` (int seconds). May
            also carry ``last_line`` (most recent script output) and ``state``.
        verb: the present-participle-ish label shown before the ellipsis
            (e.g. "Building", "Running tests"). Ignored once the task reports
            a terminal ``state`` of "done"/"failed".
        show_last_line: when True, append the script's most recent output line.

    The spinner frame is chosen from ``elapsed_s`` so successive polls advance
    it without the client tracking any frame counter.
    """
    elapsed = int(status.get("elapsed_s", 0) or 0)
    state = status.get("state", "running")

    if state == "done":
        head = f"✓ Done in {elapsed}s"
    elif state == "failed":
        head = f"✗ Failed after {elapsed}s"
    else:
        frame = _SPINNER_FRAMES[elapsed % len(_SPINNER_FRAMES)]
        head = f"{frame} {verb}… {elapsed}s elapsed"

    if show_last_line:
        last = str(status.get("last_line", "")).strip()
        if last:
            head = f"{head}  ·  {last}"
    return head


def poll_task_result(
    task_id: str,
    bridge_root: Path | str | None = None,
) -> dict[str, Any]:
    """Check if a queued task has completed (idempotent polling).

    Args:
        task_id: The task_id returned from queue_task().
        bridge_root: Override the auto-detected bridge directory.

    Returns:
        Dict with status (str):
          "queued" - task not yet picked up by daemon
          "running" - daemon is executing the task
          "completed" - task finished; dict also contains full result
                       (id, exit_code, stdout, stderr, ts_completed)

    This is fully idempotent — can be called multiple times without side effects.
    """
    root = Path(bridge_root) if bridge_root else _resolve_bridge_root()
    queue = root / "queue"
    results = root / "results"
    progress = root / "progress"

    # Check if result exists (task is done)
    result_file = results / f"{task_id}.json"
    if result_file.exists():
        try:
            result = json.loads(result_file.read_text())
            return {
                "status": "completed",
                **result,
            }
        except json.JSONDecodeError:
            pass  # File is being written; will check again on next poll

    # Check if progress log exists (task is running)
    progress_file = progress / f"{task_id}.log"
    if progress_file.exists():
        running: dict[str, Any] = {
            "status": "running",
            "task_id": task_id,
            "progress_available": True,
        }
        # Surface the daemon's live status ticker (elapsed_s / last_line /
        # state), written atomically to progress/<id>.status.json every ~2s.
        # This lets the non-blocking queue_task + poll_task_result flow show a
        # spinner without tailing the raw log. Best-effort: a missing or
        # half-written file just means no ticker this poll.
        status_file = progress / f"{task_id}.status.json"
        try:
            status = json.loads(status_file.read_text())
            if isinstance(status, dict):
                for key in ("elapsed_s", "last_line", "state"):
                    if key in status:
                        running[key] = status[key]
                running["status_line"] = format_status_line(status)
        except (OSError, json.JSONDecodeError):
            pass
        return running

    # Check if task is still in queue
    task_file = queue / f"{task_id}.json"
    if task_file.exists():
        return {
            "status": "queued",
            "task_id": task_id,
        }

    # Task not found — either never existed or was cleaned up
    return {
        "status": "unknown",
        "task_id": task_id,
        "message": "Task not found in queue or results",
    }


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

    Args:
        script: Path relative to the daemon's whitelist root, e.g. "scripts/hello.sh".
                Must match the daemon's safe-name regex.
        args: Positional args passed to the script verbatim.
        timeout: Max seconds the daemon will wait for the script to finish.
        poll_interval: Seconds between result-file polls on the client side.
        cwd: Working directory for the script on the Mac side.
        env: Extra env vars merged into the script's environment.
        bridge_root: Override the auto-detected bridge directory.
        idempotency_key: Optional. If two calls share the same key, the
            daemon executes the script only ONCE and returns the cached
            result on subsequent calls (the result is annotated with
            "idempotent_replay": True). Use this for non-idempotent
            operations (git push, deploy, money-moving) so a retry after
            TimeoutError is safe. Keys are persistent on the Mac via the
            daemon's journal — they survive daemon crashes and reboots.
        plan: Optional plain-English description of what the task will do.
            If ``scripts/approve_plan.sh`` exists on the machine, the daemon
            runs it with the plan text before executing the main script.
            The hook exits 0 to allow, 2 to reject (returning exit_code=-1
            with the hook's stderr as the error message). If the hook is
            absent the plan field is silently ignored.
        max_budget_usd: Optional per-task spend ceiling passed to
            ``run_claude.sh`` as ``--max-budget-usd``.  The daemon's owner
            can set ``BRIDGE_MAX_BUDGET_USD`` as a hard global ceiling; if
            both are present the effective limit is min(max_budget_usd,
            BRIDGE_MAX_BUDGET_USD).  Ignored for non-claude scripts.

    Returns:
        Dict with keys: id, exit_code, stdout, stderr, ts_completed.
        On daemon-side error: also has "error" key with diagnostic text.
        Exit code -4 means the daemon crashed mid-execution before this
        command finished; the actual script may or may not have run, so
        treat it as indeterminate.

    Raises:
        TimeoutError: If the daemon doesn't respond within `timeout + 5`s.
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
    # Atomic write: write to .tmp then rename so the daemon never reads a partial file.
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
                # Daemon may still be flushing — give it one more cycle.
                time.sleep(poll_interval)
                continue
        time.sleep(poll_interval)

    raise TimeoutError(
        f"bridge: no result for {cmd_id} within {timeout + 5}s. "
        f"Is the daemon running on the Mac? Check daemon logs or run "
        f"`launchctl list | grep cowork-to-code-bridge` on the Mac."
    )


def call_remote_streaming(
    script: str,
    args: list[str | int | float] | None = None,
    timeout: int = 600,
    poll_interval: float = 1.0,
    cwd: str | None = None,
    env: dict[str, str] | None = None,
    bridge_root: Path | str | None = None,
    idempotency_key: str | None = None,
    on_progress=None,
    on_status=None,
    plan: str | None = None,
    max_budget_usd: float | None = None,
) -> dict[str, Any]:
    """Like call_remote, but streams live output while the task runs.

    The daemon tees the script's stdout/stderr to a per-command progress file
    (progress/<id>.log). This polls that file and calls on_progress(new_text)
    for each new chunk as it appears — so long tasks (builds, test runs) show
    progress instead of waiting blind. Returns the same final result dict as
    call_remote once the task completes.

    on_progress: optional callable taking the newly-appended text (str). If
    None, new output is printed to stdout as it arrives.

    on_status: optional callable receiving status dicts written by the daemon
    every ~2 s to progress/<id>.status.json.  Each dict has:
        elapsed_s  (int)  seconds since the script started
        last_line  (str)  most recent non-empty output line
        state      (str)  "running" | "done" | "error"
        exit_code  (int)  present only when state != "running"
    Called only when the file changes (mtime-gated), so it fires at most once
    per daemon write cycle (~2 s).  Useful for a spinner / elapsed-time ticker.
    """
    root = Path(bridge_root) if bridge_root else _resolve_bridge_root()
    queue = root / "queue"
    results = root / "results"
    progress = root / "progress"
    to_cowork = root / "to_cowork"
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
    progress_file = progress / f"{cmd_id}.log"
    status_file = progress / f"{cmd_id}.status.json"
    emit = on_progress or (lambda chunk: print(chunk, end="", flush=True))
    seen = 0
    last_status_mtime: float = 0.0
    deadline = time.time() + timeout + 5
    while time.time() < deadline:
        # Stream any new progress output.
        try:
            if progress_file.exists():
                data = progress_file.read_text()
                if len(data) > seen:
                    emit(data[seen:])
                    seen = len(data)
        except OSError:
            pass
        # Fire on_status whenever the daemon updates the status file.
        if on_status is not None:
            try:
                mtime = status_file.stat().st_mtime
                if mtime > last_status_mtime:
                    last_status_mtime = mtime
                    on_status(json.loads(status_file.read_text()))
            except (OSError, json.JSONDecodeError):
                pass
        # Check for the final result.
        if result_file.exists():
            try:
                return json.loads(result_file.read_text())
            except json.JSONDecodeError:
                time.sleep(poll_interval)
                continue
        time.sleep(poll_interval)

    raise TimeoutError(
        f"bridge: no result for {cmd_id} within {timeout + 5}s. "
        f"Is the daemon running on the Mac?"
    )


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
        r = call_remote(
            "scripts/ping.sh",
            args=[],
            timeout=ping_timeout,
            bridge_root=bridge_root,
        )
        return r.get("exit_code") == 0
    except TimeoutError:
        return False


def post_message_to_cowork(
    message_type: str,
    content: str,
    parent_task_id: str | None = None,
    bridge_root: Path | str | None = None,
) -> str:
    """Post a message from Claude Code back to Cowork (bidirectional communication).

    Args:
        message_type: Type of message ("progress", "completed", "error", "info")
        content: Message content (plain text or JSON string)
        parent_task_id: Optional. The task_id of the parent task (sets parent field)
        bridge_root: Override the auto-detected bridge directory

    Returns:
        request_id: The ID of the posted message (can be replied to)

    This allows Claude Code (running on the machine) to post structured messages
    back to Cowork. Messages are written to to_cowork/ folder for Cowork to detect.
    """
    root = Path(bridge_root) if bridge_root else _resolve_bridge_root()
    to_cowork = root / "to_cowork"
    to_cowork.mkdir(parents=True, exist_ok=True)

    request_id = f"msg_{int(time.time())}_{uuid.uuid4().hex[:8]}"
    message = {
        "id": request_id,
        "type": message_type,
        "content": content,
        "ts": time.time(),
        "from": "claude-code",
    }
    if parent_task_id:
        message["parent"] = parent_task_id

    msg_file = to_cowork / f"{request_id}.json"
    tmp = msg_file.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(message))
    tmp.rename(msg_file)

    return request_id


def detect_messages_from_claude_code(
    parent_task_id: str | None = None,
    bridge_root: Path | str | None = None,
) -> list[dict[str, Any]]:
    """Detect and retrieve messages posted by Claude Code (bidirectional communication).

    Args:
        parent_task_id: Optional. Only return messages with this parent_task_id
        bridge_root: Override the auto-detected bridge directory

    Returns:
        List of message dicts {id, type, content, ts, from, parent (if set)}
        Returns empty list if no messages found.

    Messages are detected from to_cowork/ folder. If parent_task_id is specified,
    only messages with matching parent are returned. This is fully idempotent.
    """
    root = Path(bridge_root) if bridge_root else _resolve_bridge_root()
    to_cowork = root / "to_cowork"

    if not to_cowork.exists():
        return []

    messages = []
    for msg_file in sorted(to_cowork.glob("*.json")):
        if msg_file.suffix == ".answered":
            continue  # Skip already-answered messages
        try:
            msg = json.loads(msg_file.read_text())
        except (OSError, json.JSONDecodeError):
            continue

        # Filter by parent if specified
        if parent_task_id and msg.get("parent") != parent_task_id:
            continue

        messages.append(msg)

    return messages
