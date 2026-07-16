"""
Tests for async task queuing and polling (non-blocking interface).

Tests the queue_task() and poll_task_result() functions that allow
submitting tasks without waiting (useful in time-limited environments).
"""
from __future__ import annotations

import json
import tempfile
import time
from pathlib import Path

import pytest

from cowork_to_code_bridge.client import (
    format_status_line,
    poll_task_result,
    queue_task,
)


@pytest.fixture
def bridge_root():
    """A throwaway bridge directory."""
    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir) / "bridge"
        for sub in ("queue", "results", "progress"):
            (root / sub).mkdir(parents=True, exist_ok=True)
        yield root


def test_queue_task_returns_task_id(bridge_root):
    """queue_task() returns task_id and status='queued'."""
    result = queue_task(
        "scripts/ping.sh",
        args=[],
        timeout=30,
        bridge_root=bridge_root,
    )

    assert "task_id" in result
    assert result["status"] == "queued"
    assert "timestamp" in result
    assert result["task_id"].startswith(str(int(time.time()))[:9])

    # Task file should exist in queue
    task_file = bridge_root / "queue" / f"{result['task_id']}.json"
    assert task_file.exists()


def test_queue_task_effort_in_payload(bridge_root):
    """queue_task(effort=...) writes a normalized effort into the task payload (issue #33)."""
    result = queue_task(
        "scripts/run_claude.sh",
        args=["do a thing"],
        timeout=60,
        bridge_root=bridge_root,
        effort="  HIGH  ",
    )
    task_file = bridge_root / "queue" / f"{result['task_id']}.json"
    payload = json.loads(task_file.read_text())
    assert payload["effort"] == "high"  # trimmed + lowercased


def test_queue_task_no_effort_key_when_unset(bridge_root):
    """Omitting effort must not add an 'effort' key (daemon then uses CLI default)."""
    result = queue_task(
        "scripts/run_claude.sh",
        args=[],
        timeout=60,
        bridge_root=bridge_root,
    )
    task_file = bridge_root / "queue" / f"{result['task_id']}.json"
    payload = json.loads(task_file.read_text())
    assert "effort" not in payload


def test_queue_task_atomic_write(bridge_root):
    """Task file is written atomically (.tmp then rename)."""
    result = queue_task(
        "scripts/hello.sh",
        args=["arg1"],
        timeout=60,
        bridge_root=bridge_root,
    )

    task_file = bridge_root / "queue" / f"{result['task_id']}.json"
    assert task_file.exists()

    # Should not have .tmp file (it was renamed)
    tmp_file = task_file.with_suffix(".json.tmp")
    assert not tmp_file.exists()


def test_poll_task_result_queued(bridge_root):
    """poll_task_result() returns status='queued' for newly queued tasks."""
    queued = queue_task("scripts/test.sh", bridge_root=bridge_root)
    task_id = queued["task_id"]

    result = poll_task_result(task_id, bridge_root=bridge_root)

    assert result["status"] == "queued"
    assert result["task_id"] == task_id


def test_poll_task_result_running(bridge_root):
    """poll_task_result() returns status='running' when progress log exists."""
    queued = queue_task("scripts/long.sh", bridge_root=bridge_root)
    task_id = queued["task_id"]

    # Simulate daemon writing progress
    progress_log = bridge_root / "progress" / f"{task_id}.log"
    progress_log.write_text("Running step 1...\nRunning step 2...\n")

    result = poll_task_result(task_id, bridge_root=bridge_root)

    assert result["status"] == "running"
    assert result["progress_available"] is True


def test_poll_task_result_running_surfaces_status_ticker(bridge_root):
    """When the daemon has written status.json, poll exposes the live ticker."""
    queued = queue_task("scripts/build.sh", bridge_root=bridge_root)
    task_id = queued["task_id"]

    progress = bridge_root / "progress"
    (progress / f"{task_id}.log").write_text("Building...\n")
    (progress / f"{task_id}.status.json").write_text(
        json.dumps({"elapsed_s": 42, "last_line": "Compiling foo.c", "state": "running"})
    )

    result = poll_task_result(task_id, bridge_root=bridge_root)

    assert result["status"] == "running"
    assert result["elapsed_s"] == 42
    assert result["last_line"] == "Compiling foo.c"
    assert result["state"] == "running"
    assert "42s elapsed" in result["status_line"]


def test_poll_task_result_running_without_status_file(bridge_root):
    """A missing status.json is fine — running result just omits ticker keys."""
    queued = queue_task("scripts/long.sh", bridge_root=bridge_root)
    task_id = queued["task_id"]
    (bridge_root / "progress" / f"{task_id}.log").write_text("step 1\n")

    result = poll_task_result(task_id, bridge_root=bridge_root)

    assert result["status"] == "running"
    assert "status_line" not in result
    assert "elapsed_s" not in result


