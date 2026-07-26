#!/usr/bin/env python3
"""
daemon.py — runs on the user's Mac. Polls bridge/queue/ for command files
written by Cowork (sandbox). Executes whitelisted scripts. Writes results to
bridge/results/.

Security:
  - Only scripts located under SCRIPTS_DIR (relative to BRIDGE_ROOT) are
    executable. No arbitrary shell.
  - Script names must match a strict regex (alphanumerics + `_`, `/`, `.`, `-`,
    ending in .sh or .py). No `..` traversal.
  - Token-authenticated: every command must include the BRIDGE_TOKEN matching
    the daemon's loaded token. Mismatch -> rejected.

Crash resilience (Tier 1 + Tier 2 — see docs/architecture.md):
  - Append-only `journal.log` records received/started/completed/crashed events.
  - `inflight/<id>.running` marker is written before each subprocess and
    deleted after completion. On startup, any marker found means the daemon
    died mid-execution — that command is failed with exit_code=-4 and never
    retried (avoids double-execution of non-idempotent ops like git push).
  - Optional `idempotency_key` on incoming commands: if the journal has a
    cached result for that key, the script is NOT re-run; the cached result
    is returned directly. Lets callers safely retry on TimeoutError.

Configuration (env vars or .env in BRIDGE_ROOT):
  BRIDGE_ROOT       Directory containing queue/, results/, processed/.
                    Default: ~/.cowork-to-code-bridge
  BRIDGE_SCRIPTS    Directory of whitelisted scripts.
                    Default: $BRIDGE_ROOT/scripts
  BRIDGE_TOKEN      Required shared secret. If unset, daemon refuses to start
                    unless BRIDGE_ALLOW_UNAUTH=1 (dev only — NEVER in prod).
  BRIDGE_POLL_SEC   Poll interval in seconds. Default: 1.0
  BRIDGE_MAX_TIMEOUT Max script timeout in seconds (caps user input). Default: 600

Start:
    cowork-to-code-bridge-daemon
    # or
    python3 -m cowork_to_code_bridge.daemon
"""
from __future__ import annotations

import contextlib
import hmac
import json
import os
import re
import signal
import subprocess
import sys
import threading
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

# ─── Configuration ────────────────────────────────────────────────────────────
BRIDGE_ROOT = Path(
    os.environ.get("BRIDGE_ROOT", Path.home() / ".cowork-to-code-bridge")
).expanduser()
SCRIPTS_DIR = Path(os.environ.get("BRIDGE_SCRIPTS", BRIDGE_ROOT / "scripts")).expanduser()
QUEUE = BRIDGE_ROOT / "queue"
RESULTS = BRIDGE_ROOT / "results"
PROCESSED = BRIDGE_ROOT / "processed"
INFLIGHT = BRIDGE_ROOT / "inflight"
PROGRESS = BRIDGE_ROOT / "progress"  # live <id>.log files the client can tail
# Cancellation requests: a caller drops cancel/<id>.json to ask the daemon to
# stop a queued or running task. Polled while a task streams, so a wedged
# 20-minute build can be killed instead of waited out. A file here is a
# *request*, never a result — the daemon is the only writer of results.
CANCEL = BRIDGE_ROOT / "cancel"
# Reverse direction (#34): requests FROM this machine (Claude Code) TO a Cowork
# session. Async inbox — Cowork picks these up when a session is next open.
TO_COWORK = BRIDGE_ROOT / "to_cowork"        # requests Claude Code drops for Cowork
COWORK_RESULTS = BRIDGE_ROOT / "cowork_results"  # replies Cowork writes back
JOURNAL = BRIDGE_ROOT / "journal.log"
POLL_SEC = float(os.environ.get("BRIDGE_POLL_SEC", "1.0"))
MAX_TIMEOUT_SEC = int(os.environ.get("BRIDGE_MAX_TIMEOUT", "600"))
# Owner-set per-task budget ceiling for run_claude.sh calls.
# If set, daemon injects MAX_BUDGET_USD into the script env and run_claude.sh
# passes it to `claude --max-budget-usd`.  The script also reads
# BRIDGE_MAX_BUDGET_USD so the owner ceiling can never be exceeded regardless
# of what the caller sends.
_MAX_BUDGET_USD_STR: str | None = os.environ.get("BRIDGE_MAX_BUDGET_USD") or None
# Owner-set permission-scope ceiling for caller-supplied permission_scope (#47).
# Mirrors the budget ceiling above: the caller may request a per-task scope, but
# it is clamped so it can never grant MORE trust than the owner permits. Ordered
# least→most trust: plan < readonly < edit < full. If unset there is no ceiling
# (a caller may request up to 'full'). An unknown value is treated as no ceiling
# and warned once at startup, so a typo can never silently widen trust.
_SCOPE_RANK = {"plan": 0, "readonly": 1, "edit": 2, "full": 3}
# _ceiling_raw is kept (not just the validated ceiling) so main() can name an
# invalid value in its startup warning. An unrecognized value → no ceiling.
_ceiling_raw = (os.environ.get("BRIDGE_PERMISSION_CEILING") or "").strip().lower()
_PERMISSION_CEILING: str | None = (
    _ceiling_raw if _ceiling_raw in _SCOPE_RANK else None
)
ALLOW_UNAUTH = os.environ.get("BRIDGE_ALLOW_UNAUTH") == "1"
JOURNAL_WARN_BYTES = 10 * 1024 * 1024  # warn at 10 MB
JOURNAL_ROTATE_BYTES = 50 * 1024 * 1024  # rotate at 50 MB (keep one .old)
MAX_CMD_BYTES = 1 * 1024 * 1024  # reject command files larger than 1 MB (DoS guard)

