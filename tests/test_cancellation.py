"""
Comprehensive cancellation-semantics tests for the bridge.

These tests cover the full lifecycle of cancelling an operation, across the
two layers that participate in cancellation:

  1. The MCP ``cancel_operation`` tool (mcp_server.py) — a *cooperative,
     file-based* state machine. Depending on where the operation is in its
     lifecycle, cancelling either deletes the queued request, marks an
     in-flight operation for cancellation, or no-ops a completed one.
  2. The daemon process (daemon.py) — which owns the real subprocess. The
     daemon handles SIGTERM by finishing its current cycle and shutting down
     gracefully, and enforces a per-command ``timeout`` by killing runaway
     subprocesses.

HONEST NOTE ABOUT THE IMPLEMENTATION (read before trusting the message strings):
``cancel_operation`` on an in-progress op writes ``cancelled = true`` into the
operation's state file and returns a message saying "SIGTERM sent to process".
As of this writing the tool does NOT actually send a signal — the daemon does
not yet read the ``operations/`` cancel flag. So the in-progress branch is a
*signal of intent* (cooperative flag), not real preemption. These tests assert
what the code genuinely does (writes the flag) rather than the aspirational
message, so they stay green and don't lie about behaviour. The real,
process-level termination that DOES work today is the daemon's SIGTERM-driven
graceful shutdown and its per-command timeout kill — both covered here with
real long-running subprocesses, not mocks.
"""
import contextlib
import json
import os
import signal
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import pytest

from cowork_to_code_bridge.mcp_server import MCPServer

REPO_ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture
def bridge_root():
    """A throwaway bridge directory with the full directory layout the
    MCP server and daemon expect."""
    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir) / "bridge"
        for sub in (
            "queue",
            "results",
            "processed",
            "inflight",
            "progress",
            "scripts",
            "to_cowork",
            "cowork_results",
            "operations",
        ):
            (root / sub).mkdir(parents=True, exist_ok=True)
        yield root


@pytest.fixture
def mcp_server(bridge_root):
    """MCP server bound to the throwaway bridge root."""
    return MCPServer(bridge_root=bridge_root)


def _cancel(mcp_server, operation_id, reason="test cancel"):
    """Invoke the cancel_operation tool and return the unwrapped result dict."""
    resp = mcp_server.handle_request(
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {
                "name": "cancel_operation",
                "arguments": {"operation_id": operation_id, "reason": reason},
            },
        }
    )
    assert "result" in resp, f"expected result, got: {resp}"
    return resp["result"]


# ─────────────────────────────────────────────────────────────────────────────
# 1. PRE-EXECUTION CANCELLATION
# ─────────────────────────────────────────────────────────────────────────────
def test_pre_execution_cancellation_removes_queued_request(mcp_server, bridge_root):
    """Pre-execution cancel: the request is still sitting in the ``to_cowork``
    inbox and has not been picked up.

    Expected: the tool deletes the queued request file so the daemon/agent
    never starts work on it (no subprocess, no SIGTERM needed — the task is
    simply skipped), and reports status ``cancelled``.
    """
    op_id = "op_preexec_001"
    request_file = bridge_root / "to_cowork" / f"{op_id}.json"
    request_file.write_text(json.dumps({"id": op_id, "request": "long task"}))

    assert request_file.exists()

    result = _cancel(mcp_server, op_id, reason="changed my mind")

    assert result["status"] == "cancelled"
    assert result["reason"] == "changed my mind"
    # The queued request must be gone so it can never be executed.
    assert not request_file.exists(), "queued request should be deleted on pre-exec cancel"


# ─────────────────────────────────────────────────────────────────────────────
# 2. DURING-EXECUTION CANCELLATION
#    Two parts:
#      2a. The MCP tool's in-progress branch (cooperative flag).
#      2b. The daemon's REAL graceful shutdown on SIGTERM, with a real
#          long-running subprocess.
# ─────────────────────────────────────────────────────────────────────────────
def test_during_execution_cancel_marks_operation_state(mcp_server, bridge_root):
    """During-execution cancel (MCP layer): the request has left the queue and
    an operation state file exists in ``operations/`` — i.e. it is in flight.

    Expected: the tool marks the operation state with ``cancelled = true`` plus
    a reason/timestamp and returns status ``cancelling``. This is the
    cooperative cancellation signal; see the module docstring for why this is a
    flag and not a real SIGTERM today.
    """
    op_id = "op_inflight_002"
    op_file = bridge_root / "operations" / f"{op_id}.json"
    op_file.write_text(
        json.dumps(
            {
                "operation_id": op_id,
                "status": "executing",
                "created_at": time.time(),
            }
        )
    )
    # Crucially: NO queued request and NO result — so the tool falls through to
    # the in-progress branch rather than the pre-exec or post-exec branches.
    assert not (bridge_root / "to_cowork" / f"{op_id}.json").exists()
    assert not (bridge_root / "cowork_results" / f"{op_id}.json").exists()

    result = _cancel(mcp_server, op_id, reason="user aborted")

    assert result["status"] == "cancelling"
    assert result["reason"] == "user aborted"

    persisted = json.loads(op_file.read_text())
    assert persisted["cancelled"] is True
    assert persisted["cancel_reason"] == "user aborted"
    assert "cancelled_at" in persisted


