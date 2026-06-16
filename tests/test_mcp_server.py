"""
tests/test_mcp_server.py — unit tests for the cowork-to-code-bridge MCP server.

Tests the JSON-RPC 2.0 / MCP protocol layer without requiring a live daemon.
"""
from __future__ import annotations

import json
import subprocess
import sys
import textwrap
from pathlib import Path

REPO = Path(__file__).parent.parent
MCP_MODULE = REPO / "cowork_to_code_bridge" / "mcp_server.py"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _send_recv(messages: list[dict], timeout: int = 10) -> list[dict]:
    """Spawn the MCP server, send messages, collect responses, return them."""
    proc = subprocess.Popen(
        [sys.executable, str(MCP_MODULE), "--stdio"],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    payload = "\n".join(json.dumps(m) for m in messages) + "\n"
    try:
        stdout, _ = proc.communicate(input=payload, timeout=timeout)
    except subprocess.TimeoutExpired:
        proc.kill()
        raise

    responses = []
    for line in stdout.splitlines():
        line = line.strip()
        if line:
            responses.append(json.loads(line))
    return responses


def _rpc(method: str, params: dict | None = None, req_id: int = 1) -> dict:
    msg: dict = {"jsonrpc": "2.0", "id": req_id, "method": method}
    if params is not None:
        msg["params"] = params
    return msg


def _notification(method: str, params: dict | None = None) -> dict:
    msg: dict = {"jsonrpc": "2.0", "method": method}
    if params is not None:
        msg["params"] = params
    return msg


# ---------------------------------------------------------------------------
# Protocol tests
# ---------------------------------------------------------------------------

def test_mcp_server_initialize() -> None:
    """initialize returns protocolVersion, capabilities, serverInfo."""
    responses = _send_recv([
        _rpc("initialize", {
            "protocolVersion": "2024-11-05",
            "capabilities": {},
            "clientInfo": {"name": "test", "version": "0.0.1"},
        }),
    ])
    assert len(responses) == 1
    r = responses[0]
    assert r["id"] == 1
    assert "result" in r
    result = r["result"]
    assert result["protocolVersion"] == "2024-11-05"
    assert "tools" in result["capabilities"]
    assert result["serverInfo"]["name"] == "cowork-to-code-bridge"


def test_mcp_server_tools_list() -> None:
    """tools/list returns all expected tools with valid schemas."""
    responses = _send_recv([
        _rpc("initialize", {"protocolVersion": "2024-11-05", "capabilities": {}, "clientInfo": {"name": "t", "version": "0"}}, req_id=1),
        _notification("notifications/initialized"),
        _rpc("tools/list", {}, req_id=2),
    ])
    # Notifications produce no response; we should have 2 responses (init + tools/list)
    by_id = {r["id"]: r for r in responses}
    assert 2 in by_id
    tools = by_id[2]["result"]["tools"]
    names = {t["name"] for t in tools}
    assert "escalate_to_claude" in names
    assert "call_remote" in names
    assert "daemon_alive" in names
    assert "call_mcp_tool" in names
    for tool in tools:
        assert "description" in tool
        assert "inputSchema" in tool
        assert tool["inputSchema"]["type"] == "object"


def test_mcp_server_unknown_method() -> None:
    """Unknown methods return a -32601 error."""
    responses = _send_recv([_rpc("no_such_method", {}, req_id=99)])
    assert responses[0]["id"] == 99
    assert responses[0]["error"]["code"] == -32601


def test_mcp_server_unknown_tool() -> None:
    """tools/call with an unknown tool name returns isError=True."""
    responses = _send_recv([
        _rpc("initialize", {"protocolVersion": "2024-11-05", "capabilities": {}, "clientInfo": {"name": "t", "version": "0"}}, req_id=1),
        _rpc("tools/call", {"name": "does_not_exist", "arguments": {}}, req_id=2),
    ])
    by_id = {r["id"]: r for r in responses}
    assert 2 in by_id
    # Unknown tool → -32601 error at the JSON-RPC level
    assert "error" in by_id[2]
    assert by_id[2]["error"]["code"] == -32601


def test_mcp_server_parse_error() -> None:
    """Malformed JSON returns a -32700 parse error."""
    proc = subprocess.Popen(
        [sys.executable, str(MCP_MODULE), "--stdio"],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    stdout, _ = proc.communicate(input="not json\n", timeout=5)
    resp = json.loads(stdout.strip())
    assert resp["error"]["code"] == -32700


def test_mcp_server_ping() -> None:
    """ping responds with empty result."""
    responses = _send_recv([_rpc("ping", {}, req_id=7)])
    assert responses[0]["id"] == 7
    assert responses[0]["result"] == {}


def test_mcp_server_notification_no_response() -> None:
    """Notifications (no id) produce no response line."""
    responses = _send_recv([
        _notification("notifications/initialized"),
        _rpc("ping", {}, req_id=5),
    ])
    # Only ping gets a response
    assert len(responses) == 1
    assert responses[0]["id"] == 5


def test_mcp_server_daemon_alive_timeout_is_error() -> None:
    """daemon_alive with a real call returns isError=False but alive=False when no daemon."""
    # In CI there's no daemon, so alive=False — but the call itself must not crash.
    responses = _send_recv([
        _rpc("initialize", {"protocolVersion": "2024-11-05", "capabilities": {}, "clientInfo": {"name": "t", "version": "0"}}, req_id=1),
        _rpc("tools/call", {"name": "daemon_alive", "arguments": {"ping_timeout": 2}}, req_id=2),
    ])
    by_id = {r["id"]: r for r in responses}
    assert 2 in by_id
    result = by_id[2]["result"]
    # No daemon in CI — should return isError=False (timeout handled gracefully)
    assert result["isError"] is False
    payload = json.loads(result["content"][0]["text"])
    assert "alive" in payload
    assert payload["alive"] is False


def test_mcp_server_no_args_prints_usage() -> None:
    """Running without --stdio prints usage to stderr and exits 1."""
    proc = subprocess.run(
        [sys.executable, str(MCP_MODULE)],
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 1
    assert "--stdio" in proc.stderr
