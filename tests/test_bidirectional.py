"""
tests/test_bidirectional.py — unit tests for the interactive bidirectional loop.

feat: interactive bidirectional loop (Claude Code → Cowork → Claude Code)

Tests:
  1. happy_path           — question detected → reply written → resume returns result
  2. timeout_exit_1       — request_cowork.sh timeout must exit 1, not exit 0
  3. idempotency_resume   — resumed task uses existing result, not re-run
  4. parallel_tasks       — two tasks each ask a question; replies don't cross-contaminate
  5. daemon_injects_cmd_id — daemon.py sets BRIDGE_CMD_ID in child env
  6. parent_field_present — request_cowork.sh includes parent field
"""
from __future__ import annotations

import json
import time
from pathlib import Path

import pytest

# ---------------------------------------------------------------------------
# Import client helpers
# ---------------------------------------------------------------------------
try:
    from cowork_to_code_bridge.client import reply_to_machine, resume_remote
except ImportError:
    import sys
    sys.path.insert(0, str(Path(__file__).parent.parent))
    from cowork_to_code_bridge.client import reply_to_machine, resume_remote  # type: ignore

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def bridge_root(tmp_path):
    root = tmp_path / "bridge"
    for d in ("queue", "results", "progress", "to_cowork", "cowork_results",
              "processed", "inflight"):
        (root / d).mkdir(parents=True)
    return root


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _drop_question(root: Path, request_id: str, question: str, parent: str) -> None:
    payload = {"id": request_id, "request": question, "ts": time.time(),
               "from": "claude-code", "parent": parent}
    out = root / "to_cowork" / f"{request_id}.json"
    tmp = out.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(payload))
    tmp.rename(out)


def _drop_result(root: Path, cmd_id: str, exit_code: int = 0, stdout: str = "done") -> None:
    payload = {"id": cmd_id, "exit_code": exit_code, "stdout": stdout,
               "stderr": "", "ts_completed": time.time()}
    out = root / "results" / f"{cmd_id}.json"
    tmp = out.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(payload))
    tmp.rename(out)


def _read_reply(root: Path, request_id: str) -> dict:
    return json.loads((root / "cowork_results" / f"{request_id}.json").read_text())


def _scan_question(root: Path, cmd_id: str) -> dict | None:
    """Simulate the interactive poll: find a to_cowork file with parent==cmd_id.

    Renames the file to .json.answered on detection, matching what the real
    client does — prevents resume_remote from re-detecting the same question.
    """
    for f in sorted((root / "to_cowork").glob("*.json")):
        try:
            data = json.loads(f.read_text())
        except (OSError, json.JSONDecodeError):
            continue
        if data.get("parent") == cmd_id:
            f.rename(f.with_suffix(".json.answered"))
            return data
    return None


# ---------------------------------------------------------------------------
# 1. Happy path
# ---------------------------------------------------------------------------

def test_happy_path(bridge_root):
    cmd_id = "1234567890_happypath"
    req_id = "1234567890_req1"
    deadline = time.time() + 30.0

    # Script drops a question
    _drop_question(bridge_root, req_id, "Deploy to production?", cmd_id)

    # Interactive poll detects it
    found = _scan_question(bridge_root, cmd_id)
    assert found is not None
    assert found["request"] == "Deploy to production?"

    # Build awaiting_reply shape (as call_remote_streaming would)
    ar = {
        "state": "awaiting_reply",
        "cmd_id": cmd_id,
        "request_id": found["id"],
        "question": found["request"],
        "from": found["from"],
        "_deadline": deadline,
        "_bridge_root": str(bridge_root),
    }

    # Cowork answers
    reply_to_machine(ar["request_id"], "yes", bridge_root=bridge_root)
    reply = _read_reply(bridge_root, req_id)
    assert reply["reply"] == "yes"
    assert reply["from"] == "cowork"
    assert reply["id"] == req_id

    # Result lands (simulating the script unblocking after getting the reply)
    _drop_result(bridge_root, cmd_id, stdout="deployed successfully")

    # resume_remote picks up the result
    final = resume_remote(ar["cmd_id"], ar["_deadline"],
                          poll_interval=0.02, bridge_root=bridge_root)
    assert final["exit_code"] == 0
    assert "deployed" in final["stdout"]


