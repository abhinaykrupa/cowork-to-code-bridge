"""Real task cancellation — SIGTERM the process tree, not just a flag.

Before this, `cancel_operation` stamped `cancelled=True` onto
`operations/<id>.json` — a file no component ever read — and told the caller
"SIGTERM sent to process". Nothing was sent and nothing stopped. Reporting a kill
that did not happen is worse than reporting none, because the caller stops
watching a task that is still running and still spending budget. The old test
asserted the word "SIGTERM" appeared in the response *message*, which is how the
gap survived review.

These tests exercise the real path: a cancel request file, a daemon that polls it
while streaming, a signal to the whole process group, and an exit_code=-5 result.

(Complements tests/test_cancellation.py, which covers the MCP tool surface.)
"""

from __future__ import annotations

import contextlib
import importlib
import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

import pytest

REPO = Path(__file__).parent.parent
sys.path.insert(0, str(REPO))

daemon = importlib.import_module("cowork_to_code_bridge.daemon")
client = importlib.import_module("cowork_to_code_bridge.client")


# ---------------------------------------------------------------------------
# 1. Reading cancel requests
# ---------------------------------------------------------------------------

def test_read_cancel_request_absent_is_none(tmp_path, monkeypatch):
    monkeypatch.setattr(daemon, "CANCEL", tmp_path)
    assert daemon._read_cancel_request("task-1") is None


def test_read_cancel_request_returns_reason(tmp_path, monkeypatch):
    monkeypatch.setattr(daemon, "CANCEL", tmp_path)
    (tmp_path / "task-1.json").write_text(json.dumps({"reason": "user aborted"}))
    assert daemon._read_cancel_request("task-1") == "user aborted"


def test_read_cancel_request_malformed_still_cancels(tmp_path, monkeypatch):
    """Presence is the signal; a corrupt body must not mean 'keep running'."""
    monkeypatch.setattr(daemon, "CANCEL", tmp_path)
    (tmp_path / "task-1.json").write_text("{not json")
    assert daemon._read_cancel_request("task-1") == "cancelled by request"


def test_read_cancel_request_no_reason_field(tmp_path, monkeypatch):
    monkeypatch.setattr(daemon, "CANCEL", tmp_path)
    (tmp_path / "task-1.json").write_text(json.dumps({"id": "task-1"}))
    assert daemon._read_cancel_request("task-1") == "cancelled by request"


def test_clear_cancel_request_is_idempotent(tmp_path, monkeypatch):
    monkeypatch.setattr(daemon, "CANCEL", tmp_path)
    (tmp_path / "t.json").write_text("{}")
    daemon._clear_cancel_request("t")
    assert not (tmp_path / "t.json").exists()
    daemon._clear_cancel_request("t")  # must not raise on a missing file


# ---------------------------------------------------------------------------
# 2. End-to-end: a long-running child is actually killed
# ---------------------------------------------------------------------------

def test_cancel_kills_running_child(tmp_path):
    """The real thing: a 300s sleeper must die in seconds, not run to term."""
    script = tmp_path / "slow.py"
    script.write_text("import time\nprint('started', flush=True)\ntime.sleep(300)\n")
    fired = {"n": 0}

    def cancel_check():
        fired["n"] += 1                      # let it start, cancel on a later poll
        return "test abort" if fired["n"] >= 2 else None

    t0 = time.monotonic()
    result = daemon._run_streaming(
        [sys.executable, str(script)], cwd=str(tmp_path), env={**os.environ},
        timeout=300, progress_file=tmp_path / "p.log", cancel_check=cancel_check,
    )
    elapsed = time.monotonic() - t0

    assert result["exit_code"] == -5
    assert result["cancelled"] is True
    assert result["cancel_reason"] == "test abort"
    assert elapsed < 30, f"cancellation took {elapsed:.1f}s — child was not killed"


def test_cancel_kills_grandchildren(tmp_path):
    """A script's spawned children must die too, or they orphan and keep running.

    The shell spawns a python sleeper, records its pid, then waits. Killing only
    the shell would leave the sleeper alive — this asserts the whole group dies.
    """
    pidfile = tmp_path / "child.pid"
    script = tmp_path / "spawner.sh"
    script.write_text(
        f'#!/bin/bash\n'
        f'{sys.executable} -c "import time; time.sleep(300)" &\n'
        f'echo $! > {pidfile}\n'
        f'echo spawned\n'
        f'wait\n'
    )
    calls = {"n": 0}

    def cancel_check():
        calls["n"] += 1
        # Only cancel once the grandchild is confirmed up.
        return "kill the tree" if pidfile.exists() and calls["n"] >= 2 else None

    result = daemon._run_streaming(
        ["bash", str(script)], cwd=str(tmp_path), env={**os.environ},
        timeout=300, progress_file=tmp_path / "p.log", cancel_check=cancel_check,
    )
    assert result["exit_code"] == -5
    assert pidfile.exists(), "grandchild never started; test isn't exercising the tree"
    grandchild = int(pidfile.read_text().strip())

    for _ in range(50):
        try:
            os.kill(grandchild, 0)
        except OSError:
            break
        time.sleep(0.1)
    else:
        with contextlib.suppress(OSError):
            os.kill(grandchild, signal.SIGKILL)
        pytest.fail(f"grandchild {grandchild} survived cancellation — "
                    "process group was not signalled")


