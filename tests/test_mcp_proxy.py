"""
tests/test_mcp_proxy.py — tests for mcp_proxy.sh, mcp_register.sh, mcp_list_servers.sh.

Coverage:
  - Template sync: examples/allowed_scripts/ matches install.sh heredocs
  - mcp_list_servers.sh: empty registry, --json flag
  - mcp_register.sh: register a server, remove a server, --list
  - mcp_proxy.sh: unknown server returns error JSON (exit 0), exits 0 always,
                  valid response from a fake stdio MCP echo server
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import textwrap
from pathlib import Path


REPO = Path(__file__).parent.parent
EXAMPLES = REPO / "examples" / "allowed_scripts"
INSTALL_SH = REPO / "install.sh"


# ── Helpers ───────────────────────────────────────────────────────────────────

def _extract_heredoc(marker: str) -> str:
    """Extract content between <<'MARKER' … MARKER in install.sh."""
    text = INSTALL_SH.read_text()
    pattern = rf"<<'{re.escape(marker)}'\n(.*?)\n{re.escape(marker)}"
    m = re.search(pattern, text, re.DOTALL)
    assert m, f"Heredoc marker '{marker}' not found in install.sh"
    return m.group(1)


def _run(script: Path, args: list[str], env: dict | None = None) -> subprocess.CompletedProcess:
    e = {**os.environ, **(env or {})}
    return subprocess.run(
        ["bash", str(script)] + args,
        capture_output=True, text=True, env=e,
    )


# ── Template sync ─────────────────────────────────────────────────────────────

def test_mcp_proxy_template_sync():
    """examples/allowed_scripts/mcp_proxy.sh must match the MCPPROXY heredoc."""
    heredoc = _extract_heredoc("MCPPROXY")
    actual  = (EXAMPLES / "mcp_proxy.sh").read_text().rstrip("\n")
    assert actual == heredoc, (
        "mcp_proxy.sh is out of sync with the MCPPROXY heredoc in install.sh. "
        "Update both files together."
    )


def test_mcp_register_template_sync():
    """examples/allowed_scripts/mcp_register.sh must match the MCPREG heredoc."""
    heredoc = _extract_heredoc("MCPREG")
    actual  = (EXAMPLES / "mcp_register.sh").read_text().rstrip("\n")
    assert actual == heredoc, (
        "mcp_register.sh is out of sync with the MCPREG heredoc in install.sh."
    )


def test_mcp_list_servers_template_sync():
    """examples/allowed_scripts/mcp_list_servers.sh must match the MCPLIST heredoc."""
    heredoc = _extract_heredoc("MCPLIST")
    actual  = (EXAMPLES / "mcp_list_servers.sh").read_text().rstrip("\n")
    assert actual == heredoc, (
        "mcp_list_servers.sh is out of sync with the MCPLIST heredoc in install.sh."
    )


# ── mcp_list_servers.sh ───────────────────────────────────────────────────────

def test_mcp_list_servers_empty_registry(tmp_path: Path) -> None:
    """With no registry file, --json returns valid JSON with empty servers."""
    script = EXAMPLES / "mcp_list_servers.sh"
    result = _run(script, ["--json"], {"BRIDGE_MCP_REGISTRY": str(tmp_path / "reg.json")})
    assert result.returncode == 0
    data = json.loads(result.stdout)
    assert data["count"] == 0
    assert data["servers"] == {}


def test_mcp_list_servers_human_readable_empty(tmp_path: Path) -> None:
    """With no registry file, human-readable output mentions how to register."""
    script = EXAMPLES / "mcp_list_servers.sh"
    result = _run(script, [], {"BRIDGE_MCP_REGISTRY": str(tmp_path / "reg.json")})
    assert result.returncode == 0
    assert "mcp_register" in result.stdout.lower() or "register" in result.stdout.lower()


# ── mcp_register.sh ───────────────────────────────────────────────────────────

def test_mcp_register_adds_server(tmp_path: Path) -> None:
    """Registering a server writes it to the registry JSON."""
    reg = tmp_path / "reg.json"
    script = EXAMPLES / "mcp_register.sh"
    result = _run(script, [
        "--name", "filesystem",
        "--command", "npx",
        "--args", '["-y","@modelcontextprotocol/server-filesystem","/tmp"]',
    ], {"BRIDGE_MCP_REGISTRY": str(reg)})
    assert result.returncode == 0
    assert reg.exists()
    data = json.load(reg.open())
    assert "filesystem" in data
    assert data["filesystem"]["command"] == "npx"
    assert data["filesystem"]["args"] == ["-y", "@modelcontextprotocol/server-filesystem", "/tmp"]


def test_mcp_register_remove_server(tmp_path: Path) -> None:
    """--remove deletes a server from the registry."""
    reg = tmp_path / "reg.json"
    reg.write_text(json.dumps({"myserver": {"command": "echo", "args": [], "env": {}}}))
    script = EXAMPLES / "mcp_register.sh"
    result = _run(script, ["--remove", "myserver"], {"BRIDGE_MCP_REGISTRY": str(reg)})
    assert result.returncode == 0
    data = json.load(reg.open())
    assert "myserver" not in data


def test_mcp_register_remove_unknown_fails(tmp_path: Path) -> None:
    """--remove on a non-existent server exits non-zero."""
    reg = tmp_path / "reg.json"
    reg.write_text("{}")
    script = EXAMPLES / "mcp_register.sh"
    result = _run(script, ["--remove", "ghost"], {"BRIDGE_MCP_REGISTRY": str(reg)})
    assert result.returncode != 0


def test_mcp_register_list(tmp_path: Path) -> None:
    """--list outputs registered server names."""
    reg = tmp_path / "reg.json"
    reg.write_text(json.dumps({"pg": {"command": "uvx", "args": [], "env": {}}}))
    script = EXAMPLES / "mcp_register.sh"
    result = _run(script, ["--list"], {"BRIDGE_MCP_REGISTRY": str(reg)})
    assert result.returncode == 0
    assert "pg" in result.stdout


# ── mcp_proxy.sh ─────────────────────────────────────────────────────────────

def test_mcp_proxy_exits_zero_always(tmp_path: Path) -> None:
    """mcp_proxy.sh exits 0 even when no registry exists."""
    script = EXAMPLES / "mcp_proxy.sh"
    result = _run(script, [
        "--server", "missing",
        "--method", "tools/list",
    ], {"BRIDGE_MCP_REGISTRY": str(tmp_path / "reg.json")})
    assert result.returncode == 0


def test_mcp_proxy_unknown_server_returns_error_json(tmp_path: Path) -> None:
    """An unknown server name produces valid JSON with an error field."""
    reg = tmp_path / "reg.json"
    reg.write_text("{}")
    script = EXAMPLES / "mcp_proxy.sh"
    result = _run(script, [
        "--server", "ghost",
        "--method", "tools/list",
        "--params", "{}",
    ], {"BRIDGE_MCP_REGISTRY": str(reg)})
    assert result.returncode == 0
    data = json.loads(result.stdout)
    assert "error" in data
    assert "ghost" in data["error"]["message"]


def test_mcp_proxy_missing_registry_returns_error_json(tmp_path: Path) -> None:
    """No registry file → valid JSON error, exit 0."""
    script = EXAMPLES / "mcp_proxy.sh"
    result = _run(script, [
        "--server", "any",
        "--method", "tools/list",
    ], {"BRIDGE_MCP_REGISTRY": str(tmp_path / "nonexistent.json")})
    assert result.returncode == 0
    data = json.loads(result.stdout)
    assert "error" in data


def test_mcp_proxy_bad_command_returns_error_json(tmp_path: Path) -> None:
    """If the registered command doesn't exist, proxy returns error JSON, exit 0."""
    reg = tmp_path / "reg.json"
    reg.write_text(json.dumps({
        "badserver": {"command": "/nonexistent/binary", "args": [], "env": {}}
    }))
    script = EXAMPLES / "mcp_proxy.sh"
    result = _run(script, [
        "--server", "badserver",
        "--method", "tools/list",
        "--params", "{}",
    ], {"BRIDGE_MCP_REGISTRY": str(reg)})
    assert result.returncode == 0
    data = json.loads(result.stdout)
    assert "error" in data


