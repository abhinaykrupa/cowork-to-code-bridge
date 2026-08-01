"""Tests for queue-age expiry (#77).

`timeout` bounds how long a task may *run*. Nothing bounded how long it may
*wait* in queue/ — so a daemon that was down (asleep, rebooted, crashed) would
drain its backlog on restart and execute every task, potentially hours after
the caller gave up. For a state-changing task that is worse than never running.

These tests assert on the real side effect (a counter file the script
increments), not on the response string. A test that only checked the result
payload would pass against a daemon that wrote "expired" *and still ran the
script* — this repo has shipped exactly that class of no-op before. Each
positive case is therefore paired with a negative control proving the same
setup does execute when it should.
"""
from __future__ import annotations

import importlib
import json
import time

import pytest


@pytest.fixture
def bridge(tmp_path, monkeypatch):
    """Daemon wired to a throwaway root, with a script that has a side effect.

    `counter` starts at 0 and the script increments it. It is the ground truth
    for "did the task actually execute" — result payloads are not.
    """
    monkeypatch.setenv("BRIDGE_ROOT", str(tmp_path))
    monkeypatch.setenv("BRIDGE_TOKEN", "test-token")
    monkeypatch.delenv("BRIDGE_MAX_TASK_AGE_SEC", raising=False)

    def _build(max_age_env: str | None = None):
        if max_age_env is None:
            monkeypatch.delenv("BRIDGE_MAX_TASK_AGE_SEC", raising=False)
        else:
            monkeypatch.setenv("BRIDGE_MAX_TASK_AGE_SEC", max_age_env)
        import cowork_to_code_bridge.daemon as d
        importlib.reload(d)
        for sub in (d.QUEUE, d.RESULTS, d.PROCESSED,
                    d.INFLIGHT, d.PROGRESS, d.SCRIPTS_DIR):
            sub.mkdir(parents=True, exist_ok=True)
        counter = tmp_path / "counter"
        counter.write_text("0")
        script = d.SCRIPTS_DIR / "increment.sh"
        script.write_text(
            "#!/bin/bash\n"
            f"f={counter}\n"
            "n=$(cat $f)\n"
            "echo $((n+1)) > $f\n"
            "echo ran\n"
        )
        script.chmod(0o755)
        return d, counter

    return _build


def _enqueue(d, cmd_id, age_sec: float, **payload):
    """Queue a task that was submitted `age_sec` seconds ago."""
    p = {"id": cmd_id, "script": "scripts/increment.sh", "args": [],
         "token": "test-token", "timeout": 5,
         "ts_submitted": time.time() - age_sec, **payload}
    f = d.QUEUE / f"{cmd_id}.json"
    f.write_text(json.dumps(p))
    return f


def _ran(counter) -> bool:
    return counter.read_text().strip() != "0"


# ─── the core guarantee: an expired task does not execute ─────────────────────

def test_expired_task_does_not_execute(bridge):
    """A task older than the max age must not run the script at all."""
    d, counter = bridge("60")
    d.run_one(_enqueue(d, "exp_1", age_sec=600), "test-token", {}, {})

    # THE assertion: the side effect never happened.
    assert not _ran(counter), "expired task executed its script anyway"

    res = json.loads((d.RESULTS / "exp_1.json").read_text())
    assert res["exit_code"] == -6
    assert res["expired"] is True
    assert res["max_age_sec"] == 60
    assert res["age_sec"] >= 600


def test_fresh_task_still_executes(bridge):
    """Negative control: same setup, young task — proves the gate is age-based
    and not a blanket 'never run anything'."""
    d, counter = bridge("60")
    d.run_one(_enqueue(d, "fresh_1", age_sec=1), "test-token", {}, {})

    assert _ran(counter), "fresh task was wrongly skipped"
    assert json.loads((d.RESULTS / "fresh_1.json").read_text())["exit_code"] == 0


def test_expiry_disabled_runs_an_ancient_task(bridge):
    """Negative control for the escape hatch: BRIDGE_MAX_TASK_AGE_SEC=0 restores
    the pre-#77 behaviour, so a week-old task still executes.

    This is what makes the positive test meaningful: it proves the skip above
    was caused by the age gate, not by some unrelated failure to run.
    """
    d, counter = bridge("0")
    d.run_one(_enqueue(d, "old_ok", age_sec=7 * 86400), "test-token", {}, {})

    assert _ran(counter), "expiry was disabled but the task still didn't run"
    assert json.loads((d.RESULTS / "old_ok.json").read_text())["exit_code"] == 0


def test_default_max_age_is_one_hour(bridge):
    """Unset env → 3600s default, per the issue."""
    d, _ = bridge(None)
    assert d.MAX_TASK_AGE_SEC == 3600


# ─── result plumbing: expiry reports like any other completion ────────────────

def test_expired_task_is_journaled_and_archived(bridge):
    """An expiry is a normal terminal outcome: journaled, queue file archived,
    no inflight marker left behind."""
    d, _ = bridge("60")
    terminal: dict[str, str] = {}
    d.run_one(_enqueue(d, "exp_j", age_sec=600), "test-token", terminal, {})

    events = [json.loads(ln) for ln in d.JOURNAL.read_text().splitlines()]
    types = [e["event"] for e in events]
    assert "expired" in types
    assert "started" not in types, "daemon journaled a start for an expired task"
    assert terminal["exp_j"] == "expired"
    assert (d.PROCESSED / "exp_j.json").exists()
    assert not (d.QUEUE / "exp_j.json").exists()
    assert not (d.INFLIGHT / "exp_j.running").exists()