def test_poll_task_result_ignores_corrupt_status_file(bridge_root):
    """A half-written status.json must not break polling."""
    queued = queue_task("scripts/long.sh", bridge_root=bridge_root)
    task_id = queued["task_id"]
    progress = bridge_root / "progress"
    (progress / f"{task_id}.log").write_text("step 1\n")
    (progress / f"{task_id}.status.json").write_text('{"elapsed_s": 5, ')  # truncated

    result = poll_task_result(task_id, bridge_root=bridge_root)

    assert result["status"] == "running"
    assert "status_line" not in result


def test_format_status_line_running():
    line = format_status_line({"elapsed_s": 42, "state": "running"}, verb="Building")
    assert "Building…" in line
    assert "42s elapsed" in line
    # leading char is a braille spinner frame, not ASCII
    assert line[0] in "⣾⣽⣻⢿⡿⣟⣯⣷"


def test_format_status_line_spinner_advances_with_elapsed():
    a = format_status_line({"elapsed_s": 0})
    b = format_status_line({"elapsed_s": 1})
    assert a[0] != b[0]


def test_format_status_line_terminal_states():
    assert "Done in 10s" in format_status_line({"elapsed_s": 10, "state": "done"})
    assert "Failed after 7s" in format_status_line({"elapsed_s": 7, "state": "failed"})


def test_format_status_line_show_last_line():
    line = format_status_line(
        {"elapsed_s": 3, "last_line": "Compiling foo.c", "state": "running"},
        show_last_line=True,
    )
    assert "Compiling foo.c" in line


def test_format_status_line_show_last_line_short_line_intact():
    # A short line is appended verbatim (no ellipsis).
    line = format_status_line(
        {"elapsed_s": 1, "last_line": "ok", "state": "running"},
        show_last_line=True,
    )
    tail = line.split("  ·  ", 1)[1]
    assert tail == "ok"  # verbatim, not clipped


def test_format_status_line_truncates_long_last_line():
    # A wide log line must be clipped so the ticker stays a compact one-liner.
    long_line = "x" * 500
    line = format_status_line(
        {"elapsed_s": 3, "last_line": long_line, "state": "running"},
        show_last_line=True,
    )
    assert line.endswith("…")
    # The appended tail (after the "  ·  " separator) is bounded.
    tail = line.split("  ·  ", 1)[1]
    assert len(tail) <= 80
    assert long_line not in line


def test_format_status_line_handles_missing_elapsed():
    # Defensive: empty/garbage dict must not raise.
    assert "0s elapsed" in format_status_line({})


def test_poll_task_result_completed(bridge_root):
    """poll_task_result() returns status='completed' with full result."""
    queued = queue_task("scripts/done.sh", bridge_root=bridge_root)
    task_id = queued["task_id"]

    # Simulate daemon writing result
    result_file = bridge_root / "results" / f"{task_id}.json"
    final_result = {
        "id": task_id,
        "exit_code": 0,
        "stdout": "Success!\n",
        "stderr": "",
        "ts_completed": time.time(),
    }
    result_file.write_text(json.dumps(final_result))

    result = poll_task_result(task_id, bridge_root=bridge_root)

    assert result["status"] == "completed"
    assert result["exit_code"] == 0
    assert result["stdout"] == "Success!\n"


def test_poll_task_result_unknown_task(bridge_root):
    """poll_task_result() returns status='unknown' for non-existent tasks."""
    result = poll_task_result("nonexistent_task_12345", bridge_root=bridge_root)

    assert result["status"] == "unknown"
    assert "not found" in result["message"].lower()


def test_queue_then_poll_workflow(bridge_root):
    """Full async workflow: queue → poll until done."""
    # 1. Queue a task (returns immediately)
    queued = queue_task(
        "scripts/quick.sh",
        args=["arg"],
        timeout=30,
        bridge_root=bridge_root,
    )
    task_id = queued["task_id"]
    assert queued["status"] == "queued"

    # 2. Poll - should be queued
    status = poll_task_result(task_id, bridge_root=bridge_root)
    assert status["status"] == "queued"

    # 3. Simulate daemon picking up the task (write progress)
    progress_log = bridge_root / "progress" / f"{task_id}.log"
    progress_log.write_text("Starting work...\n")

    status = poll_task_result(task_id, bridge_root=bridge_root)
    assert status["status"] == "running"

    # 4. Simulate daemon completing (write result)
    result_file = bridge_root / "results" / f"{task_id}.json"
    result_file.write_text(json.dumps({
        "id": task_id,
        "exit_code": 0,
        "stdout": "Done!\n",
        "stderr": "",
        "ts_completed": time.time(),
    }))

    status = poll_task_result(task_id, bridge_root=bridge_root)
    assert status["status"] == "completed"
    assert status["exit_code"] == 0


def test_idempotent_polling(bridge_root):
    """poll_task_result() is fully idempotent."""
    queued = queue_task("scripts/test.sh", bridge_root=bridge_root)
    task_id = queued["task_id"]

    # Poll multiple times, should get same result
    r1 = poll_task_result(task_id, bridge_root=bridge_root)
    r2 = poll_task_result(task_id, bridge_root=bridge_root)
    r3 = poll_task_result(task_id, bridge_root=bridge_root)

    assert r1 == r2 == r3
    assert r1["status"] == "queued"