def test_mcp_proxy_real_echo_server(tmp_path: Path) -> None:
    """A fake stdio MCP server that returns a valid JSON-RPC response is relayed correctly."""
    # Write a fake MCP server: reads JSON-RPC lines, responds to initialize then tools/list.
    fake_server = tmp_path / "fake_mcp_server.py"
    fake_server.write_text(textwrap.dedent("""\
        #!/usr/bin/env python3
        import sys, json

        for line in sys.stdin:
            line = line.strip()
            if not line:
                continue
            try:
                req = json.loads(line)
            except Exception:
                continue
            method = req.get("method", "")
            req_id = req.get("id")

            if method == "initialize":
                resp = {
                    "jsonrpc": "2.0", "id": req_id,
                    "result": {
                        "protocolVersion": "2024-11-05",
                        "capabilities": {},
                        "serverInfo": {"name": "fake-mcp", "version": "0.1"},
                    }
                }
                print(json.dumps(resp), flush=True)
            elif method == "notifications/initialized":
                pass  # notification, no response
            elif method == "tools/list":
                resp = {
                    "jsonrpc": "2.0", "id": req_id,
                    "result": {
                        "tools": [{"name": "echo_tool", "description": "echoes input"}]
                    }
                }
                print(json.dumps(resp), flush=True)
                break
            else:
                resp = {
                    "jsonrpc": "2.0", "id": req_id,
                    "error": {"code": -32601, "message": f"Method not found: {method}"}
                }
                print(json.dumps(resp), flush=True)
    """))
    fake_server.chmod(0o755)

    reg = tmp_path / "reg.json"
    reg.write_text(json.dumps({
        "fake": {"command": "python3", "args": [str(fake_server)], "env": {}}
    }))

    script = EXAMPLES / "mcp_proxy.sh"
    result = _run(script, [
        "--server", "fake",
        "--method", "tools/list",
        "--params", "{}",
    ], {"BRIDGE_MCP_REGISTRY": str(reg)})

    assert result.returncode == 0
    data = json.loads(result.stdout)
    assert "error" not in data, f"Unexpected error: {data}"
    assert "result" in data
    tools = data["result"]["tools"]
    assert any(t["name"] == "echo_tool" for t in tools)