def test_expiry_is_checked_before_idempotency_replay(bridge):
    """An expired task must not serve a cached result either.

    The caller that owned that idempotency key is long gone; replaying to it is
    as wrong as executing. Ordering matters, so it gets its own test.
    """
    d, counter = bridge("60")
    cache = {"deploy-key": {"exit_code": 0, "stdout": "cached"}}
    d.run_one(_enqueue(d, "exp_i", age_sec=600, idempotency_key="deploy-key"),
              "test-token", {}, cache)

    res = json.loads((d.RESULTS / "exp_i.json").read_text())
    assert res["exit_code"] == -6, "expired task served the cached result"
    assert not res.get("idempotent_replay")
    assert not _ran(counter)


# ─── per-task override, clamped one-way ───────────────────────────────────────

def test_per_task_max_age_can_be_stricter(bridge):
    """A caller may tighten expiry below the owner default."""
    d, counter = bridge("3600")
    d.run_one(_enqueue(d, "strict_1", age_sec=120, max_age_sec=30),
              "test-token", {}, {})

    assert not _ran(counter), "per-task max_age_sec=30 did not expire a 120s task"
    res = json.loads((d.RESULTS / "strict_1.json").read_text())
    assert res["exit_code"] == -6
    assert res["max_age_sec"] == 30


def test_per_task_max_age_cannot_exceed_owner_ceiling(bridge):
    """A caller may NOT loosen expiry past the owner's ceiling — same one-way
    clamp as the budget and permission ceilings."""
    d, counter = bridge("60")
    d.run_one(_enqueue(d, "loose_1", age_sec=600, max_age_sec=99999),
              "test-token", {}, {})

    assert not _ran(counter), "caller escaped the owner's max-age ceiling"
    assert json.loads((d.RESULTS / "loose_1.json").read_text())["max_age_sec"] == 60


def test_caller_cannot_opt_out_with_zero(bridge):
    """max_age_sec=0 means 'no expiry'. A caller sending it must not thereby
    disable an owner-configured bound."""
    d, counter = bridge("60")
    d.run_one(_enqueue(d, "zero_1", age_sec=600, max_age_sec=0),
              "test-token", {}, {})

    assert not _ran(counter), "caller disabled expiry with max_age_sec=0"
    assert json.loads((d.RESULTS / "zero_1.json").read_text())["exit_code"] == -6


def test_per_task_max_age_applies_when_owner_has_no_default(bridge):
    """With the owner default off, the caller's own bound is the only one — and
    it still has to work."""
    d, counter = bridge("0")
    d.run_one(_enqueue(d, "own_1", age_sec=600, max_age_sec=60),
              "test-token", {}, {})

    assert not _ran(counter)
    assert json.loads((d.RESULTS / "own_1.json").read_text())["exit_code"] == -6


# ─── degenerate timestamps must fail open, not brick the bridge ───────────────

@pytest.mark.parametrize("bad", [None, "not-a-number", 0, -1])
def test_unusable_timestamp_does_not_expire(bridge, bad):
    """Missing/garbage ts_submitted means 'age unknown'. Fail open: an older
    client that predates the stamp must keep working, not have every task
    rejected."""
    d, counter = bridge("60")
    p = {"id": "bad_ts", "script": "scripts/increment.sh", "args": [],
         "token": "test-token", "timeout": 5}
    if bad is not None:
        p["ts_submitted"] = bad
    (d.QUEUE / "bad_ts.json").write_text(json.dumps(p))
    d.run_one(d.QUEUE / "bad_ts.json", "test-token", {}, {})

    assert _ran(counter), f"ts_submitted={bad!r} wrongly expired the task"
    assert json.loads((d.RESULTS / "bad_ts.json").read_text())["exit_code"] == 0


def test_future_timestamp_clamps_to_zero_age(bridge):
    """Clock skew between sandbox and host can put ts_submitted in the future.
    That must read as age 0, never as a negative age or an expiry."""
    d, counter = bridge("60")
    d.run_one(_enqueue(d, "future_1", age_sec=-3600), "test-token", {}, {})

    assert _ran(counter), "a future timestamp was treated as expired"
    assert json.loads((d.RESULTS / "future_1.json").read_text())["exit_code"] == 0


@pytest.mark.parametrize("bad", ["abc", None, -5])
def test_bad_per_task_max_age_falls_back_to_default(bridge, bad):
    """A malformed max_age_sec must fall back to the owner default, never
    silently un-bound the task."""
    d, counter = bridge("60")
    d.run_one(_enqueue(d, "badage", age_sec=600, max_age_sec=bad),
              "test-token", {}, {})

    assert not _ran(counter), f"max_age_sec={bad!r} silently disabled expiry"
    assert json.loads((d.RESULTS / "badage.json").read_text())["max_age_sec"] == 60


# ─── client plumbing ──────────────────────────────────────────────────────────

def test_client_writes_max_age_into_payload(tmp_path):
    """queue_task(max_age_sec=...) has to reach the task file, or none of the
    daemon-side behaviour above is reachable from the public API."""
    from cowork_to_code_bridge.client import queue_task

    root = tmp_path / "bridge"
    (root / "queue").mkdir(parents=True)
    r = queue_task("scripts/ping.sh", bridge_root=root, max_age_sec=120)

    payload = json.loads((root / "queue" / f"{r['task_id']}.json").read_text())
    assert payload["max_age_sec"] == 120.0
    assert "ts_submitted" in payload, "expiry needs a submission timestamp"


def test_client_omits_max_age_when_not_requested(tmp_path):
    """Absent by default, so the daemon default governs."""
    from cowork_to_code_bridge.client import queue_task

    root = tmp_path / "bridge"
    (root / "queue").mkdir(parents=True)
    r = queue_task("scripts/ping.sh", bridge_root=root)

    payload = json.loads((root / "queue" / f"{r['task_id']}.json").read_text())
    assert "max_age_sec" not in payload