# ---------------------------------------------------------------------------
# 2. Timeout exit 1
# ---------------------------------------------------------------------------

def test_timeout_exit_1():
    """request_cowork.sh and install.sh heredoc must exit 1 on --wait timeout."""
    repo = Path(__file__).parent.parent

    script = (repo / "examples" / "allowed_scripts" / "request_cowork.sh").read_text()
    assert "exit 1" in script, "examples/request_cowork.sh must exit 1 on timeout"
    assert "exit 0" in script, "examples/request_cowork.sh must still exit 0 on success"

    install = (repo / "install.sh").read_text()
    start = install.find("<<'REQCW'")
    end = install.find("REQCW", start + 10)
    assert start >= 0
    heredoc = install[start:end]
    assert "exit 1" in heredoc, "install.sh REQCW heredoc must exit 1 on timeout"


# ---------------------------------------------------------------------------
# 3. Idempotency with resume
# ---------------------------------------------------------------------------

def test_idempotency_resume(bridge_root):
    """resume_remote must return existing result without re-running the task."""
    cmd_id = "1234567890_idem"
    req_id = "1234567890_req_idem"

    reply_to_machine(req_id, "approved", bridge_root=bridge_root)
    _drop_result(bridge_root, cmd_id, stdout="original output")

    deadline = time.time() + 30.0
    r = resume_remote(cmd_id, deadline, poll_interval=0.02, bridge_root=bridge_root)
    assert r["exit_code"] == 0
    assert r["stdout"] == "original output"


# ---------------------------------------------------------------------------
# 4. Parallel task correlation
# ---------------------------------------------------------------------------

def test_parallel_task_correlation(bridge_root):
    """Two tasks ask questions; each gets only its own reply."""
    cmd_a = "1234567890_taskA"
    cmd_b = "1234567890_taskB"
    req_a = "1234567890_reqA"
    req_b = "1234567890_reqB"

    _drop_question(bridge_root, req_a, "Approve A?", cmd_a)
    _drop_question(bridge_root, req_b, "Approve B?", cmd_b)

    q_a = _scan_question(bridge_root, cmd_a)
    q_b = _scan_question(bridge_root, cmd_b)

    assert q_a is not None and q_a["request"] == "Approve A?"
    assert q_b is not None and q_b["request"] == "Approve B?"
    assert q_a["id"] == req_a
    assert q_b["id"] == req_b

    reply_to_machine(req_a, "yes for A", bridge_root=bridge_root)
    reply_to_machine(req_b, "no for B", bridge_root=bridge_root)

    r_a = _read_reply(bridge_root, req_a)
    r_b = _read_reply(bridge_root, req_b)

    assert r_a["reply"] == "yes for A"
    assert r_b["reply"] == "no for B"
    assert r_a["id"] == req_a
    assert r_b["id"] == req_b


# ---------------------------------------------------------------------------
# 5. daemon.py injects BRIDGE_CMD_ID
# ---------------------------------------------------------------------------

def test_daemon_injects_bridge_cmd_id():
    src = (Path(__file__).parent.parent / "daemon" / "daemon.py").read_text()
    assert 'env["BRIDGE_CMD_ID"] = cmd_id' in src, (
        "daemon.py must inject BRIDGE_CMD_ID into the child process environment"
    )


# ---------------------------------------------------------------------------
# 6. request_cowork.sh includes parent field
# ---------------------------------------------------------------------------

def test_request_cowork_parent_field():
    repo = Path(__file__).parent.parent
    script = (repo / "examples" / "allowed_scripts" / "request_cowork.sh").read_text()
    assert "parent" in script
    assert "BRIDGE_CMD_ID" in script
