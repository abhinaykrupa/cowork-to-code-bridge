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
        return {
            "status": "running",
            "task_id": task_id,
            "progress_available": True,
        }

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
    interactive: bool = False,
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

    interactive: when True, each poll iteration also scans to_cowork/*.json for
    a request whose "parent" field matches this cmd_id. If found, returns early
    with shape:
        {"state": "awaiting_reply", "cmd_id": ..., "request_id": ...,
         "question": ..., "from": "claude-code"}
    The caller should show the question, call reply_to_machine(request_id, answer),
    then call resume_remote(cmd_id, remaining_deadline) to re-enter the wait loop.
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
        # Interactive mode: check whether the running task has asked a question.
        if interactive and to_cowork.exists():
            for req_file in sorted(to_cowork.glob("*.json")):
                try:
                    req = json.loads(req_file.read_text())
                except (OSError, json.JSONDecodeError):
                    continue
                if req.get("parent") == cmd_id:
                    req_file.rename(req_file.with_suffix(".json.answered"))
                    return {
                        "state": "awaiting_reply",
                        "cmd_id": cmd_id,
                        "request_id": req.get("id", req_file.stem),
                        "question": req.get("request", ""),
                        "from": req.get("from", "claude-code"),
                        "_deadline": deadline,
                        "_bridge_root": str(root),
                    }
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


def reply_to_machine(
    request_id: str,
    text: str,
    bridge_root: Path | str | None = None,
) -> None:
    """Write a reply to a mid-task question raised by a running script.

    Call this after call_remote_streaming returns {"state": "awaiting_reply"}.
    Writes the reply JSON to cowork_results/<request_id>.json so request_cowork.sh
    --wait polling on the Mac side picks it up and unblocks the script.

    Args:
        request_id: the "request_id" field from the awaiting_reply dict.
        text:       the answer to send back (plain string).
    """
    root = Path(bridge_root) if bridge_root else _resolve_bridge_root()
    cowork_results = root / "cowork_results"
    cowork_results.mkdir(parents=True, exist_ok=True)
    reply = {"id": request_id, "reply": text, "ts": time.time(), "from": "cowork"}
    out = cowork_results / f"{request_id}.json"
    tmp = out.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(reply))
    tmp.rename(out)


def resume_remote(
    cmd_id: str,
    deadline: float,
    poll_interval: float = 1.0,
    on_progress=None,
    on_status=None,
    interactive: bool = True,
    bridge_root: Path | str | None = None,
) -> dict[str, Any]:
    """Re-enter the wait loop for a task after answering its question.

    Call this after reply_to_machine() to continue waiting for the task's
    final result (or its next question, if interactive=True).

    Args:
        cmd_id:    the "cmd_id" from the awaiting_reply dict.
        deadline:  the "_deadline" from the awaiting_reply dict (absolute epoch time).
                   Preserves the original timeout budget — the clock never resets.
    Returns:
        Same dict shapes as call_remote_streaming: final result or another
        awaiting_reply if the task asks another question.
    """
    root = Path(bridge_root) if bridge_root else _resolve_bridge_root()
    results = root / "results"
    progress = root / "progress"
    to_cowork = root / "to_cowork"
    result_file = results / f"{cmd_id}.json"
    progress_file = progress / f"{cmd_id}.log"
    status_file = progress / f"{cmd_id}.status.json"
    emit = on_progress or (lambda chunk: print(chunk, end="", flush=True))
    seen = 0
    last_status_mtime: float = 0.0
    while time.time() < deadline:
        try:
            if progress_file.exists():
                data = progress_file.read_text()
                if len(data) > seen:
                    emit(data[seen:])
                    seen = len(data)
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
        if interactive and to_cowork.exists():
            for req_file in sorted(to_cowork.glob("*.json")):
                try:
                    req = json.loads(req_file.read_text())
                except (OSError, json.JSONDecodeError):
                    continue
                if req.get("parent") == cmd_id:
                    req_file.rename(req_file.with_suffix(".json.answered"))
                    return {
                        "state": "awaiting_reply",
                        "cmd_id": cmd_id,
                        "request_id": req.get("id", req_file.stem),
                        "question": req.get("request", ""),
                        "from": req.get("from", "claude-code"),
                        "_deadline": deadline,
                        "_bridge_root": str(root),
                    }
        if result_file.exists():
            try:
                return json.loads(result_file.read_text())
            except json.JSONDecodeError:
                time.sleep(poll_interval)
                continue
        time.sleep(poll_interval)
    raise TimeoutError(
        f"bridge: no result for {cmd_id} — deadline expired while waiting for reply."
    )


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
