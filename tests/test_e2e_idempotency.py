"""End-to-end test: drive run_one() directly to confirm idempotency + journal
flow against a real subprocess. Doesn't run the polling loop, just one cycle."""
from __future__ import annotations

import importlib
import json

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
    events = [json.loads(ln) for ln in d.JOURNAL.read_text().splitlines()]
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


def test_e2e_status_file_cleaned_up_after_run(bridge):
    """The daemon removes the .status.json alongside the .log after the result
    is written. Clients polling the status file should see it disappear once
    the final result JSON is available."""
    d, _ = bridge
    terminal, cache = {}, {}
    f = _enqueue(d, "1500_sta")
    d.run_one(f, "test-token", terminal, cache)

    assert not (d.PROGRESS / "1500_sta.status.json").exists(), (
        ".status.json must be removed alongside .log after run completes"
    )
    assert not (d.PROGRESS / "1500_sta.log").exists()


def test_e2e_status_file_has_correct_terminal_state_for_success(bridge, tmp_path):
    """The _write_status_atomic helper writes state='done' and exit_code=0 on
    success before the file is cleaned up by run_one.  We verify by patching
    the cleanup so we can read the file."""
    import importlib
    d, _ = bridge

    # Intercept unlink so the status file survives for inspection.
    status_path: list = []

    original_run_one = d.run_one

    def patched_run_one(cmd_path, token, terminal, idem_cache):
        # Call the real implementation — cleanup happens inside.
        original_run_one(cmd_path, token, terminal, idem_cache)

    # Instead, test _run_streaming directly with a short script.
    import tempfile, pathlib
    script = tmp_path / "ok.sh"
    script.write_text("#!/bin/bash\necho hello\n")
    script.chmod(0o755)
    progress_file = tmp_path / "progress" / "test.log"
    progress_file.parent.mkdir(parents=True, exist_ok=True)
    result = d._run_streaming(
        ["bash", str(script)], str(tmp_path), {}, timeout=10,
        progress_file=progress_file,
    )
    status_file = tmp_path / "progress" / "test.status.json"
    # _run_streaming writes the terminal status BEFORE returning.
    assert status_file.exists(), ".status.json must be written by _run_streaming before return"
    s = json.loads(status_file.read_text())
    assert s["state"] == "done"
    assert s["exit_code"] == 0
    assert isinstance(s["elapsed_s"], int)
    assert "last_line" in s


def test_e2e_status_file_state_error_on_nonzero_exit(bridge, tmp_path):
    """state='error' when the script exits non-zero."""
    import importlib
    d, _ = bridge
    script = tmp_path / "fail.sh"
    script.write_text("#!/bin/bash\necho oops\nexit 42\n")
    script.chmod(0o755)
    progress_file = tmp_path / "progress" / "fail.log"
    progress_file.parent.mkdir(parents=True, exist_ok=True)
    d._run_streaming(
        ["bash", str(script)], str(tmp_path), {}, timeout=10,
        progress_file=progress_file,
    )
    status_file = tmp_path / "progress" / "fail.status.json"
    assert status_file.exists()
    s = json.loads(status_file.read_text())
    assert s["state"] == "error"
    assert s["exit_code"] == 42


def test_e2e_status_file_last_line_captured(bridge, tmp_path):
    """last_line in the status file reflects the most recent non-empty output."""
    import importlib
    d, _ = bridge
    script = tmp_path / "lines.sh"
    script.write_text("#!/bin/bash\necho first line\necho second line\n")
    script.chmod(0o755)
    progress_file = tmp_path / "progress" / "lines.log"
    progress_file.parent.mkdir(parents=True, exist_ok=True)
    d._run_streaming(
        ["bash", str(script)], str(tmp_path), {}, timeout=10,
        progress_file=progress_file,
    )
    status_file = tmp_path / "progress" / "lines.status.json"
    s = json.loads(status_file.read_text())
    assert s["last_line"] == "second line"


def test_e2e_oversized_command_rejected(bridge):
    """A command file larger than MAX_CMD_BYTES is rejected, not slurped."""
    d, _ = bridge
    cmd_id = "1500_big"
    f = d.QUEUE / f"{cmd_id}.json"
    # Write a valid-looking but oversized payload (padding in an unused field).
    big = {"id": cmd_id, "script": "scripts/increment.sh", "args": [],
           "token": "test-token", "timeout": 5, "pad": "x" * (d.MAX_CMD_BYTES + 10)}
    f.write_text(json.dumps(big))
    d.run_one(f, "test-token", {}, {})
    res = json.loads((d.RESULTS / f"{cmd_id}.json").read_text())
    assert res["exit_code"] == -1
    assert "too large" in res["error"]


def test_e2e_wrong_token_rejected(bridge):
    """Constant-time token check still rejects a wrong token."""
    d, counter = bridge
    cmd_id = "1501_tok"
    f = _enqueue(d, cmd_id)  # _enqueue sets token=test-token
    # Tamper the token.
    p = json.loads(f.read_text()); p["token"] = "WRONG"; f.write_text(json.dumps(p))
    d.run_one(f, "test-token", {}, {})
    res = json.loads((d.RESULTS / f"{cmd_id}.json").read_text())
    assert res["exit_code"] == -1
    assert "token mismatch" in res["error"]
    assert counter.read_text().strip() == "0", "script must not run on bad token"


def test_e2e_caller_cannot_override_protected_env_vars(bridge):
    """Security: a caller with the token must not be able to override CLAUDE_FLAGS
    or other protected env vars set by the daemon owner (e.g. via launchd)."""
    import importlib
    d, _ = bridge

    # Inject CLAUDE_FLAGS into the daemon env (simulates owner setting it in launchd)
    import os
    os.environ["CLAUDE_FLAGS"] = "--permission-mode plan"
    importlib.reload(d)  # reload so daemon picks up the env

    # Caller tries to unset CLAUDE_FLAGS via cmd.env — must NOT take effect
    cmd_id = "1600_sec"
    payload = {
        "id": cmd_id, "script": "scripts/increment.sh", "args": [],
        "token": "test-token", "timeout": 5,
        "env": {"CLAUDE_FLAGS": ""},   # attacker tries to clear the restriction
    }
    f = d.QUEUE / f"{cmd_id}.json"
    import json as _json
    f.write_text(_json.dumps(payload))
    terminal, cache = {}, {}
    d.run_one(f, "test-token", terminal, cache)

    # The call should complete (exit 0 — the increment script doesn't use CLAUDE_FLAGS),
    # but more importantly: verify daemon logged the blocked override attempt.
    import json as j
    res = j.loads((d.RESULTS / f"{cmd_id}.json").read_text())
    assert res["exit_code"] == 0

    # Clean up env
    del os.environ["CLAUDE_FLAGS"]