def test_no_cancel_check_runs_to_completion(tmp_path):
    """cancel_check=None must degrade to ordinary behaviour, not break."""
    script = tmp_path / "quick.py"
    script.write_text("print('done')\n")
    result = daemon._run_streaming(
        [sys.executable, str(script)], cwd=str(tmp_path), env={**os.environ},
        timeout=30, progress_file=tmp_path / "p.log", cancel_check=None,
    )
    assert result["exit_code"] == 0
    assert result["stdout"].strip() == "done"
    assert "cancelled" not in result


def test_uncancelled_task_keeps_normal_result_shape(tmp_path):
    """A task nobody cancels must not gain cancellation keys."""
    script = tmp_path / "quick.py"
    script.write_text("print('fine')\n")
    result = daemon._run_streaming(
        [sys.executable, str(script)], cwd=str(tmp_path), env={**os.environ},
        timeout=30, progress_file=tmp_path / "p.log", cancel_check=lambda: None,
    )
    assert result["exit_code"] == 0
    assert "cancelled" not in result
    assert "cancel_reason" not in result


def test_timeout_still_works_alongside_cancellation(tmp_path):
    """The cancel-aware wait loop must not break the timeout path."""
    script = tmp_path / "slow.py"
    script.write_text("import time\ntime.sleep(60)\n")
    t0 = time.monotonic()
    result = daemon._run_streaming(
        [sys.executable, str(script)], cwd=str(tmp_path), env={**os.environ},
        timeout=2, progress_file=tmp_path / "p.log", cancel_check=lambda: None,
    )
    elapsed = time.monotonic() - t0
    assert result["exit_code"] == -2
    assert "timeout" in result["error"]
    assert elapsed < 25, f"timeout path took {elapsed:.1f}s"


def test_sigkill_escalation_for_sigterm_ignoring_child(tmp_path, monkeypatch):
    """A child that traps SIGTERM must still die, via SIGKILL after the grace."""
    monkeypatch.setattr(daemon, "CANCEL_GRACE_SEC", 1.0)
    script = tmp_path / "stubborn.py"
    script.write_text(
        "import signal, time\n"
        "signal.signal(signal.SIGTERM, signal.SIG_IGN)\n"
        "print('armed', flush=True)\n"
        "time.sleep(300)\n"
    )
    calls = {"n": 0}

    def cancel_check():
        calls["n"] += 1
        return "die" if calls["n"] >= 3 else None

    t0 = time.monotonic()
    result = daemon._run_streaming(
        [sys.executable, str(script)], cwd=str(tmp_path), env={**os.environ},
        timeout=300, progress_file=tmp_path / "p.log", cancel_check=cancel_check,
    )
    elapsed = time.monotonic() - t0
    assert result["exit_code"] == -5
    assert elapsed < 30, f"SIGKILL escalation took {elapsed:.1f}s"


def test_cancelled_result_reports_partial_output(tmp_path):
    """Output produced before the kill must survive into the result."""
    script = tmp_path / "chatty.py"
    script.write_text(
        "import time\nprint('work in progress', flush=True)\ntime.sleep(300)\n"
    )
    calls = {"n": 0}

    def cancel_check():
        calls["n"] += 1
        return "stop" if calls["n"] >= 3 else None

    result = daemon._run_streaming(
        [sys.executable, str(script)], cwd=str(tmp_path), env={**os.environ},
        timeout=300, progress_file=tmp_path / "p.log", cancel_check=cancel_check,
    )
    assert result["exit_code"] == -5
    assert "work in progress" in result["stdout"]


# ---------------------------------------------------------------------------
# 3. Client surface
# ---------------------------------------------------------------------------

def _bridge(tmp_path):
    for sub in ("queue", "results", "progress", "cancel"):
        (tmp_path / sub).mkdir(parents=True, exist_ok=True)
    return tmp_path


def test_cancel_task_writes_request_for_queued(tmp_path):
    root = _bridge(tmp_path)
    (root / "queue" / "t1.json").write_text("{}")
    out = client.cancel_task("t1", reason="changed my mind", bridge_root=root)
    assert out["status"] == "requested"
    req = json.loads((root / "cancel" / "t1.json").read_text())
    assert req["reason"] == "changed my mind"
    assert req["id"] == "t1"


