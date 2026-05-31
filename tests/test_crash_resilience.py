"""Crash-resilience tests for the daemon.

These tests don't run the daemon as a long-lived process — they call the
recovery helpers directly with simulated state on disk. That's the right
abstraction level: the daemon's crash safety lives entirely in
journal+inflight semantics, so we test those semantics, not the polling loop.

Run with: pytest tests/test_crash_resilience.py -v
"""
from __future__ import annotations

import json
import os
from pathlib import Path

import pytest


@pytest.fixture
def bridge(tmp_path, monkeypatch):
    """Set BRIDGE_ROOT to a tmp dir and re-import the daemon module fresh."""
    monkeypatch.setenv("BRIDGE_ROOT", str(tmp_path))
    monkeypatch.setenv("BRIDGE_TOKEN", "test-token")
    # Force a fresh import so module-level paths pick up the new BRIDGE_ROOT.
    import importlib
    import cowork_to_code_bridge.daemon as d
    importlib.reload(d)
    for sub in (d.QUEUE, d.RESULTS, d.PROCESSED, d.INFLIGHT, d.PROGRESS, d.SCRIPTS_DIR):
        sub.mkdir(parents=True, exist_ok=True)
    return d


def _write_queue(d, cmd_id: str, payload: dict) -> Path:
    f = d.QUEUE / f"{cmd_id}.json"
    f.write_text(json.dumps(payload))
    return f


def _write_inflight(d, cmd_id: str, pid: int = 99999) -> Path:
    f = d.INFLIGHT / f"{cmd_id}.running"
    f.write_text(json.dumps({"id": cmd_id, "pid": pid, "started_ts": 0, "cmd": {}}))
    return f


def test_journal_append_and_replay_roundtrip(bridge):
    d = bridge
    d._journal_append({"id": "a", "event": "received"})
    d._journal_append({"id": "a", "event": "started", "pid": 1})
    d._journal_append({"id": "a", "event": "completed", "result": {"exit_code": 0}})
    terminal, cache = d._journal_replay()
    assert terminal == {"a": "completed"}
    assert cache == {}  # no idempotency key was set


def test_idempotency_cache_built_from_journal(bridge):
    d = bridge
    d._journal_append({"id": "a", "event": "received", "idempotency_key": "deploy-v1"})
    d._journal_append({"id": "a", "event": "completed", "result": {"exit_code": 0, "stdout": "ok"}})
    _, cache = d._journal_replay()
    assert cache == {"deploy-v1": {"exit_code": 0, "stdout": "ok"}}


def test_partial_journal_line_does_not_crash_replay(bridge):
    """A power loss can leave a half-written last line. Replay must tolerate it."""
    d = bridge
    d._journal_append({"id": "a", "event": "completed", "result": {"exit_code": 0}})
    # Append a truncated line (simulating power cut mid-write).
    with open(d.JOURNAL, "a") as f:
        f.write('{"id": "b", "event": "rec')
    terminal, _ = d._journal_replay()
    assert terminal == {"a": "completed"}


def test_inflight_marker_with_no_terminal_status_yields_crash_record(bridge):
    """The flagship Tier-1 contract: a leftover marker means we crashed."""
    d = bridge
    cmd_id = "1000_abc"
    _write_inflight(d, cmd_id)
    _write_queue(d, cmd_id, {"script": "scripts/whatever.sh"})

    d._recover_inflight(terminal={})

    # Result file should exist with exit_code=-4.
    result_file = d.RESULTS / f"{cmd_id}.json"
    assert result_file.exists(), "recovery must write a result for the orphan"
    result = json.loads(result_file.read_text())
    assert result["exit_code"] == -4
    assert "crashed" in result["error"].lower()

    # Queue file moved to processed; not left for re-run.
    assert not (d.QUEUE / f"{cmd_id}.json").exists()
    assert (d.PROCESSED / f"{cmd_id}.json").exists()
    # Marker cleared.
    assert not (d.INFLIGHT / f"{cmd_id}.running").exists()

    # Journal has the crashed event.
    terminal, _ = d._journal_replay()
    assert terminal.get(cmd_id) == "crashed_inflight"


def test_inflight_marker_with_completed_in_journal_is_just_cleanup(bridge):
    """If the journal already says completed, the marker is just stale cleanup —
    do NOT overwrite the successful result with exit_code=-4."""
    d = bridge
    cmd_id = "1001_xyz"
    # Journal says we finished.
    d._journal_append({"id": cmd_id, "event": "received"})
    d._journal_append({"id": cmd_id, "event": "completed", "result": {"exit_code": 0, "stdout": "good"}})
    # Pre-existing result file from before the crash.
    (d.RESULTS / f"{cmd_id}.json").write_text(json.dumps({"exit_code": 0, "stdout": "good"}))
    # But the inflight marker was never deleted (crash between completed-write and marker-clear).
    _write_inflight(d, cmd_id)
    _write_queue(d, cmd_id, {"script": "scripts/whatever.sh"})

    terminal, _ = d._journal_replay()
    assert terminal[cmd_id] == "completed"
    d._recover_inflight(terminal)

    # Result preserved.
    result = json.loads((d.RESULTS / f"{cmd_id}.json").read_text())
    assert result["exit_code"] == 0
    assert result["stdout"] == "good"
    # Marker cleared, queue moved.
    assert not (d.INFLIGHT / f"{cmd_id}.running").exists()
    assert (d.PROCESSED / f"{cmd_id}.json").exists()


def test_stale_queue_file_with_terminal_status_is_drained(bridge):
    """Edge case: a queue file lingers for an id the journal already finalized."""
    d = bridge
    cmd_id = "1002_def"
    d._journal_append({"id": cmd_id, "event": "completed", "result": {"exit_code": 0}})
    _write_queue(d, cmd_id, {"script": "scripts/x.sh"})

    terminal, _ = d._journal_replay()
    d._drain_stale_queue(terminal)

    assert not (d.QUEUE / f"{cmd_id}.json").exists()
    assert (d.PROCESSED / f"{cmd_id}.json").exists()


def test_inflight_marker_atomic_write_creates_no_partial(bridge):
    """We rename a .tmp into place — readers should never see a partial."""
    d = bridge
    d._inflight_write("xyz", {"script": "scripts/x.sh"})
    # No .tmp left behind.
    assert not (d.INFLIGHT / "xyz.running.tmp").exists()
    marker = d.INFLIGHT / "xyz.running"
    assert marker.exists()
    payload = json.loads(marker.read_text())
    assert payload["id"] == "xyz"
    assert payload["pid"] == os.getpid()


def test_recovery_handles_empty_state(bridge):
    """No journal, no inflight, no queue — recovery should be a no-op."""
    d = bridge
    terminal, cache = d._journal_replay()
    assert terminal == {}
    assert cache == {}
    d._recover_inflight(terminal)  # should not raise
    d._drain_stale_queue(terminal)  # should not raise
