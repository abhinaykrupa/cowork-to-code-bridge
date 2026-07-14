"""
mcp_server.py — stdio MCP server for cowork-to-code-bridge.

Exposes the bridge as an MCP tool server so any MCP-compatible agent
(Hermes, OpenClaw, Claude Desktop, etc.) can call:

  • escalate_to_claude  — submit a task/question to the Claude Code agent
  • call_remote         — run any whitelisted script via the bridge
  • daemon_alive        — health-check the daemon
  • call_mcp_tool       — proxy a call to a registered stdio MCP server

Zero external dependencies (stdlib only).  Speaks JSON-RPC 2.0 over stdio
exactly as the MCP spec requires.

Usage:
    cowork-to-code-bridge-mcp --stdio
    python -m cowork_to_code_bridge.mcp_server --stdio

Hermes config (examples/hermes-mcp-config.json):
    {
      "mcpServers": {
        "cowork": {
          "command": "cowork-to-code-bridge-mcp",
          "args": ["--stdio"]
        }
      }
    }
"""
from __future__ import annotations

import json
import sys
import traceback
from typing import Any

from cowork_to_code_bridge.client import (
    call_mcp_tool as _call_mcp_tool,
)
from cowork_to_code_bridge.client import (
    call_remote as _call_remote,
)
from cowork_to_code_bridge.client import (
    daemon_alive as _daemon_alive,
)

__version__ = "0.5.1"
PROTOCOL_VERSION = "2024-11-05"

# ---------------------------------------------------------------------------
# Tool definitions (MCP inputSchema format)
# ---------------------------------------------------------------------------

TOOLS: list[dict[str, Any]] = [
    {
        "name": "escalate_to_claude",
        "description": (
            "Submit a task or question to the Claude Code agent running on your computer "
            "via the cowork-to-code-bridge daemon.  The agent runs the task in a local "
            "environment with full file/shell access, then returns stdout, stderr, and "
            "exit_code.  Use this to delegate debugging, coding, or file-system work to "
            "your local Claude Code instance."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "task": {
                    "type": "string",
                    "description": (
                        "The task or question for Claude Code.  Be specific — include "
                        "repo paths, error messages, or exact filenames where relevant."
                    ),
                },
                "cwd": {
                    "type": "string",
                    "description": "Working directory on the host machine (optional).",
                },
                "timeout": {
                    "type": "integer",
                    "description": "Timeout in seconds.  Default: 300.",
                    "default": 300,
                },
                "max_budget_usd": {
                    "type": "number",
                    "description": "Per-task spend ceiling for run_claude.sh (optional).",
                },
                "plan": {
                    "type": "string",
                    "description": (
                        "Plain-English description of what the task will do.  "
                        "Shown to the human if approve_plan.sh is installed."
                    ),
                },
                "permission_scope": {
                    "type": "string",
                    "enum": ["plan", "readonly", "edit", "full"],
                    "description": (
                        "Per-task permission scope (least→most permissive: plan, "
                        "readonly, edit, full).  Clamped down to the owner's "
                        "BRIDGE_PERMISSION_CEILING; ignored if the owner set a "
                        "global CLAUDE_FLAGS.  Optional."
                    ),
                },
            },
            "required": ["task"],
        },
    },
    {
        "name": "call_remote",
        "description": (
            "Run any whitelisted script on the host machine via the bridge daemon and "
            "return its result.  The script must be in the daemon's allowed-scripts "
            "directory (typically ~/.cowork-to-code-bridge/scripts/)."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "script": {
                    "type": "string",
                    "description": "Relative path to the script, e.g. 'scripts/ping.sh'.",
                },
                "args": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Positional arguments for the script.",
                    "default": [],
                },
                "timeout": {
                    "type": "integer",
                    "description": "Timeout in seconds.  Default: 60.",
                    "default": 60,
                },
                "cwd": {
                    "type": "string",
                    "description": "Working directory on the host machine (optional).",
                },
                "idempotency_key": {
                    "type": "string",
                    "description": "Stable key for safe retries — same key returns cached result.",
                },
            },
            "required": ["script"],
        },
    },
    {
        "name": "daemon_alive",
        "description": (
            "Return true if the cowork-to-code-bridge daemon is reachable on the host "
            "machine, false otherwise.  Use this as a health-check before submitting work."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "ping_timeout": {
                    "type": "integer",
                    "description": "Seconds to wait for a ping response.  Default: 10.",
                    "default": 10,
                },
            },
            "required": [],
        },
    },
    {
        "name": "call_mcp_tool",
        "description": (
            "Proxy a JSON-RPC call to a stdio MCP server registered on the host machine "
            "via mcp_register.sh.  Useful for reaching local MCP servers (e.g. filesystem, "
            "postgres) that only exist on the host."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "server": {
                    "type": "string",
                    "description": "Name of the registered MCP server (e.g. 'filesystem').",
                },
                "method": {
                    "type": "string",
                    "description": "MCP JSON-RPC method (e.g. 'tools/list', 'tools/call').",
                },
                "params": {
                    "type": "object",
                    "description": "Method parameters (optional).",
                },
            },
            "required": ["server", "method"],
        },
    },
]

# ---------------------------------------------------------------------------
# Tool handlers
# ---------------------------------------------------------------------------