# ─── Output bounds (memory + disk DoS guards) ─────────────────────────────────
# A task's stdout/stderr is capped at MAX_OUTPUT_BYTES in the result file. The
# cap is enforced *while streaming*, not once at the end: a script emitting
# gigabytes would otherwise fill the daemon's RAM before any final clip ran.
# _tee keeps a bounded tail — dropping the oldest chunk as new ones arrive — so
# resident memory stays O(MAX_OUTPUT_BYTES) regardless of how much the child
# writes. When output is dropped, the result carries stdout_truncated /
# stderr_truncated so a caller can tell "64 KiB of output" from "the tail of
# 5 GB" instead of silently reading a clipped stream as complete.
MAX_OUTPUT_BYTES = int(os.environ.get("BRIDGE_MAX_OUTPUT_BYTES", str(64 * 1024)))
# The progress log is a best-effort live view the client tails. It is capped
# separately so an unbounded child can't fill the disk; once over the cap we
# stop appending (keeping the head, which holds the useful start-of-run context).
MAX_PROGRESS_BYTES = int(os.environ.get("BRIDGE_MAX_PROGRESS_BYTES",
                                        str(4 * 1024 * 1024)))

# ─── Cancellation ─────────────────────────────────────────────────────────────
# How often the streaming loop checks for a cancel request, and how long the
# child gets to exit on SIGTERM before SIGKILL. The child is started in its own
# process group so the signal reaches the whole tree — a bare SIGTERM to the
# shell would leave orphaned grandchildren (the `claude` process a script spawned)
# still holding the machine.
CANCEL_POLL_SEC = float(os.environ.get("BRIDGE_CANCEL_POLL_SEC", "0.5"))
CANCEL_GRACE_SEC = float(os.environ.get("BRIDGE_CANCEL_GRACE_SEC", "5.0"))

# Allow only relative paths inside scripts/, ending in .sh or .py.
# Use fullmatch (not match) so the pattern must cover the ENTIRE string —
# re.match only anchors the start, fullmatch anchors both ends.
SAFE_NAME = re.compile(r"scripts/[A-Za-z0-9_/.-]+\.(sh|py)")


def load_env() -> dict[str, str]:
    """Merge process env with .env in BRIDGE_ROOT (process env wins)."""
    env = dict(os.environ)
    env_file = BRIDGE_ROOT / ".env"
    if env_file.exists():
        for line in env_file.read_text().splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, _, v = line.partition("=")
            env.setdefault(k.strip(), v.strip().strip('"').strip("'"))
    return env


def log(msg: str) -> None:
    print(f"[{time.strftime('%Y-%m-%dT%H:%M:%S')}] {msg}", flush=True)


def write_result(cmd_id: str, payload: dict) -> None:
    """Atomic-write a result file."""
    payload.setdefault("id", cmd_id)
    payload.setdefault("ts_completed", time.time())
    out = RESULTS / f"{cmd_id}.json"
    tmp = out.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(payload))
    tmp.rename(out)


# ─── Crash-resilience: journal + in-flight markers ────────────────────────────
#
# State model:
#   journal.log            — append-only jsonl, one event per line, fsync'd.
#                            Events: received, started, completed, crashed_inflight,
#                            idempotency_hit.
#   inflight/<id>.running  — written before subprocess.run, deleted after success.
#                            Presence on startup => the command was mid-execution
#                            when the daemon died.
#
# Recovery on startup:
#   1. Replay journal => {id -> terminal_status} and {idempotency_key -> result}.
#   2. For each inflight/*.running file:
#        - If journal has terminal status for this id, just delete the marker
#          (we crashed after completing but before cleanup).
#        - Else: write exit_code=-4 result, journal crashed_inflight, move the
#          queue file (if still present) to processed. Never re-run.
#   3. For each queue/*.json with terminal status in journal, move to processed
#      (stale leftover from a partial cleanup).


def _journal_append(event: dict) -> None:
    """Append one event to the journal as jsonl. fsync to survive power loss."""
    event = {"ts": time.time(), **event}
    line = json.dumps(event) + "\n"
    # Open in append+binary, write, fsync.
    fd = os.open(str(JOURNAL), os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o600)
    try:
        os.write(fd, line.encode("utf-8"))
        os.fsync(fd)
    finally:
        os.close(fd)


def _journal_replay() -> tuple[dict[str, str], dict[str, dict]]:
    """Read journal.log. Returns (terminal_status_by_id, cached_result_by_idem_key).

    terminal_status_by_id: id -> one of {"completed", "crashed_inflight",
                                          "idempotency_hit"} (terminal events only).
    cached_result_by_idem_key: idempotency_key -> the result dict from the
                               first completion that used that key.
    """
    terminal: dict[str, str] = {}
    cache: dict[str, dict] = {}
    # idem_key per id, harvested from received events, so we can attach the
    # cached result when we later see the corresponding completed event.
    idem_by_id: dict[str, str] = {}
    if not JOURNAL.exists():
        return terminal, cache
    try:
        with JOURNAL.open("r") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    ev = json.loads(line)
                except json.JSONDecodeError:
                    # Tolerate a partial last line from a power-loss crash.
                    continue
                evid = ev.get("id")
                evtype = ev.get("event")
                if not evid or not evtype:
                    continue
                if evtype == "received":
                    k = ev.get("idempotency_key")
                    if k:
                        idem_by_id[evid] = k
                elif evtype == "completed":
                    terminal[evid] = "completed"
                    result = ev.get("result") or {}
                    k = idem_by_id.get(evid)
                    if k and k not in cache:
                        cache[k] = result
                elif evtype == "crashed_inflight":
                    terminal[evid] = "crashed_inflight"
                elif evtype == "idempotency_hit":
                    terminal[evid] = "idempotency_hit"
    except Exception as e:
        log(f"!! journal replay error: {e}")
    return terminal, cache