def test_cancel_task_writes_request_for_running(tmp_path):
    root = _bridge(tmp_path)
    (root / "progress" / "t2.log").write_text("working\n")
    out = client.cancel_task("t2", bridge_root=root)
    assert out["status"] == "requested"
    assert (root / "cancel" / "t2.json").exists()


def test_cancel_task_already_completed_is_noop(tmp_path):
    root = _bridge(tmp_path)
    (root / "results" / "t3.json").write_text(json.dumps({"exit_code": 0}))
    out = client.cancel_task("t3", bridge_root=root)
    assert out["status"] == "already_done"
    # No stale request left behind to bite a future task reusing this id.
    assert not (root / "cancel" / "t3.json").exists()


def test_cancel_task_unknown_task(tmp_path):
    root = _bridge(tmp_path)
    out = client.cancel_task("nope", bridge_root=root)
    assert out["status"] == "unknown"
    assert not (root / "cancel" / "nope.json").exists()


def test_cancel_task_twice_is_harmless(tmp_path):
    root = _bridge(tmp_path)
    (root / "queue" / "t4.json").write_text("{}")
    assert client.cancel_task("t4", bridge_root=root)["status"] == "requested"
    assert client.cancel_task("t4", bridge_root=root)["status"] == "requested"
    assert json.loads((root / "cancel" / "t4.json").read_text())["id"] == "t4"


def test_cancel_task_leaves_no_tmp_file(tmp_path):
    """The atomic write must not leave a .tmp behind for the daemon to trip on."""
    root = _bridge(tmp_path)
    (root / "queue" / "t5.json").write_text("{}")
    client.cancel_task("t5", bridge_root=root)
    assert list((root / "cancel").glob("*.tmp")) == []


def test_cancel_task_exported_from_package():
    pkg = importlib.import_module("cowork_to_code_bridge")
    assert hasattr(pkg, "cancel_task")
    assert "cancel_task" in pkg.__all__
    # queue_task/poll_task_result are documented as core API in CLAUDE.md but
    # were never exported; guard that they stay reachable too.
    for name in ("queue_task", "poll_task_result"):
        assert hasattr(pkg, name), f"{name} must be importable from the package"


# ---------------------------------------------------------------------------
# 4. Wiring guards
# ---------------------------------------------------------------------------

def test_mcp_cancel_no_longer_claims_a_signal_it_never_sent():
    src = (REPO / "cowork_to_code_bridge" / "mcp_operations.py").read_text()
    assert "SIGTERM sent to process" not in src, (
        "cancel_operation must not report sending a signal it does not send"
    )
    assert '"cancel"' in src, (
        "cancel_operation must write a real request into cancel/ so the daemon "
        "can act on it"
    )


def test_daemon_wires_cancel_check_into_streaming():
    src = (REPO / "cowork_to_code_bridge" / "daemon.py").read_text()
    assert "cancel_check=lambda: _read_cancel_request(cmd_id)" in src, (
        "run_one must pass a cancel_check to _run_streaming, or a cancel request "
        "is written but never read"
    )
    assert "start_new_session=True" in src, (
        "the child must run in its own process group so cancellation reaches "
        "spawned grandchildren"
    )


def test_cancel_dir_is_permission_hardened():
    src = (REPO / "cowork_to_code_bridge" / "daemon.py").read_text()
    hardening = src[src.index("for d in (BRIDGE_ROOT, QUEUE, SCRIPTS_DIR"):]
    assert "CANCEL" in hardening[:200], (
        "cancel/ must be 0o700-hardened — a world-writable cancel dir would let "
        "any local user kill the owner's tasks"
    )


# ---------------------------------------------------------------------------
# 5. Negative control — prove the tree-kill test can fail.
# ---------------------------------------------------------------------------

def test_negative_control_bare_terminate_leaves_grandchild(tmp_path):
    """Kill only the direct child and show the grandchild survives.

    This is what the code did before start_new_session + killpg. If this ever
    fails, test_cancel_kills_grandchildren has lost its teeth.
    """
    pidfile = tmp_path / "gc.pid"
    script = tmp_path / "spawner.sh"
    script.write_text(
        f'#!/bin/bash\n'
        f'{sys.executable} -c "import time; time.sleep(30)" &\n'
        f'echo $! > {pidfile}\n'
        f'wait\n'
    )
    proc = subprocess.Popen(["bash", str(script)])
    for _ in range(50):
        if pidfile.exists():
            break
        time.sleep(0.1)
    assert pidfile.exists(), "grandchild never started"
    grandchild = int(pidfile.read_text().strip())

    proc.terminate()          # the OLD behaviour: signal the shell only
    proc.wait(timeout=10)
    time.sleep(0.5)
    try:
        os.kill(grandchild, 0)
        survived = True
    except OSError:
        survived = False
    with contextlib.suppress(OSError):
        os.kill(grandchild, signal.SIGKILL)
    assert survived, (
        "negative control broken: a bare terminate() should have orphaned the "
        "grandchild, which is the failure mode killpg exists to prevent"
    )