def _handle_escalate_to_claude(args: dict[str, Any]) -> dict[str, Any]:
    task = args["task"]
    timeout = int(args.get("timeout", 300))
    cwd = args.get("cwd")
    max_budget_usd = args.get("max_budget_usd")
    plan = args.get("plan")
    permission_scope = args.get("permission_scope")

    result = _call_remote(
        script="scripts/run_claude.sh",
        args=[task],
        timeout=timeout,
        cwd=cwd,
        plan=plan,
        max_budget_usd=max_budget_usd,
        permission_scope=permission_scope,
    )
    return result


def _handle_call_remote(args: dict[str, Any]) -> dict[str, Any]:
    return _call_remote(
        script=args["script"],
        args=args.get("args", []),
        timeout=int(args.get("timeout", 60)),
        cwd=args.get("cwd"),
        idempotency_key=args.get("idempotency_key"),
    )


def _handle_daemon_alive(args: dict[str, Any]) -> dict[str, Any]:
    alive = _daemon_alive(ping_timeout=int(args.get("ping_timeout", 10)))
    return {"alive": alive}


def _handle_call_mcp_tool(args: dict[str, Any]) -> dict[str, Any]:
    return _call_mcp_tool(
        server=args["server"],
        method=args["method"],
        params=args.get("params"),
    )


_HANDLERS = {
    "escalate_to_claude": _handle_escalate_to_claude,
    "call_remote": _handle_call_remote,
    "daemon_alive": _handle_daemon_alive,
    "call_mcp_tool": _handle_call_mcp_tool,
}

# ---------------------------------------------------------------------------
# JSON-RPC 2.0 / MCP protocol helpers
# ---------------------------------------------------------------------------


def _send(msg: dict[str, Any]) -> None:
    """Write a JSON-RPC message to stdout (one line, newline-terminated)."""
    sys.stdout.write(json.dumps(msg) + "\n")
    sys.stdout.flush()


def _ok(req_id: Any, result: Any) -> None:
    _send({"jsonrpc": "2.0", "id": req_id, "result": result})


def _err(req_id: Any, code: int, message: str, data: Any = None) -> None:
    err: dict[str, Any] = {"code": code, "message": message}
    if data is not None:
        err["data"] = data
    _send({"jsonrpc": "2.0", "id": req_id, "error": err})


# ---------------------------------------------------------------------------
# Request dispatcher
# ---------------------------------------------------------------------------


def _dispatch(req: dict[str, Any]) -> None:
    method = req.get("method", "")
    req_id = req.get("id")  # None for notifications
    params = req.get("params") or {}

    # Notifications (no id) — just ack silently
    if req_id is None:
        return

    try:
        if method == "initialize":
            _ok(
                req_id,
                {
                    "protocolVersion": PROTOCOL_VERSION,
                    "capabilities": {"tools": {}},
                    "serverInfo": {
                        "name": "cowork-to-code-bridge",
                        "version": __version__,
                    },
                },
            )

        elif method == "tools/list":
            _ok(req_id, {"tools": TOOLS})

        elif method == "tools/call":
            name = params.get("name", "")
            arguments = params.get("arguments") or {}

            if name not in _HANDLERS:
                _err(req_id, -32601, f"Unknown tool: {name!r}")
                return

            try:
                result = _HANDLERS[name](arguments)
                # MCP tools/call returns content array
                content_text = json.dumps(result, indent=2)
                _ok(
                    req_id,
                    {
                        "content": [{"type": "text", "text": content_text}],
                        "isError": False,
                    },
                )
            except TimeoutError as exc:
                _ok(
                    req_id,
                    {
                        "content": [{"type": "text", "text": f"TimeoutError: {exc}"}],
                        "isError": True,
                    },
                )
            except Exception as exc:
                tb = traceback.format_exc()
                _ok(
                    req_id,
                    {
                        "content": [
                            {
                                "type": "text",
                                "text": f"Error calling {name!r}: {exc}\n{tb}",
                            }
                        ],
                        "isError": True,
                    },
                )

        elif method == "ping":
            _ok(req_id, {})

        else:
            _err(req_id, -32601, f"Method not found: {method!r}")

    except Exception as exc:
        _err(req_id, -32603, f"Internal error: {exc}", traceback.format_exc())


# ---------------------------------------------------------------------------
# Main loop
# ---------------------------------------------------------------------------


def run_stdio() -> None:
    """Read JSON-RPC messages from stdin (one per line) and dispatch them."""
    print(  # noqa: T201  (informational stderr only)
        f"cowork-to-code-bridge MCP server v{__version__} ready (stdio)",
        file=sys.stderr,
    )

    for raw_line in sys.stdin:
        line = raw_line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except json.JSONDecodeError as exc:
            _err(None, -32700, f"Parse error: {exc}")
            continue

        if not isinstance(msg, dict):
            _err(None, -32600, "Invalid Request: not an object")
            continue

        _dispatch(msg)


def main() -> None:
    if "--stdio" not in sys.argv and len(sys.argv) < 2:
        print(
            "Usage: cowork-to-code-bridge-mcp --stdio\n\n"
            "Starts the MCP server in stdio mode for use with Hermes, OpenClaw,\n"
            "Claude Desktop, or any MCP-compatible client.\n\n"
            "Tools exposed:\n"
            + "\n".join(f"  • {t['name']}" for t in TOOLS),
            file=sys.stderr,
        )
        sys.exit(1)

    run_stdio()


if __name__ == "__main__":
    main()