def _inflight_write(cmd_id: str, cmd_snapshot: dict) -> None:
    """Write the in-flight marker. fsync so it survives a power cut."""
    marker = INFLIGHT / f"{cmd_id}.running"
    payload = {
        "id": cmd_id,
        "pid": os.getpid(),
        "started_ts": time.time(),
        "cmd": cmd_snapshot,
    }
    tmp = marker.with_suffix(".running.tmp")
    data = json.dumps(payload).encode("utf-8")
    fd = os.open(str(tmp), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    try:
        os.write(fd, data)
        os.fsync(fd)
    finally:
        os.close(fd)
    tmp.rename(marker)


def _inflight_clear(cmd_id: str) -> None:
    marker = INFLIGHT / f"{cmd_id}.running"
    marker.unlink(missing_ok=True)


def _recover_inflight(terminal: dict[str, str]) -> None:
    """On startup: convert orphaned in-flight markers into recorded crashes."""
    markers = sorted(INFLIGHT.glob("*.running"))
    if not markers:
        return
    log(f"   recovery: {len(markers)} in-flight marker(s) from previous run")
    for marker in markers:
        cmd_id = marker.stem  # strips ".running"
        if terminal.get(cmd_id) == "completed":
            # We finished but crashed before cleanup. Result file should already
            # exist; just clear the marker and move the queue file if it's still there.
            log(f"   recovery: {cmd_id} already completed, clearing stale marker")
            marker.unlink(missing_ok=True)
            qfile = QUEUE / f"{cmd_id}.json"
            if qfile.exists():
                qfile.rename(PROCESSED / qfile.name)
            continue
        # Genuine crash: command was mid-execution. Fail it; do NOT re-run.
        log(f"   recovery: {cmd_id} crashed mid-execution; marking failed")
        write_result(cmd_id, {
            "exit_code": -4,
            "error": "daemon crashed mid-execution; command status indeterminate, not retried",
        })
        _journal_append({"id": cmd_id, "event": "crashed_inflight"})
        marker.unlink(missing_ok=True)
        qfile = QUEUE / f"{cmd_id}.json"
        if qfile.exists():
            qfile.rename(PROCESSED / qfile.name)


def _drain_stale_queue(terminal: dict[str, str]) -> None:
    """Queue files for ids that already reached terminal status are leftovers."""
    for f in sorted(QUEUE.glob("*.json")):
        if terminal.get(f.stem):
            log(f"   recovery: {f.stem} already terminal in journal, archiving")
            f.rename(PROCESSED / f.name)


class _BoundedTail:
    """Accumulate text but keep only the last `limit` characters.

    Streaming output used to be collected in an unbounded list and clipped once
    at the end (`"".join(buf)[-65536:]`). The clip bounded the *result file* but
    not the daemon's memory: a child emitting gigabytes filled RAM first, and
    the tail arrived only if the process survived to produce it. This keeps the
    same tail semantics (last `limit` chars) with resident size bounded to
    ~2x limit, and records whether anything was dropped.

    Not thread-safe by itself; each stream gets its own instance and only that
    stream's tee thread writes to it.
    """

    __slots__ = ("_chunks", "_size", "_limit", "truncated", "total")

    def __init__(self, limit: int) -> None:
        self._chunks: list[str] = []
        self._size = 0
        self._limit = max(0, limit)
        self.truncated = False
        self.total = 0

    def append(self, text: str) -> None:
        if not text:
            return
        self.total += len(text)
        self._chunks.append(text)
        self._size += len(text)
        # Drop whole chunks from the front while the remainder still covers the
        # limit; then trim the new front chunk so the tail is exactly `limit`.
        while self._chunks and self._size - len(self._chunks[0]) >= self._limit:
            dropped = self._chunks.pop(0)
            self._size -= len(dropped)
            self.truncated = True
        if self._size > self._limit and self._chunks:
            overflow = self._size - self._limit
            self._chunks[0] = self._chunks[0][overflow:]
            self._size -= overflow
            self.truncated = True

    def value(self) -> str:
        return "".join(self._chunks)[-self._limit:] if self._limit else ""


def _output_fields(out_buf: _BoundedTail, err_buf: _BoundedTail) -> dict[str, Any]:
    """Build the stdout/stderr result fields, flagging truncation explicitly.

    `*_truncated` / `*_total_bytes` are only present when output was actually
    dropped, so a normal result keeps its existing shape and old clients see no
    new keys. When they ARE present, the caller can tell a genuinely small
    output from the tail of a huge one rather than reading a clipped stream as
    if it were complete.
    """
    fields: dict[str, Any] = {"stdout": out_buf.value(), "stderr": err_buf.value()}
    if out_buf.truncated:
        fields["stdout_truncated"] = True
        fields["stdout_total_bytes"] = out_buf.total
    if err_buf.truncated:
        fields["stderr_truncated"] = True
        fields["stderr_total_bytes"] = err_buf.total
    return fields


def _read_cancel_request(cmd_id: str) -> str | None:
    """Return the cancel reason if cancel/<id>.json exists, else None.

    A missing or unreadable file means "not cancelled" — cancellation must never
    be inferred from an I/O error, or a transient read failure would kill a
    healthy task. Malformed JSON still counts as a cancel request (the file's
    presence is the signal; the reason is only for reporting).
    """
    req = CANCEL / f"{cmd_id}.json"
    if not req.exists():
        return None
    try:
        data = json.loads(req.read_text())
        reason = data.get("reason")
        return str(reason) if reason else "cancelled by request"
    except (OSError, ValueError):
        return "cancelled by request"


def _clear_cancel_request(cmd_id: str) -> None:
    """Drop a consumed cancel request so a recycled id can't inherit it."""
    with contextlib.suppress(OSError):
        (CANCEL / f"{cmd_id}.json").unlink(missing_ok=True)


def _terminate_tree(proc: subprocess.Popen) -> None:
    """SIGTERM the child's process group, then SIGKILL anything that ignores it.

    Signals the group (not just the pid) because a bundled script typically
    spawns further processes — `claude`, a test runner, a build — and killing
    only the shell would leave those orphaned and still consuming the machine.
    Falls back to killing the single process if the group signal fails (the
    child may have already exited, or set up its own session).
    """
    def _signal_group(sig: int) -> bool:
        try:
            os.killpg(os.getpgid(proc.pid), sig)
            return True
        except (ProcessLookupError, PermissionError, OSError):
            return False

    if not _signal_group(signal.SIGTERM):
        with contextlib.suppress(Exception):
            proc.terminate()
    try:
        proc.wait(timeout=CANCEL_GRACE_SEC)
        return
    except subprocess.TimeoutExpired:
        pass
    # Grace expired — escalate. SIGKILL can't be caught, so this is terminal.
    if not _signal_group(signal.SIGKILL):
        with contextlib.suppress(Exception):
            proc.kill()
    with contextlib.suppress(Exception):
        proc.wait(timeout=CANCEL_GRACE_SEC)


def _run_streaming(argv: list[str], cwd: str, env: dict[str, str],
                   timeout: int, progress_file: Path,
                   status_interval: float = 2.0,
                   cancel_check: Callable[[], str | None] | None = None) -> dict[str, Any]:
    """Run a subprocess, teeing stdout+stderr to progress_file line-by-line.

    Returns the same result dict shape as the old subprocess.run path:
      {exit_code, stdout, stderr} on success/failure,
      {exit_code: -2, error, stdout, stderr} on timeout,
      {exit_code: -3, error} on internal error.

    The progress file is a best-effort live view (the client tails it). The
    authoritative output is the captured stdout/stderr returned here.

    Every ~status_interval seconds a small status JSON is written atomically
    alongside the progress log:
      progress/<id>.status.json → {"elapsed_s": int, "last_line": str, "state": str}
    The client can poll this file for a live ticker without parsing raw log output.
    The status file is written atomically (tmp + rename) so readers never see
    a partial write. It is cleaned up by run_one() after the result is written.
    """
    out_buf = _BoundedTail(MAX_OUTPUT_BYTES)
    err_buf = _BoundedTail(MAX_OUTPUT_BYTES)
    # Shared slot: _tee updates this so the status writer has a recent line.
    last_line: list[str] = [""]
    # Bytes written to the progress log so far, so _tee can stop at the cap.
    progress_bytes = [0]
    progress_capped = [False]

    # Truncate/create the progress file at start.
    with contextlib.suppress(OSError):
        progress_file.write_text("")

    status_file = progress_file.parent / (progress_file.stem + ".status.json")
    start_time = time.monotonic()

    def _write_status_atomic(state: str, exit_code: int | None = None) -> None:
        """Write status JSON atomically; never raises."""
        try:
            payload: dict[str, Any] = {
                "elapsed_s": int(time.monotonic() - start_time),
                "last_line": last_line[0].rstrip(),
                "state": state,
            }
            if exit_code is not None:
                payload["exit_code"] = exit_code
            tmp = status_file.parent / (status_file.name + ".tmp")
            tmp.write_text(json.dumps(payload))
            tmp.rename(status_file)
        except Exception:  # noqa: BLE001
            pass

    def _tee(stream, buf, tag):
        # Read line-by-line; append to the bounded in-memory tail AND the
        # progress file. Both sides are capped: buf drops its oldest content
        # past MAX_OUTPUT_BYTES, and the progress log stops growing past
        # MAX_PROGRESS_BYTES, so a runaway child can exhaust neither RAM nor disk.
        try:
            for line in iter(stream.readline, ""):
                buf.append(line)
                stripped = line.strip()
                if stripped:
                    last_line[0] = stripped
                if progress_bytes[0] >= MAX_PROGRESS_BYTES:
                    if not progress_capped[0]:
                        progress_capped[0] = True
                        with contextlib.suppress(OSError), progress_file.open("a") as pf:
                            pf.write(f"\n[bridge] progress log capped at "
                                     f"{MAX_PROGRESS_BYTES} bytes; "
                                     f"further output omitted from this live view.\n")
                    continue
                text = line if tag == "out" else f"[stderr] {line}"
                progress_bytes[0] += len(text.encode("utf-8", "replace"))
                with contextlib.suppress(OSError), progress_file.open("a") as pf:
                    pf.write(text)
        finally:
            with contextlib.suppress(Exception):
                stream.close()

    try:
        proc = subprocess.Popen(
            argv, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True, cwd=cwd, env=env, bufsize=1,
            # Own process group: cancellation signals the whole tree. A script
            # that spawned `claude` would otherwise survive as an orphan holding
            # the machine after its parent shell took the SIGTERM.
            start_new_session=True,
        )
    except Exception as e:
        return {"exit_code": -3, "error": str(e)}

    t_out = threading.Thread(target=_tee, args=(proc.stdout, out_buf, "out"), daemon=True)
    t_err = threading.Thread(target=_tee, args=(proc.stderr, err_buf, "err"), daemon=True)
    t_out.start()
    t_err.start()

    # Status writer: fires every ~status_interval seconds until _status_stop is set.
    # Using threading.Event.wait(timeout) instead of sleep so the thread wakes up
    # immediately on stop rather than waiting a full interval.
    _status_stop = threading.Event()

    def _write_status_loop() -> None:
        while not _status_stop.wait(timeout=status_interval):
            _write_status_atomic(state="running")

    t_status = threading.Thread(target=_write_status_loop, daemon=True)
    t_status.start()

    def _finish(state: str, payload: dict[str, Any]) -> dict[str, Any]:
        """Shared teardown: reap tees, stop the status writer, write final status."""
        t_out.join(timeout=2)
        t_err.join(timeout=2)
        # Stop status writer before writing the final status so "running" can
        # never overwrite the terminal state.
        _status_stop.set()
        t_status.join(timeout=0.5)
        _write_status_atomic(state=state, exit_code=payload["exit_code"])
        return {**payload, **_output_fields(out_buf, err_buf)}

    # Wait in CANCEL_POLL_SEC slices rather than one blocking wait(timeout), so a
    # cancel request lands within ~half a second instead of after the full task
    # timeout. cancel_check is None when cancellation isn't wired (tests, or a
    # caller that doesn't want it), in which case this degrades to a plain wait.
    deadline = time.monotonic() + timeout
    cancelled_reason: str | None = None
    while True:
        try:
            proc.wait(timeout=CANCEL_POLL_SEC if cancel_check else timeout)
            break
        except subprocess.TimeoutExpired:
            pass
        if cancel_check:
            cancelled_reason = cancel_check()
            if cancelled_reason is not None:
                _terminate_tree(proc)
                return _finish("cancelled", {
                    "exit_code": -5,
                    "error": "cancelled",
                    "cancelled": True,
                    "cancel_reason": cancelled_reason,
                })
        if time.monotonic() >= deadline:
            _terminate_tree(proc)
            return _finish("error", {
                "exit_code": -2,
                "error": f"timeout after {timeout}s",
            })

    final_state = "done" if proc.returncode == 0 else "error"
    return _finish(final_state, {"exit_code": proc.returncode})


def run_one(cmd_path: Path, token_required: str | None,
            terminal: dict[str, str], idem_cache: dict[str, dict]) -> None:
    cmd_id = cmd_path.stem
    # Size guard: refuse to slurp an oversized command file into memory.
    try:
        if cmd_path.stat().st_size > MAX_CMD_BYTES:
            write_result(cmd_id, {"exit_code": -1,
                                  "error": f"command file too large (> {MAX_CMD_BYTES} bytes)"})
            log(f"  ✗ {cmd_id}: oversized command file, rejected")
            cmd_path.rename(PROCESSED / cmd_path.name)
            return
    except OSError:
        cmd_path.unlink(missing_ok=True)
        return
    try:
        cmd = json.loads(cmd_path.read_text())
    except Exception as e:
        log(f"  ! bad json in {cmd_path.name}: {e}")
        cmd_path.unlink(missing_ok=True)
        return

    # ─── auth (constant-time compare to avoid token timing leaks) ──────────────
    if token_required:
        supplied = cmd.get("token")
        if not isinstance(supplied, str) or not hmac.compare_digest(supplied, token_required):
            write_result(cmd_id, {"exit_code": -1, "error": "bridge token mismatch"})
            log(f"  ✗ {cmd_id}: token mismatch")
            cmd_path.rename(PROCESSED / cmd_path.name)
            return

    # ─── journal: received ────────────────────────────────────────────────────
    idem_key = cmd.get("idempotency_key")
    _journal_append({
        "id": cmd_id,
        "event": "received",
        "idempotency_key": idem_key,
        "script": cmd.get("script"),
    })

    # ─── idempotency short-circuit ────────────────────────────────────────────
    if idem_key and idem_key in idem_cache:
        cached = dict(idem_cache[idem_key])
        cached.setdefault("idempotent_replay", True)
        write_result(cmd_id, cached)
        _journal_append({"id": cmd_id, "event": "idempotency_hit", "key": idem_key})
        terminal[cmd_id] = "idempotency_hit"
        log(f"  ↺ {cmd_id}: idempotency hit on key={idem_key!r}; returning cached result")
        cmd_path.rename(PROCESSED / cmd_path.name)
        return

    # ─── plan approval gate ───────────────────────────────────────────────────
    # If (a) the command includes a "plan" field AND (b) scripts/approve_plan.sh
    # exists, run the hook synchronously with the plan text on stdin before
    # touching the main script. Exit 0 = proceed. Exit 2 = reject (hook's
    # stderr is returned to Cowork as the error message). Any other exit code
    # is treated as an internal error and also blocks execution.
    # If approve_plan.sh is absent the plan field is silently ignored.
    plan_text = cmd.get("plan")
    approve_hook = SCRIPTS_DIR / "approve_plan.sh"
    if plan_text and approve_hook.exists():
        log(f"  ⧖ {cmd_id}: running approve_plan.sh hook")
        try:
            hook_result = subprocess.run(
                ["bash", str(approve_hook)],
                input=str(plan_text),
                capture_output=True,
                text=True,
                timeout=30,
            )
        except subprocess.TimeoutExpired:
            write_result(cmd_id, {
                "exit_code": -1,
                "error": "approve_plan.sh timed out after 30s",
            })
            log(f"  ✗ {cmd_id}: approve_plan.sh timed out")
            cmd_path.rename(PROCESSED / cmd_path.name)
            return
        except Exception as e:
            write_result(cmd_id, {"exit_code": -1, "error": f"approve_plan.sh error: {e}"})
            log(f"  ✗ {cmd_id}: approve_plan.sh failed to run: {e}")
            cmd_path.rename(PROCESSED / cmd_path.name)
            return

        if hook_result.returncode != 0:
            _fallback = "plan rejected by approve_plan.sh"
            rejection = (hook_result.stderr or hook_result.stdout or _fallback).strip()
            write_result(cmd_id, {
                "exit_code": -1,
                "error": f"plan rejected: {rejection}",
                "plan_rejected": True,
            })
            _rc = hook_result.returncode
            log(f"  ✗ {cmd_id}: plan rejected by hook (exit {_rc}): {rejection[:120]}")
            cmd_path.rename(PROCESSED / cmd_path.name)
            return
        log(f"  ✓ {cmd_id}: plan approved by hook")

    # ─── validate script path ─────────────────────────────────────────────────
    script = cmd.get("script", "")
    if not SAFE_NAME.fullmatch(script):
        write_result(cmd_id, {"exit_code": -1, "error": f"script path not allowed: {script!r}"})
        log(f"  ✗ {cmd_id}: bad script path {script!r}")
        cmd_path.rename(PROCESSED / cmd_path.name)
        return

    # SAFE_NAME guarantees "scripts/..." — strip and join under SCRIPTS_DIR.
    script_rel = script[len("scripts/"):]
    script_full = (SCRIPTS_DIR / script_rel).resolve()
    # Defence-in-depth: ensure the resolved path is still under SCRIPTS_DIR
    # (in case symlinks or weird input slipped past the regex).
    try:
        script_full.relative_to(SCRIPTS_DIR.resolve())
    except ValueError:
        write_result(cmd_id, {"exit_code": -1, "error": f"script escapes scripts dir: {script!r}"})
        log(f"  ✗ {cmd_id}: path escape {script!r}")
        cmd_path.rename(PROCESSED / cmd_path.name)
        return

    if not script_full.exists():
        write_result(cmd_id, {"exit_code": -1, "error": f"script does not exist: {script}"})
        log(f"  ✗ {cmd_id}: script not found {script}")
        cmd_path.rename(PROCESSED / cmd_path.name)
        return

    # ─── validate args ────────────────────────────────────────────────────────
    args = cmd.get("args", [])
    if not isinstance(args, list) or not all(isinstance(a, (str, int, float)) for a in args):
        write_result(cmd_id, {"exit_code": -1, "error": "args must be a list of strings/numbers"})
        cmd_path.rename(PROCESSED / cmd_path.name)
        return

    # ─── build cmdline ────────────────────────────────────────────────────────
    if script.endswith(".sh"):
        argv = ["bash", str(script_full), *map(str, args)]
    else:  # .py
        argv = [sys.executable, str(script_full), *map(str, args)]

    timeout = min(int(cmd.get("timeout", 60)), MAX_TIMEOUT_SEC)
    cwd = cmd.get("cwd", str(BRIDGE_ROOT))
    extra_env = cmd.get("env", {}) or {}

    log(f"  → {cmd_id}: {script} {args}")
    env = load_env()
    # Security: daemon (owner) env vars take priority over caller-supplied env.
    # This prevents a caller with the bridge token from overriding security-critical
    # vars like CLAUDE_FLAGS that the owner set in launchd/systemd to restrict
    # what Claude Code can do. Caller can only SET vars not already in daemon env.
    for k, v in extra_env.items():
        k = str(k)
        if k not in env:          # owner var wins; caller can only add new ones
            env[k] = str(v)
        elif k.upper() in ("CLAUDE_FLAGS", "BRIDGE_TOKEN", "BRIDGE_ROOT",
                           "BRIDGE_ALLOW_UNAUTH", "BRIDGE_MAX_TIMEOUT",
                           "BRIDGE_MAX_BUDGET_USD", "BRIDGE_CMD_ID"):
            log(f"  ! blocked caller attempt to override protected env var: {k}")
        else:
            env[k] = str(v)       # non-security vars: caller wins (e.g. PYTHONPATH)

    # ── Task correlation id injection (issue #72) ─────────────────────────────
    # Inject BRIDGE_CMD_ID so a script that calls request_cowork.sh mid-task can
    # stamp the request with its parent task id. request_cowork.sh reads this and
    # writes it as the "parent" field of the request JSON, letting the Cowork
    # client's interactive poll loop correlate a mid-task question back to the
    # running task. Set AFTER the caller-env merge (and listed in the protected
    # vars above) so a caller with the bridge token can't spoof another task's id.
    env["BRIDGE_CMD_ID"] = cmd_id

    # ── Budget cap injection ──────────────────────────────────────────────────
    # Inject MAX_BUDGET_USD from the command payload into the script environment
    # so run_claude.sh can forward it to `claude --max-budget-usd`.
    # The owner ceiling (BRIDGE_MAX_BUDGET_USD) is also forwarded so run_claude.sh
    # can apply min(caller, owner) itself — this gives the script full context.
    # MAX_BUDGET_USD from the caller is validated to be a positive float; invalid
    # values are ignored (logged) so a bad payload can't crash the daemon.
    caller_budget_raw = cmd.get("max_budget_usd")
    if caller_budget_raw is not None:
        try:
            caller_budget = float(caller_budget_raw)
            if caller_budget <= 0:
                raise ValueError("must be positive")
            env["MAX_BUDGET_USD"] = f"{caller_budget:.4f}"
        except (TypeError, ValueError) as exc:
            log(f"  ! ignoring invalid max_budget_usd={caller_budget_raw!r}: {exc}")
    if _MAX_BUDGET_USD_STR:
        # Always forward the owner ceiling so run_claude.sh can enforce it.
        env["BRIDGE_MAX_BUDGET_USD"] = _MAX_BUDGET_USD_STR

    # ── Model tier injection ──────────────────────────────────────────────────
    # Inject CLAUDE_MODEL_TIER from the command payload so run_claude.sh can map
    # it to a concrete `--model` ID. The tier is validated against the router's
    # canonical set; an unknown tier is ignored (logged) so a bad payload falls
    # back to the CLI default rather than crashing the daemon or dispatching to a
    # garbage model name. An owner-set CLAUDE_MODEL_TIER in the daemon env always
    # wins (same precedence as CLAUDE_FLAGS) — the caller can't override it.
    tier_raw = cmd.get("model_tier")
    if tier_raw is not None:
        if "CLAUDE_MODEL_TIER" in env:
            log("  ! ignoring caller model_tier: owner CLAUDE_MODEL_TIER is set")
        else:
            tier_norm = str(tier_raw).strip().lower()
            if tier_norm in {"haiku", "sonnet", "opus", "fable"}:
                env["CLAUDE_MODEL_TIER"] = tier_norm
            else:
                log(f"  ! ignoring invalid model_tier={tier_raw!r}")

    # ── Effort injection (issue #33) ──────────────────────────────────────────
    # Inject CLAUDE_EFFORT from the command payload so run_claude.sh can pass the
    # claude CLI's `--effort <low|medium|high|xhigh|max>` flag. Parallel to model
    # tier: the effort is validated against the CLI's fixed set; an unknown value
    # is ignored (logged) so a bad payload falls back to the CLI default rather
    # than dispatching a garbage flag. An owner-set CLAUDE_EFFORT in the daemon
    # env always wins (same precedence as model tier and CLAUDE_FLAGS) — the
    # caller can't override it.
    effort_raw = cmd.get("effort")
    if effort_raw is not None:
        if "CLAUDE_EFFORT" in env:
            log("  ! ignoring caller effort: owner CLAUDE_EFFORT is set")
        else:
            effort_norm = str(effort_raw).strip().lower()
            if effort_norm in {"low", "medium", "high", "xhigh", "max"}:
                env["CLAUDE_EFFORT"] = effort_norm
            else:
                log(f"  ! ignoring invalid effort={effort_raw!r}")

    # ── Per-task permission scope injection (issue #47) ───────────────────────
    # Inject CLAUDE_FLAGS from a caller-supplied permission_scope so a single task
    # can be sandboxed (plan/readonly/edit) without the owner having to set a
    # global CLAUDE_FLAGS. The caller picks from a fixed safe allowlist of named
    # scopes (NOT arbitrary flags) — the scope is resolved to a vetted flag set by
    # the router, so the bridge token can never be used to widen trust to full
    # shell. An owner-set CLAUDE_FLAGS in the daemon env always wins (same
    # precedence as model tier and budget); an unknown scope is ignored (logged).
    scope_raw = cmd.get("permission_scope")
    if scope_raw is not None:
        if "CLAUDE_FLAGS" in env:
            log("  ! ignoring caller permission_scope: owner CLAUDE_FLAGS is set")
        else:
            scope_norm = str(scope_raw).strip().lower()
            # Canonical scope → CLAUDE_FLAGS. Kept in sync with model_router.py's
            # SCOPE_TO_FLAGS and run_claude.sh's scope_to_flags(); inlined here so
            # the daemon stays import-free for dispatch (same style as model_tier).
            # 'full' maps to no flags — leave CLAUDE_FLAGS unset so the CLI default
            # applies rather than widening trust.
            scope_flags = {
                "plan": "--permission-mode plan",
                "readonly": "--allowedTools Read,Glob,Grep",
                "edit": "--allowedTools Read,Glob,Grep,Edit,Write",
                "full": "",
            }
            if scope_norm in scope_flags:
                # Clamp against the owner's ceiling (BRIDGE_PERMISSION_CEILING).
                # The caller can request a scope but can never exceed the owner's
                # cap — e.g. owner sets ceiling='edit' and a task asks for 'full',
                # it is clamped down to 'edit'. This is the missing enforcement
                # behind #47/#75: without it, any caller with the bridge token
                # could request 'full' and bypass sandboxing entirely.
                if (
                    _PERMISSION_CEILING is not None
                    and _SCOPE_RANK[scope_norm] > _SCOPE_RANK[_PERMISSION_CEILING]
                ):
                    log(
                        f"  ! clamping permission scope {scope_norm!r} → "
                        f"{_PERMISSION_CEILING!r} (owner ceiling)"
                    )
                    scope_norm = _PERMISSION_CEILING
                flags = scope_flags[scope_norm]
                if flags:
                    env["CLAUDE_FLAGS"] = flags
                    log(f"  permission scope {scope_norm!r} → CLAUDE_FLAGS={flags}")
            else:
                log(f"  ! ignoring invalid permission_scope={scope_raw!r}")

    # ─── cancelled while queued? ──────────────────────────────────────────────
    # Checked after validation but BEFORE the in-flight marker and any execution,
    # so a task cancelled while it sat in the queue never runs at all. This is
    # the cheap, fully-safe case: nothing has side-effected yet.
    _queued_cancel = _read_cancel_request(cmd_id)
    if _queued_cancel is not None:
        write_result(cmd_id, {
            "exit_code": -5,
            "error": "cancelled",
            "cancelled": True,
            "cancel_reason": _queued_cancel,
            "stdout": "",
            "stderr": "",
        })
        _journal_append({"id": cmd_id, "event": "completed",
                         "result": {"exit_code": -5, "cancelled": True}})
        terminal[cmd_id] = "completed"
        _clear_cancel_request(cmd_id)
        log(f"  ⨯ {cmd_id}: cancelled before execution ({_queued_cancel})")
        cmd_path.rename(PROCESSED / cmd_path.name)
        return

    # ─── in-flight marker + journal: started ──────────────────────────────────
    # Marker is written BEFORE subprocess.run. If we crash between this point
    # and the post-run cleanup, recovery on next startup will see the marker,
    # write exit_code=-4, and refuse to re-run. This is the crash-safety
    # guarantee for Tier 1.
    _inflight_write(cmd_id, {
        "script": script, "args": args, "timeout": timeout,
        "idempotency_key": idem_key,
    })
    _journal_append({"id": cmd_id, "event": "started", "pid": os.getpid()})

    # Stream output to a live progress file so the client can show progress
    # while long tasks (builds, test runs) are still running, instead of waiting
    # blind for the final result. The progress file is best-effort and append-
    # only; the authoritative result is still the result JSON written below.
    progress_file = PROGRESS / f"{cmd_id}.log"
    result = _run_streaming(argv, cwd, env, timeout, progress_file,
                            cancel_check=lambda: _read_cancel_request(cmd_id))
    if result.get("cancelled"):
        log(f"  ⨯ {cmd_id}: cancelled ({result.get('cancel_reason')})")
    # The request has been honoured (or the task finished first) — clear it either
    # way so a stale file can't cancel an unrelated future task.
    _clear_cancel_request(cmd_id)

    # Order matters: result file first (durable), then journal completed (so
    # recovery sees terminal status), then clear in-flight marker, then move
    # queue file. Each step is recoverable from the next startup.
    write_result(cmd_id, result)
    _journal_append({"id": cmd_id, "event": "completed", "result": result})
    terminal[cmd_id] = "completed"
    if idem_key:
        idem_cache.setdefault(idem_key, result)
    _inflight_clear(cmd_id)
    # The result file is now authoritative; drop the live progress + status files.
    (PROGRESS / f"{cmd_id}.log").unlink(missing_ok=True)
    (PROGRESS / f"{cmd_id}.status.json").unlink(missing_ok=True)
    cmd_path.rename(PROCESSED / cmd_path.name)
    log(f"  ✓ {cmd_id}: exit={result['exit_code']}")


def main() -> int:
    for d in (BRIDGE_ROOT, QUEUE, RESULTS, PROCESSED, INFLIGHT, PROGRESS, CANCEL,
              TO_COWORK, COWORK_RESULTS, SCRIPTS_DIR):
        d.mkdir(parents=True, exist_ok=True)

    # Harden directory perms: only the owner should be able to read the token,
    # write into the queue, or drop scripts. World/group-writable here would let
    # any local user inject commands or scripts. to_cowork/ + cowork_results/ are
    # included because their request/reply files can carry the bridge token.
    # CANCEL is included: dropping a file there stops a running task, so a
    # world-writable cancel/ would let any local user kill the owner's work.
    for d in (BRIDGE_ROOT, QUEUE, SCRIPTS_DIR, CANCEL, TO_COWORK, COWORK_RESULTS):
        try:
            mode = d.stat().st_mode & 0o777
            if mode & 0o077:  # any group/other bits set
                os.chmod(d, 0o700)
                log(f"   tightened perms on {d} (was {oct(mode)} → 0o700)")
        except OSError:
            pass

    env = load_env()
    token = env.get("BRIDGE_TOKEN") or None
    if not token:
        if not ALLOW_UNAUTH:
            log("!! BRIDGE_TOKEN not set and BRIDGE_ALLOW_UNAUTH != 1 — refusing to start.")
            log("   Either set BRIDGE_TOKEN in env or in $BRIDGE_ROOT/.env, or set")
            log("   BRIDGE_ALLOW_UNAUTH=1 for local dev (NEVER for shared machines).")
            return 1
        log("!! BRIDGE_TOKEN not set, BRIDGE_ALLOW_UNAUTH=1 — accepting unauthenticated commands.")
    else:
        log(f"   bridge token loaded (len={len(token)}, prefix={token[:6]}…)")

    log(f"   BRIDGE_ROOT  = {BRIDGE_ROOT}")
    log(f"   SCRIPTS_DIR  = {SCRIPTS_DIR}")

    # ─── crash recovery ───────────────────────────────────────────────────────
    terminal, idem_cache = _journal_replay()
    if terminal or idem_cache:
        log(f"   journal: {len(terminal)} terminal record(s), "
            f"{len(idem_cache)} idempotency key(s) cached")
    _recover_inflight(terminal)
    _drain_stale_queue(terminal)

    # Journal hygiene: rotate when very large (keep one .old), else warn.
    # Rotation happens AFTER replay above, so the in-memory idempotency cache and
    # terminal state for this run are already loaded from the full history.
    try:
        if JOURNAL.exists():
            size = JOURNAL.stat().st_size
            if size > JOURNAL_ROTATE_BYTES:
                old = JOURNAL.with_suffix(".log.old")
                old.unlink(missing_ok=True)
                JOURNAL.rename(old)
                log(f"   rotated journal.log ({size // 1024 // 1024} MB) → {old.name}")
            elif size > JOURNAL_WARN_BYTES:
                log(f"!! journal.log is {size // 1024} KB — will auto-rotate at "
                    f"{JOURNAL_ROTATE_BYTES // 1024 // 1024} MB.")
    except OSError:
        pass

    log(f"daemon up — polling {QUEUE} every {POLL_SEC}s. ctrl+c to stop.")
    if _PERMISSION_CEILING is not None:
        log(f"permission ceiling: caller scope clamped to {_PERMISSION_CEILING!r} max")
    elif _ceiling_raw:
        # Set but unrecognized — warn loudly; no ceiling is enforced (fail-open
        # on the value, but the caller scope allowlist still bounds trust).
        log(f"! ignoring invalid BRIDGE_PERMISSION_CEILING={_ceiling_raw!r} (no ceiling)")

    stop = False

    def sigint(*_a):
        nonlocal stop
        stop = True
        log("stop requested — finishing current cycle…")

    signal.signal(signal.SIGINT, sigint)
    signal.signal(signal.SIGTERM, sigint)

    while not stop:
        try:
            files = sorted(QUEUE.glob("*.json"))
            for f in files:
                run_one(f, token, terminal, idem_cache)
        except Exception as e:
            log(f"! daemon loop error: {e}")
        time.sleep(POLL_SEC)

    log("daemon exiting")
    return 0


if __name__ == "__main__":
    sys.exit(main())
