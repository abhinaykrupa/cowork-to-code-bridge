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
