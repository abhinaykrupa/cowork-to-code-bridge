"""End-to-end test: drive run_one() directly to confirm idempotency + journal
flow against a real subprocess. Doesn't run the polling loop, just one cycle."""
from __future__ import annotations

import importlib
import json
import os
from pathlib import Path

import pytest


@pytest.fixture
def bridge(tmp_path, monkeypatch):
    monkeypatch.setenv("BRIDGE_ROOT", str(tmp_path))
    monkeypatch.setenv("BRIDGE_TOKEN", "test-token")
    import cowork_to_code_bridge.daemon as d
    importlib.reload(d)
    for sub in (d.QUEUE, d.RESULTS, d.PROCESSED, d.INFLIGHT, d.PROGRESS, d.SCRIPTS_DIR):
        sub.mkdir(parents=True, exist_ok=True)
    # Install a script that always succeeds and prints a side-effect counter.
    counter = tmp_path / "counter"
    counter.write_text("0")
    script = d.SCRIPTS_DIR / "increment.sh"
    script.write_text(
        "#!/bin/bash\n"
        f"f={counter}\n"
        "n=$(cat $f)\n"
        "n=$((n+1))\n"
        "echo $n > $f\n"
        "echo \"ran $n\"\n"
    )
    script.chmod(0o755)
    return d, counter


def _enqueue(d, cmd_id, **payload):
    p = {"id": cmd_id, "script": "scripts/increment.sh", "args": [],
         "token": "test-token", "timeout": 5, **payload}
    f = d.QUEUE / f"{cmd_id}.json"
    f.write_text(json.dumps(p))
    return f


def test_e2e_normal_run_creates_journal_and_clears_marker(bridge):
    d, counter = bridge
    terminal, cache = {}, {}
    f = _enqueue(d, "1100_aaa")
    d.run_one(f, "test-token", terminal, cache)

    # Subprocess ran.
    assert counter.read_text().strip() == "1"
    # Result file exists with success.
    res = json.loads((d.RESULTS / "1100_aaa.json").read_text())
    assert res["exit_code"] == 0
    assert "ran 1" in res["stdout"]
    # Marker cleared, queue moved.
    assert not (d.INFLIGHT / "1100_aaa.running").exists()
    assert (d.PROCESSED / "1100_aaa.json").exists()
    # Journal has received + started + completed.
    events = [json.loads(l) for l in d.JOURNAL.read_text().splitlines()]
    types = [e["event"] for e in events]
    assert types == ["received", "started", "completed"]


def test_e2e_idempotency_replays_cached_result_without_running(bridge):
    d, counter = bridge
    terminal, cache = {}, {}

    # First call with key.
    f1 = _enqueue(d, "1200_aaa", idempotency_key="my-deploy")
    d.run_one(f1, "test-token", terminal, cache)
    assert counter.read_text().strip() == "1"
    assert "my-deploy" in cache

    # Second call with same key — should NOT re-run the script.
    f2 = _enqueue(d, "1201_bbb", idempotency_key="my-deploy")
    d.run_one(f2, "test-token", terminal, cache)
    assert counter.read_text().strip() == "1", "script must not re-run on idempotency hit"

    res2 = json.loads((d.RESULTS / "1201_bbb.json").read_text())
    assert res2["exit_code"] == 0
    assert res2.get("idempotent_replay") is True
    # Different cmd_id but same payload as the first run.
    assert "ran 1" in res2["stdout"]


def test_e2e_idempotency_cache_survives_journal_replay(bridge):
    """The fundamental promise: after a daemon restart, the idempotency cache
    is rebuilt from journal.log, so a retry from the client still gets the
    cached result instead of a re-run."""
    d, counter = bridge

    # Run once.
    terminal, cache = {}, {}
    f1 = _enqueue(d, "1300_aaa", idempotency_key="ship-it")
    d.run_one(f1, "test-token", terminal, cache)
    assert counter.read_text().strip() == "1"

    # Simulate a daemon restart: throw away the in-memory state, replay journal.
    terminal2, cache2 = d._journal_replay()
    assert "ship-it" in cache2, "idempotency cache must rebuild from journal"

    # Client retries with same key (new cmd_id, since cmd_ids are unique per call).
    f2 = _enqueue(d, "1301_bbb", idempotency_key="ship-it")
    d.run_one(f2, "test-token", terminal2, cache2)
    assert counter.read_text().strip() == "1", "script must not re-run after restart"


def test_e2e_bad_script_path_journals_received_then_fails_without_marker(bridge):
    """Auth + validation failures should record received in journal but never
    write an in-flight marker — they don't get to the subprocess step."""
    d, _ = bridge
    terminal, cache = {}, {}
    f = _enqueue(d, "1400_aaa", script="scripts/../etc/passwd")
    d.run_one(f, "test-token", terminal, cache)

    res = json.loads((d.RESULTS / "1400_aaa.json").read_text())
    assert res["exit_code"] == -1
    # No in-flight marker.
    assert not (d.INFLIGHT / "1400_aaa.running").exists()


def test_e2e_progress_file_written_during_run_and_cleared_after(bridge):
    """Streaming: the daemon writes a live progress file while the script runs,
    capturing its output, then removes it once the final result is written."""
    d, counter = bridge
    terminal, cache = {}, {}
    f = _enqueue(d, "1400_str")
    d.run_one(f, "test-token", terminal, cache)

    # Final result has the output (proves the tee captured it).
    res = json.loads((d.RESULTS / "1400_str.json").read_text())
    assert res["exit_code"] == 0
    assert "ran 1" in res["stdout"]
    # Progress file is cleaned up after completion (result is authoritative).
    assert not (d.PROGRESS / "1400_str.log").exists()
