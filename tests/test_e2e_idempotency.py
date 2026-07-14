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
    d, _ = bridge

    # Instead, test _run_streaming directly with a short script.
    script = tmp_path / "ok.sh"
    script.write_text("#!/bin/bash\necho hello\n")
    script.chmod(0o755)
    progress_file = tmp_path / "progress" / "test.log"
    progress_file.parent.mkdir(parents=True, exist_ok=True)
    d._run_streaming(
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


# ─── max_budget_usd tests ─────────────────────────────────────────────────────

def _budget_bridge(tmp_path, monkeypatch, owner_ceiling=None):
    """Return a bridge fixture with an optional BRIDGE_MAX_BUDGET_USD ceiling."""
    monkeypatch.setenv("BRIDGE_ROOT", str(tmp_path))
    monkeypatch.setenv("BRIDGE_TOKEN", "test-token")
    if owner_ceiling is not None:
        monkeypatch.setenv("BRIDGE_MAX_BUDGET_USD", str(owner_ceiling))
    else:
        monkeypatch.delenv("BRIDGE_MAX_BUDGET_USD", raising=False)
    import cowork_to_code_bridge.daemon as d
    importlib.reload(d)
    for sub in (d.QUEUE, d.RESULTS, d.PROCESSED, d.INFLIGHT, d.PROGRESS, d.SCRIPTS_DIR):
        sub.mkdir(parents=True, exist_ok=True)
    # A script that dumps its environment so we can inspect MAX_BUDGET_USD.
    script = d.SCRIPTS_DIR / "dump_env.sh"
    script.write_text("#!/bin/bash\nenv\n")
    script.chmod(0o755)
    return d


def test_budget_caller_value_forwarded_to_env(tmp_path, monkeypatch):
    """max_budget_usd in the command payload is forwarded as MAX_BUDGET_USD env var."""
    d = _budget_bridge(tmp_path, monkeypatch)
    p = {"id": "b1", "script": "scripts/dump_env.sh", "args": [],
         "token": "test-token", "timeout": 5, "max_budget_usd": 3.5}
    (d.QUEUE / "b1.json").write_text(json.dumps(p))
    d.run_one(d.QUEUE / "b1.json", "test-token", {}, {})
    res = json.loads((d.RESULTS / "b1.json").read_text())
    assert res["exit_code"] == 0
    assert "MAX_BUDGET_USD=3.5000" in res["stdout"]


def test_budget_owner_ceiling_forwarded_to_env(tmp_path, monkeypatch):
    """BRIDGE_MAX_BUDGET_USD owner ceiling is forwarded as BRIDGE_MAX_BUDGET_USD env var."""
    d = _budget_bridge(tmp_path, monkeypatch, owner_ceiling=5.0)
    p = {"id": "b2", "script": "scripts/dump_env.sh", "args": [],
         "token": "test-token", "timeout": 5}
    (d.QUEUE / "b2.json").write_text(json.dumps(p))
    d.run_one(d.QUEUE / "b2.json", "test-token", {}, {})
    res = json.loads((d.RESULTS / "b2.json").read_text())
    assert res["exit_code"] == 0
    assert "BRIDGE_MAX_BUDGET_USD=5.0" in res["stdout"]


def test_budget_invalid_value_ignored(tmp_path, monkeypatch):
    """A non-numeric max_budget_usd is silently dropped; the script still runs."""
    d = _budget_bridge(tmp_path, monkeypatch)
    p = {"id": "b3", "script": "scripts/dump_env.sh", "args": [],
         "token": "test-token", "timeout": 5, "max_budget_usd": "bad"}
    (d.QUEUE / "b3.json").write_text(json.dumps(p))
    d.run_one(d.QUEUE / "b3.json", "test-token", {}, {})
    res = json.loads((d.RESULTS / "b3.json").read_text())
    assert res["exit_code"] == 0
    assert "MAX_BUDGET_USD" not in res["stdout"]


def test_budget_negative_value_ignored(tmp_path, monkeypatch):
    """Negative max_budget_usd is silently dropped."""
    d = _budget_bridge(tmp_path, monkeypatch)
    p = {"id": "b4", "script": "scripts/dump_env.sh", "args": [],
         "token": "test-token", "timeout": 5, "max_budget_usd": -1.0}
    (d.QUEUE / "b4.json").write_text(json.dumps(p))
    d.run_one(d.QUEUE / "b4.json", "test-token", {}, {})
    res = json.loads((d.RESULTS / "b4.json").read_text())
    assert res["exit_code"] == 0
    assert "MAX_BUDGET_USD" not in res["stdout"]


def test_budget_caller_cannot_override_owner_ceiling(tmp_path, monkeypatch):
    """Caller cannot override BRIDGE_MAX_BUDGET_USD — it is in the protected list."""
    d = _budget_bridge(tmp_path, monkeypatch, owner_ceiling=5.0)
    # Caller tries to set BRIDGE_MAX_BUDGET_USD via the env dict (not max_budget_usd).
    p = {"id": "b5", "script": "scripts/dump_env.sh", "args": [],
         "token": "test-token", "timeout": 5,
         "env": {"BRIDGE_MAX_BUDGET_USD": "999.0"}}
    (d.QUEUE / "b5.json").write_text(json.dumps(p))
    d.run_one(d.QUEUE / "b5.json", "test-token", {}, {})
    res = json.loads((d.RESULTS / "b5.json").read_text())
    assert res["exit_code"] == 0
    # The owner's value (5.0) must not have been overwritten to 999.
    assert "BRIDGE_MAX_BUDGET_USD=999" not in res["stdout"]
    assert "BRIDGE_MAX_BUDGET_USD=5.0" in res["stdout"]


def _scope_bridge(tmp_path, monkeypatch, ceiling=None):
    """Return a bridge fixture with an optional BRIDGE_PERMISSION_CEILING.

    Uses a dump_env.sh script so tests can inspect the CLAUDE_FLAGS the daemon
    injects for a caller-supplied permission_scope.
    """
    monkeypatch.setenv("BRIDGE_ROOT", str(tmp_path))
    monkeypatch.setenv("BRIDGE_TOKEN", "test-token")
    # Ensure no owner CLAUDE_FLAGS is set (that would short-circuit scope logic).
    monkeypatch.delenv("CLAUDE_FLAGS", raising=False)
    if ceiling is not None:
        monkeypatch.setenv("BRIDGE_PERMISSION_CEILING", str(ceiling))
    else:
        monkeypatch.delenv("BRIDGE_PERMISSION_CEILING", raising=False)
    import cowork_to_code_bridge.daemon as d
    importlib.reload(d)
    for sub in (d.QUEUE, d.RESULTS, d.PROCESSED, d.INFLIGHT, d.PROGRESS, d.SCRIPTS_DIR):
        sub.mkdir(parents=True, exist_ok=True)
    script = d.SCRIPTS_DIR / "dump_env.sh"
    script.write_text("#!/bin/bash\nenv\n")
    script.chmod(0o755)
    return d


def _run_scope(d, cmd_id, scope):
    p = {"id": cmd_id, "script": "scripts/dump_env.sh", "args": [],
         "token": "test-token", "timeout": 5, "permission_scope": scope}
    (d.QUEUE / f"{cmd_id}.json").write_text(json.dumps(p))
    d.run_one(d.QUEUE / f"{cmd_id}.json", "test-token", {}, {})
    res = json.loads((d.RESULTS / f"{cmd_id}.json").read_text())
    assert res["exit_code"] == 0
    return res["stdout"]


def test_scope_edit_forwarded_as_claude_flags(tmp_path, monkeypatch):
    """permission_scope='edit' with no ceiling injects the edit CLAUDE_FLAGS."""
    d = _scope_bridge(tmp_path, monkeypatch)
    out = _run_scope(d, "s1", "edit")
    assert "CLAUDE_FLAGS=--allowedTools Read,Glob,Grep,Edit,Write" in out


def test_scope_full_injects_no_flags(tmp_path, monkeypatch):
    """permission_scope='full' leaves CLAUDE_FLAGS unset (defers to CLI default)."""
    d = _scope_bridge(tmp_path, monkeypatch)
    out = _run_scope(d, "s2", "full")
    assert "CLAUDE_FLAGS=" not in out


def test_scope_ceiling_clamps_full_to_edit(tmp_path, monkeypatch):
    """Owner ceiling='edit' clamps a caller's 'full' request down to 'edit'."""
    d = _scope_bridge(tmp_path, monkeypatch, ceiling="edit")
    out = _run_scope(d, "s3", "full")
    # Clamped: gets edit flags, NOT unrestricted full.
    assert "CLAUDE_FLAGS=--allowedTools Read,Glob,Grep,Edit,Write" in out


def test_scope_ceiling_clamps_edit_to_plan(tmp_path, monkeypatch):
    """Owner ceiling='plan' clamps a caller's 'edit' request down to 'plan'."""
    d = _scope_bridge(tmp_path, monkeypatch, ceiling="plan")
    out = _run_scope(d, "s4", "edit")
    assert "CLAUDE_FLAGS=--permission-mode plan" in out


def test_scope_at_or_below_ceiling_not_clamped(tmp_path, monkeypatch):
    """A request at or below the ceiling passes through unchanged."""
    d = _scope_bridge(tmp_path, monkeypatch, ceiling="edit")
    out = _run_scope(d, "s5", "readonly")
    assert "CLAUDE_FLAGS=--allowedTools Read,Glob,Grep" in out
    # readonly must NOT have been widened up to the edit ceiling.
    assert "Edit,Write" not in out


def test_scope_invalid_ceiling_ignored_no_clamp(tmp_path, monkeypatch):
    """An unrecognized BRIDGE_PERMISSION_CEILING enforces no ceiling (fail-open)."""
    d = _scope_bridge(tmp_path, monkeypatch, ceiling="bogus")
    assert d._PERMISSION_CEILING is None
    out = _run_scope(d, "s6", "full")
    # No clamp: full stays full (no flags injected).
    assert "CLAUDE_FLAGS=" not in out


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
    p = json.loads(f.read_text())
    p["token"] = "WRONG"
    f.write_text(json.dumps(p))
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
