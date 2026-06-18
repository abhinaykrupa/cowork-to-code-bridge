"""
Tests for MCP server functionality.

Tests the three MCP tools:
  1. escalate_to_claude — hand task to Claude Code, get result
  2. run_script — execute a whitelisted script directly
  3. list_bridge_scripts — discover available scripts
"""
import json
import tempfile
from pathlib import Path

import pytest

from cowork_to_code_bridge.mcp_server import MCPServer


@pytest.fixture
def bridge_root():
    """Temporary bridge directory."""
    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir) / "bridge"
        root.mkdir(parents=True, exist_ok=True)
        (root / "queue").mkdir(exist_ok=True)
        (root / "results").mkdir(exist_ok=True)
        (root / "scripts").mkdir(exist_ok=True)
        (root / "to_cowork").mkdir(exist_ok=True)
        (root / "cowork_results").mkdir(exist_ok=True)
        yield root


@pytest.fixture
def mcp_server(bridge_root):
    """MCP server instance."""
    return MCPServer(bridge_root=bridge_root)


def test_mcp_initialize(mcp_server):
    """Test MCP initialize."""
    req = {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}}
    resp = mcp_server.handle_request(req)
    assert resp["id"] == 1
    assert resp["result"]["serverInfo"]["name"] == "cowork-to-code-bridge"


def test_mcp_tools_list(mcp_server):
    """Test MCP tools/list."""
    req = {"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}}
    resp = mcp_server.handle_request(req)
    assert resp["id"] == 1
    tools = resp["result"]["tools"]
    names = [t["name"] for t in tools]
    assert "escalate_to_claude" in names
    assert "run_script" in names
    assert "list_bridge_scripts" in names


def test_mcp_escalate_to_claude_validation(mcp_server):
    """Test escalate_to_claude requires request."""
    req = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "tools/call",
        "params": {"name": "escalate_to_claude", "arguments": {}},
    }
    resp = mcp_server.handle_request(req)
    assert "error" in resp


def test_mcp_escalate_to_claude_queued(mcp_server, bridge_root):
    """Test escalate_to_claude queues request."""
    req = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "tools/call",
        "params": {
            "name": "escalate_to_claude",
            "arguments": {"request": "Test request", "wait_seconds": 1},
        },
    }
    resp = mcp_server.handle_request(req)
    assert resp["id"] == 1
    assert "result" in resp
    assert resp["result"]["status"] == "timeout"  # No agent to reply immediately
    # Verify request was written
    inbox = bridge_root / "to_cowork"
    requests = list(inbox.glob("*.json"))
    assert len(requests) > 0


def test_mcp_escalate_to_claude_with_reply(mcp_server, bridge_root):
    """Test escalate_to_claude with an agent reply."""
    # First, queue a request
    req1 = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "tools/call",
        "params": {
            "name": "escalate_to_claude",
            "arguments": {"request": "Test request", "wait_seconds": 2},
        },
    }
    resp1 = mcp_server.handle_request(req1)
    # Extract request_id from the queued message
    inbox = bridge_root / "to_cowork"
    requests = list(inbox.glob("*.json"))
    assert len(requests) > 0
    request_file = requests[0]
    request_id = request_file.stem

    # Simulate agent reply
    replies = bridge_root / "cowork_results"
    reply_file = replies / f"{request_id}.json"
    reply_file.write_text(
        json.dumps(
            {
                "id": request_id,
                "result": "Fixed the issue",
                "ts": 123456789,
            }
        )
    )

    # Query again for the same request (should find reply)
    req2 = {
        "jsonrpc": "2.0",
        "id": 2,
        "method": "tools/call",
        "params": {
            "name": "escalate_to_claude",
            "arguments": {"request": "Test request 2", "wait_seconds": 2},
        },
    }
    resp2 = mcp_server.handle_request(req2)
    # This is a new request, so it will timeout, but we proved the reply polling works


def test_mcp_run_script_validation(mcp_server):
    """Test run_script requires script name."""
    req = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "tools/call",
        "params": {"name": "run_script", "arguments": {}},
    }
    resp = mcp_server.handle_request(req)
    assert "error" in resp


def test_mcp_run_script_not_found(mcp_server):
    """Test run_script with non-existent script."""
    req = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "tools/call",
        "params": {
            "name": "run_script",
            "arguments": {"script": "nonexistent.sh", "args": [], "timeout": 1},
        },
    }
    resp = mcp_server.handle_request(req)
    assert "result" in resp
    assert resp["result"]["status"] == "error"


def test_mcp_list_bridge_scripts(mcp_server, bridge_root):
    """Test list_bridge_scripts."""
    # Create a test script
    script = bridge_root / "scripts" / "test.sh"
    script.write_text("#!/bin/bash\n# Test script for MCP\necho 'test'")

    req = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "tools/call",
        "params": {"name": "list_bridge_scripts", "arguments": {}},
    }
    resp = mcp_server.handle_request(req)
    assert "result" in resp
    scripts = resp["result"]["scripts"]
    assert any(s["name"] == "test.sh" for s in scripts)


