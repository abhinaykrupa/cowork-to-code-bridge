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


def call_remote(
    script: str,
    args: list[str | int | float] | None = None,
    timeout: int = 60,
    poll_interval: float = 1.0,
    cwd: str | None = None,
    env: dict[str, str] | None = None,
    bridge_root: Path | str | None = None,
    idempotency_key: str | None = None,
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
) -> dict[str, Any]:
    """Like call_remote, but streams live output while the task runs.

    The daemon tees the script's stdout/stderr to a per-command progress file
    (progress/<id>.log). This polls that file and calls on_progress(new_text)
    for each new chunk as it appears — so long tasks (builds, test runs) show
    progress instead of waiting blind. Returns the same final result dict as
    call_remote once the task completes.

    on_progress: optional callable taking the newly-appended text (str). If
    None, new output is printed to stdout as it arrives.
    """
    root = Path(bridge_root) if bridge_root else _resolve_bridge_root()
    queue = root / "queue"
    results = root / "results"
    progress = root / "progress"
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
    token = _load_token(root)
    if token:
        payload["token"] = token

    cmd_file = queue / f"{cmd_id}.json"
    tmp = cmd_file.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(payload))
    tmp.rename(cmd_file)

    result_file = results / f"{cmd_id}.json"
    progress_file = progress / f"{cmd_id}.log"
    emit = on_progress or (lambda chunk: print(chunk, end="", flush=True))
    seen = 0
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