def test_during_execution_daemon_graceful_shutdown_on_sigterm(bridge_root):
    """During-execution cancel (daemon layer, REAL subprocess): start the actual
    daemon against a temp bridge root, give it a script that is busy executing,
    let it begin, then send the daemon SIGTERM.

    This pins down the daemon's ACTUAL cancellation semantics, which are
    "graceful" in the cooperative sense, NOT preemptive:

      * The SIGTERM handler sets a ``stop`` flag and logs "stop requested —
        finishing current cycle…".
      * The daemon runs commands synchronously inside ``run_one`` → ``proc.wait``.
        It does NOT interrupt the in-flight subprocess; it lets the current
        command finish, then the poll loop sees ``stop`` and exits cleanly (0).

    So the contract this test enforces: SIGTERM during execution → daemon
    finishes the current command, then shuts down gracefully with exit 0. We use
    a short (3s) child so "finish the current cycle then exit" completes inside
    the assertion window — a 60s child would make the daemon block for the full
    60s, which is the same behaviour, just slower. No mocks: a real ``python``
    daemon subprocess and a real ``sleep`` child.
    """
    # A real, briefly-running script the daemon will execute synchronously.
    long_script = bridge_root / "scripts" / "long_sleep.sh"
    long_script.write_text("#!/bin/bash\necho started\nsleep 3\necho done\n")
    long_script.chmod(0o755)

    env = dict(os.environ)
    env.pop("BRIDGE_TOKEN", None)  # run unauthenticated so the test can queue freely
    env["BRIDGE_ROOT"] = str(bridge_root)
    env["BRIDGE_ALLOW_UNAUTH"] = "1"  # no token, so we can queue freely
    env["BRIDGE_POLL_SEC"] = "0.2"
    env["PYTHONPATH"] = str(REPO_ROOT) + os.pathsep + env.get("PYTHONPATH", "")

    daemon = subprocess.Popen(
        [sys.executable, "-m", "cowork_to_code_bridge.daemon"],
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        # Own process group so we can be sure we signal only the daemon.
        start_new_session=True,
    )
    try:
        # Queue a long-running command for the daemon to pick up.
        cmd_id = "cmd_longsleep"
        cmd = {"id": cmd_id, "script": "scripts/long_sleep.sh", "timeout": 30}
        queue = bridge_root / "queue"
        tmp = queue / f"{cmd_id}.json.tmp"
        tmp.write_text(json.dumps(cmd))
        tmp.rename(queue / f"{cmd_id}.json")

        # Wait until the daemon has actually started the subprocess. The daemon
        # writes a live progress log per command id; the script echoes "started".
        progress_log = bridge_root / "progress" / f"{cmd_id}.log"
        deadline = time.time() + 20
        started = False
        while time.time() < deadline:
            if progress_log.exists() and "started" in progress_log.read_text():
                started = True
                break
            if daemon.poll() is not None:
                pytest.fail("daemon exited before it began executing the command")
            time.sleep(0.1)
        assert started, "daemon never began executing the long-running subprocess"

        # Now cancel by signalling the daemon — the real shutdown path.
        daemon.send_signal(signal.SIGTERM)

        # Daemon should shut down gracefully: finish the in-flight 3s command,
        # then the poll loop sees the stop flag and returns. Generous slack.
        try:
            rc = daemon.wait(timeout=20)
        except subprocess.TimeoutExpired:
            pytest.fail("daemon did not shut down within 20s of SIGTERM (not graceful)")

        # Graceful shutdown: the handler logged the stop request and the daemon
        # returned a clean exit (0) rather than dying on an unhandled signal.
        output = daemon.stdout.read() if daemon.stdout else ""
        assert "stop requested" in output, (
            f"expected graceful stop log; daemon output:\n{output}"
        )
        assert rc == 0, f"expected clean exit 0 on SIGTERM, got {rc}"
    finally:
        if daemon.poll() is None:
            # Make sure nothing is left running if an assertion failed mid-test.
            with contextlib.suppress(ProcessLookupError, PermissionError):
                os.killpg(os.getpgid(daemon.pid), signal.SIGKILL)
            daemon.wait(timeout=5)