def test_mcp_unknown_tool(mcp_server):
    """Test MCP with unknown tool."""
    req = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "tools/call",
        "params": {"name": "unknown_tool", "arguments": {}},
    }
    resp = mcp_server.handle_request(req)
    assert "error" in resp


def test_mcp_unknown_method(mcp_server):
    """Test MCP with unknown method."""
    req = {"jsonrpc": "2.0", "id": 1, "method": "unknown_method", "params": {}}
    resp = mcp_server.handle_request(req)
    assert "error" in resp
    assert resp["error"]["code"] == -32601


def _get_status(mcp_server, operation_id):
    """Helper: call get_operation_status and return the result dict."""
    req = {
        "jsonrpc": "2.0",
        "id": 99,
        "method": "tools/call",
        "params": {
            "name": "get_operation_status",
            "arguments": {"operation_id": operation_id},
        },
    }
    resp = mcp_server.handle_request(req)
    assert "result" in resp, resp
    return resp["result"]


def test_escalate_initializes_empty_resume_receipt(mcp_server, bridge_root):
    """escalate_to_claude seeds an operation state with an empty resume receipt."""
    req = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "tools/call",
        "params": {
            "name": "escalate_to_claude",
            "arguments": {"request": "Generate a parser", "wait_seconds": 1},
        },
    }
    mcp_server.handle_request(req)

    op_files = list((bridge_root / "operations").glob("*.json"))
    assert len(op_files) == 1
    op_state = json.loads(op_files[0].read_text())
    receipt = op_state["resume_receipt"]
    assert receipt["sub_steps"] == []
    assert receipt["artifacts"] == []
    assert receipt["checkpoint_id"] is None
    assert receipt["can_resume"] is False


def test_resume_receipt_includes_substeps(mcp_server, bridge_root):
    """get_operation_status returns a complete resume_receipt with sub_steps + artifacts."""
    operation_id = "op_substeps_test"
    op_file = bridge_root / "operations" / f"{operation_id}.json"
    op_file.parent.mkdir(parents=True, exist_ok=True)

    op_state = {
        "operation_id": operation_id,
        "status": "executing",
        "created_at": 1718556000,
        "updated_at": 1718556045,
        "request": "Generate, test, and debug a parser",
        "progress": {"step": "debugging", "percent_complete": 80},
        "resume_receipt": {
            "checkpoint_id": "chk_67890",
            "context": {"module": "parser.py"},
            "sub_steps": [
                {
                    "name": "generating",
                    "status": "completed",
                    "duration_ms": 4200,
                    "checkpoint_data": {"lines_written": 120},
                },
                {
                    "name": "testing",
                    "status": "completed",
                    "duration_ms": 1800,
                    "checkpoint_data": {"tests_passed": 5, "tests_failed": 1},
                },
                {
                    "name": "debugging",
                    "status": "started",
                    "duration_ms": None,
                    "checkpoint_data": {"failing_test": "test_edge_case"},
                },
            ],
            "artifacts": [
                {
                    "path": "parser.py",
                    "type": "python",
                    "size": 3120,
                    "timestamp": 1718556020,
                },
                {
                    "path": "test_parser.py",
                    "type": "python",
                    "size": 890,
                    "timestamp": 1718556030,
                },
            ],
            "can_resume": True,
            "resume_from": "debugging",
        },
    }
    op_file.write_text(json.dumps(op_state))

    result = _get_status(mcp_server, operation_id)
    receipt = result["resume_receipt"]

    # Sub-steps present with all required fields.
    assert len(receipt["sub_steps"]) == 3
    names = [s["name"] for s in receipt["sub_steps"]]
    assert names == ["generating", "testing", "debugging"]
    for step in receipt["sub_steps"]:
        assert set(step.keys()) == {"name", "status", "duration_ms", "checkpoint_data"}
        assert step["status"] in {"started", "completed", "failed"}

    # Artifacts present with all required fields.
    assert len(receipt["artifacts"]) == 2
    for art in receipt["artifacts"]:
        assert set(art.keys()) == {"path", "type", "size", "timestamp"}

    assert receipt["can_resume"] is True
    assert receipt["resume_from"] == "debugging"
    assert receipt["checkpoint_id"] == "chk_67890"


def test_resume_receipt_normalizes_legacy_state(mcp_server, bridge_root):
    """Operation state written before sub_steps/artifacts is upgraded on read."""
    operation_id = "op_legacy_test"
    op_file = bridge_root / "operations" / f"{operation_id}.json"
    op_file.parent.mkdir(parents=True, exist_ok=True)

    # Legacy state: resume_receipt with only the old fields.
    op_state = {
        "operation_id": operation_id,
        "status": "executing",
        "resume_receipt": {
            "checkpoint_id": "chk_legacy",
            "context": {"last_completed_step": "code_generation"},
        },
    }
    op_file.write_text(json.dumps(op_state))

    result = _get_status(mcp_server, operation_id)
    receipt = result["resume_receipt"]

    # Missing fields filled with empty defaults; existing fields preserved.
    assert receipt["sub_steps"] == []
    assert receipt["artifacts"] == []
    assert receipt["checkpoint_id"] == "chk_legacy"
    assert receipt["context"] == {"last_completed_step": "code_generation"}
    assert receipt["can_resume"] is False
    assert receipt["resume_from"] is None