# ─────────────────────────────────────────────────────────────────────────────
# 3. POST-EXECUTION CANCELLATION (idempotent no-op)
# ─────────────────────────────────────────────────────────────────────────────
def test_post_execution_cancel_is_noop(mcp_server, bridge_root):
    """Post-execution cancel: a result already exists in ``cowork_results``, so
    the operation has completed.

    Expected: cancellation is a no-op — the tool reports ``completed`` and does
    NOT delete or mutate the finished result.
    """
    op_id = "op_done_003"
    result_file = bridge_root / "cowork_results" / f"{op_id}.json"
    payload = {"id": op_id, "result": "all done"}
    result_file.write_text(json.dumps(payload))

    result = _cancel(mcp_server, op_id)

    assert result["status"] == "completed"
    assert "no-op" in result["message"].lower()
    # The finished result must be untouched.
    assert result_file.exists()
    assert json.loads(result_file.read_text()) == payload


def test_post_execution_cancel_is_idempotent(mcp_server, bridge_root):
    """Cancelling an already-completed operation repeatedly must be idempotent:
    every call returns the same ``completed`` no-op and never errors or mutates
    the result, no matter how many times it is invoked.
    """
    op_id = "op_done_004"
    result_file = bridge_root / "cowork_results" / f"{op_id}.json"
    result_file.write_text(json.dumps({"id": op_id, "result": "x"}))

    first = _cancel(mcp_server, op_id)
    second = _cancel(mcp_server, op_id)
    third = _cancel(mcp_server, op_id)

    for r in (first, second, third):
        assert r["status"] == "completed"
    assert result_file.exists()


def test_cancel_unknown_operation_is_safe_noop(mcp_server):
    """Cancelling an operation id that the bridge has never seen must not raise
    and must report ``unknown`` rather than fabricating a cancellation."""
    result = _cancel(mcp_server, "op_never_existed_999")
    assert result["status"] == "unknown"
    assert "nothing to cancel" in result["message"].lower()


# ─────────────────────────────────────────────────────────────────────────────
# 4. TIMEOUT BEHAVIOUR ON CANCELLATION
#    The per-command timeout is the daemon's hard backstop: a runaway subprocess
#    is killed and reported as a timeout error. This is "cancellation by
#    deadline", tested with a real long-running subprocess.
# ─────────────────────────────────────────────────────────────────────────────
def test_timeout_kills_runaway_subprocess(bridge_root):
    """Timeout-driven cancellation (daemon layer, REAL subprocess): queue a
    command whose script sleeps far longer than its per-command ``timeout``.

    Expected: the daemon kills the runaway child when the deadline passes and
    writes a result with ``exit_code == -2`` and a timeout error — i.e. the
    operation is cancelled by deadline rather than running forever.
    """
    runaway = bridge_root / "scripts" / "runaway.sh"
    runaway.write_text("#!/bin/bash\necho running\nsleep 30\n")
    runaway.chmod(0o755)

    env = dict(os.environ)
    env.pop("BRIDGE_TOKEN", None)  # run unauthenticated so the test can queue freely
    env["BRIDGE_ROOT"] = str(bridge_root)
    env["BRIDGE_ALLOW_UNAUTH"] = "1"
    env["BRIDGE_POLL_SEC"] = "0.2"
    env["PYTHONPATH"] = str(REPO_ROOT) + os.pathsep + env.get("PYTHONPATH", "")

    daemon = subprocess.Popen(
        [sys.executable, "-m", "cowork_to_code_bridge.daemon"],
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        start_new_session=True,
    )
    try:
        cmd_id = "cmd_runaway"
        # timeout=2s, but the script sleeps 30s → daemon must kill it.
        cmd = {"id": cmd_id, "script": "scripts/runaway.sh", "timeout": 2}
        queue = bridge_root / "queue"
        tmp = queue / f"{cmd_id}.json.tmp"
        tmp.write_text(json.dumps(cmd))
        tmp.rename(queue / f"{cmd_id}.json")

        # Wait for the daemon to write the (timeout) result file.
        result_file = bridge_root / "results" / f"{cmd_id}.json"
        deadline = time.time() + 30
        while time.time() < deadline and not result_file.exists():
            if daemon.poll() is not None:
                pytest.fail("daemon exited before writing a timeout result")
            time.sleep(0.2)

        assert result_file.exists(), "daemon never produced a result for the runaway command"
        result = json.loads(result_file.read_text())
        assert result["exit_code"] == -2, f"expected timeout exit -2, got {result}"
        assert "timeout" in json.dumps(result).lower()
    finally:
        if daemon.poll() is None:
            daemon.send_signal(signal.SIGTERM)
            try:
                daemon.wait(timeout=10)
            except subprocess.TimeoutExpired:
                os.killpg(os.getpgid(daemon.pid), signal.SIGKILL)
                daemon.wait(timeout=5)
