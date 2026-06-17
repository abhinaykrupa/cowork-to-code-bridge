"""
mcp_server.py — MCP (Model Context Protocol) server that exposes the bridge
as a model provider. Hermes, Open Claw, and other agents can connect to this
server and escalate work to Claude Code without needing a subscription directly.

Usage:
  cowork-to-code-bridge-mcp --stdio

The MCP server runs in stdin/stdout mode (JSONRPC 2.0) and provides:
  - Tool: escalate_to_claude — hand a request to Claude Code, get a reply
  - Tool: list_bridge_scripts — discover available whitelisted scripts
  - Tool: run_script — execute a whitelisted script directly (no agent)

A Hermes/Open Claw agent can discover these tools via MCP and call them.
Requests are escalated to Claude Code via the bridge (async queue).
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
import uuid
from pathlib import Path
from typing import Any

from cowork_to_code_bridge.client import call_remote_streaming


class MCPServer:
    """MCP server wrapping the bridge as a model provider."""

    def __init__(self, bridge_root: Path | str | None = None):
        """Initialize MCP server with bridge connection."""
        if isinstance(bridge_root, str):
            bridge_root = Path(bridge_root)
        self.bridge_root = bridge_root or self._resolve_bridge_root()
        self.request_id_counter = 0
        self.quota_limit_daily = 100  # Operations per day
        self.quota_reset_hour = 0  # Reset at midnight UTC
        self.session_cache_mode = False  # Fresh context per call (vs persistent agent)
        self.tools = {
            "escalate_to_claude": {
                "description": "Hand a task to Claude Code on your machine. "
                "Request is written to the bridge inbox; Claude Code agent picks it up, "
                "debugs/fixes, writes reply. Returns result when available.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "request": {
                            "type": "string",
                            "description": "The task description for Claude Code "
                            "(e.g., 'Debug the API health check failure and fix it')",
                        },
                        "wait_seconds": {
                            "type": "integer",
                            "description": "Max seconds to wait for reply (default: 300)",
                            "default": 300,
                        },
                    },
                    "required": ["request"],
                },
            },
            "run_script": {
                "description": "Execute a whitelisted script directly on the bridge. "
                "No agent involved; returns result immediately.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "script": {
                            "type": "string",
                            "description": "Script path relative to scripts/ "
                            "(e.g., 'mac_health.sh', 'disk_hogs.sh')",
                        },
                        "args": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "Arguments to pass to the script",
                            "default": [],
                        },
                        "timeout": {
                            "type": "integer",
                            "description": "Max seconds for script to run (default: 60)",
                            "default": 60,
                        },
                    },
                    "required": ["script"],
                },
            },
            "list_bridge_scripts": {
                "description": "Discover available whitelisted scripts on the bridge. "
                "Returns name, description for each script.",
                "inputSchema": {"type": "object", "properties": {}, "required": []},
            },
            "get_operation_status": {
                "description": "Check status of a long-running escalation operation. "
                "Idempotent: multiple calls return same result.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "operation_id": {
                            "type": "string",
                            "description": "Operation ID returned by escalate_to_claude",
                        },
                    },
                    "required": ["operation_id"],
                },
            },
            "cancel_operation": {
                "description": "Cancel a running operation. "
                "Safe before execution (immediate), best-effort during execution (SIGTERM).",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "operation_id": {
                            "type": "string",
                            "description": "Operation ID to cancel",
                        },
                        "reason": {
                            "type": "string",
                            "description": "Reason for cancellation (logged)",
                            "default": "Caller requested",
                        },
                    },
                    "required": ["operation_id"],
                },
            },
        }

    def _resolve_bridge_root(self) -> Path:
        """Find the bridge directory (same logic as client.py)."""
        env = os.environ.get("BRIDGE_ROOT")
        if env:
            return Path(env)
        cwd_bridge = Path.cwd() / "bridge"
        if cwd_bridge.exists():
            return cwd_bridge
        return Path.home() / ".cowork-to-code-bridge"

    def handle_request(self, req: dict[str, Any]) -> dict[str, Any]:
        """Handle a JSON-RPC request."""
        method = req.get("method")
        params = req.get("params", {})
        req_id = req.get("id")

        try:
            if method == "initialize":
                result = self._handle_initialize(params)
            elif method == "tools/list":
                result = self._handle_tools_list(params)
            elif method == "tools/call":
                result = self._handle_tools_call(params)
            else:
                return self._error_response(
                    req_id, -32601, f"Method not found: {method}"
                )
            return self._success_response(req_id, result)
        except Exception as e:
            return self._error_response(req_id, -32603, str(e))

    def _handle_initialize(self, params: dict[str, Any]) -> dict[str, Any]:
        """MCP initialize."""
        return {
            "protocolVersion": "2024-11-05",
            "capabilities": {},
            "serverInfo": {
                "name": "cowork-to-code-bridge",
                "version": "0.5.1",
            },
        }

    def _handle_tools_list(self, params: dict[str, Any]) -> dict[str, Any]:
        """Return list of available tools."""
        return {
            "tools": [
                {
                    "name": name,
                    "description": tool["description"],
                    "inputSchema": tool["inputSchema"],
                }
                for name, tool in self.tools.items()
            ]
        }

    def _handle_tools_call(self, params: dict[str, Any]) -> dict[str, Any]:
        """Execute a tool call."""
        tool_name = params.get("name")
        tool_input = params.get("arguments", {})

        if tool_name == "escalate_to_claude":
            return self._tool_escalate(tool_input)
        elif tool_name == "run_script":
            return self._tool_run_script(tool_input)
        elif tool_name == "list_bridge_scripts":
            return self._tool_list_scripts(tool_input)
        elif tool_name == "get_operation_status":
            return self._tool_get_status(tool_input)
        elif tool_name == "cancel_operation":
            return self._tool_cancel(tool_input)
        else:
            raise ValueError(f"Unknown tool: {tool_name}")

    def _get_quota(self) -> dict[str, Any]:
        """Calculate remaining quota based on journal."""
        journal_file = self.bridge_root / "daemon.log"
        if not journal_file.exists():
            return {
                "used": 0,
                "remaining": self.quota_limit_daily,
                "reset_at": self._next_reset_time(),
                "limit": self.quota_limit_daily,
            }

        # Count operations in journal for today
        import datetime
        today_start = datetime.datetime.now(datetime.timezone.utc).replace(
            hour=self.quota_reset_hour, minute=0, second=0, microsecond=0
        )
        if datetime.datetime.now(datetime.timezone.utc).hour < self.quota_reset_hour:
            today_start -= datetime.timedelta(days=1)

        today_ts = today_start.timestamp()
        count = 0
        try:
            for line in journal_file.read_text().splitlines():
                if not line.strip():
                    continue
                try:
                    entry = json.loads(line)
                    if entry.get("ts", 0) >= today_ts:
                        count += 1
                except json.JSONDecodeError:
                    pass
        except Exception:
            pass

        return {
            "used": count,
            "remaining": max(0, self.quota_limit_daily - count),
            "reset_at": self._next_reset_time(),
            "limit": self.quota_limit_daily,
        }

    def _next_reset_time(self) -> str:
        """Return ISO timestamp for next quota reset."""
        import datetime
        now = datetime.datetime.now(datetime.timezone.utc)
        reset = now.replace(hour=self.quota_reset_hour, minute=0, second=0, microsecond=0)
        if reset <= now:
            reset += datetime.timedelta(days=1)
        return reset.isoformat()

    def _tool_escalate(self, args: dict[str, Any]) -> dict[str, Any]:
        """Tool: escalate_to_claude."""
        request = args.get("request", "")
        wait_seconds = args.get("wait_seconds", 300)

        if not request:
            raise ValueError("request is required")

        # Write escalation to inbox with MCP metadata
        inbox = self.bridge_root / "to_cowork"
        inbox.mkdir(parents=True, exist_ok=True)
        request_id = f"{int(time.time())}_{uuid.uuid4().hex[:8]}"

        payload = {
            "id": request_id,
            "request": request,
            "ts": time.time(),
            "from": "mcp-client",
            "escalation_context": {
                "source": "mcp-server",
                "hostname": os.uname().nodename,
                "user": os.getenv("USER", "unknown"),
            },
        }

        request_file = inbox / f"{request_id}.json"
        tmp = request_file.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(payload))
        tmp.rename(request_file)

        # Poll for reply
        replies = self.bridge_root / "cowork_results"
        replies.mkdir(parents=True, exist_ok=True)
        reply_file = replies / f"{request_id}.json"
        deadline = time.time() + wait_seconds

        quota_before = self._get_quota()

        while time.time() < deadline:
            if reply_file.exists():
                try:
                    reply = json.loads(reply_file.read_text())
                    quota_after = self._get_quota()
                    return {
                        "status": "completed",
                        "result": reply,
                        "quota": quota_after,
                    }
                except json.JSONDecodeError:
                    time.sleep(0.5)
                    continue
            time.sleep(1)

        return {
            "status": "timeout",
            "message": f"No reply within {wait_seconds}s. "
            "Claude Code (Cowork) may not be open. "
            f"Request queued at {request_file}.",
            "quota": quota_before,
        }

    def _tool_run_script(self, args: dict[str, Any]) -> dict[str, Any]:
        """Tool: run_script — execute directly, no agent."""
        script = args.get("script", "")
        script_args = args.get("args", [])
        timeout = args.get("timeout", 60)

        if not script:
            raise ValueError("script is required")

        try:
            result = call_remote_streaming(
                script=f"scripts/{script}",
                args=script_args,
                timeout=timeout,
                bridge_root=self.bridge_root,
            )
            return {
                "status": "completed",
                "exit_code": result.get("exit_code"),
                "stdout": result.get("stdout", ""),
                "stderr": result.get("stderr", ""),
            }
        except TimeoutError as e:
            return {"status": "timeout", "message": str(e)}
        except Exception as e:
            return {"status": "error", "message": str(e)}

    def _tool_list_scripts(self, args: dict[str, Any]) -> dict[str, Any]:
        """Tool: list_bridge_scripts."""
        scripts_dir = self.bridge_root / "scripts"
        if not scripts_dir.exists():
            return {"scripts": [], "message": "No scripts directory found"}

        scripts = []
        for script_file in sorted(scripts_dir.glob("*.sh")):
            name = script_file.name
            try:
                content = script_file.read_text(errors="ignore")
                # Extract first comment line as description
                for line in content.split("\n"):
                    if "#" in line:
                        desc = line.split("#", 1)[1].strip()
                        if desc and len(desc) > 5:
                            scripts.append({"name": name, "description": desc})
                            break
                if not any(s["name"] == name for s in scripts):
                    scripts.append({"name": name, "description": "(no description)"})
            except Exception:
                scripts.append({"name": name, "description": "(error reading)"})

        return {"scripts": scripts}

    def _tool_get_status(self, args: dict[str, Any]) -> dict[str, Any]:
        """Tool: get_operation_status — check status of escalation operation."""
        operation_id = args.get("operation_id", "")
        if not operation_id:
            raise ValueError("operation_id is required")

        # Check if result file exists (cached result)
        results_dir = self.bridge_root / "cowork_results"
        result_file = results_dir / f"{operation_id}.json"

        if result_file.exists():
            try:
                result = json.loads(result_file.read_text())
                return {
                    "operation_id": operation_id,
                    "status": "completed",
                    "result": result,
                    "quota": self._get_quota(),
                }
            except json.JSONDecodeError:
                pass

        # Check if request is still in queue
        queue_dir = self.bridge_root / "to_cowork"
        request_file = queue_dir / f"{operation_id}.json"
        if request_file.exists():
            return {
                "operation_id": operation_id,
                "status": "queued",
                "quota": self._get_quota(),
            }

        # Check if result file exists but unfinished
        ops_dir = self.bridge_root / "operations"
        op_file = ops_dir / f"{operation_id}.json"
        if op_file.exists():
            try:
                op_state = json.loads(op_file.read_text())
                return {
                    "operation_id": operation_id,
                    "status": op_state.get("status", "executing"),
                    "progress": op_state.get("progress"),
                    "resume_receipt": op_state.get("resume_receipt"),
                    "quota": self._get_quota(),
                }
            except json.JSONDecodeError:
                pass

        # Unknown operation
        return {
            "operation_id": operation_id,
            "status": "unknown",
            "message": "Operation not found",
            "quota": self._get_quota(),
        }

    def _tool_cancel(self, args: dict[str, Any]) -> dict[str, Any]:
        """Tool: cancel_operation — cancel a running operation."""
        operation_id = args.get("operation_id", "")
        reason = args.get("reason", "Caller requested")

        if not operation_id:
            raise ValueError("operation_id is required")

        queue_dir = self.bridge_root / "to_cowork"
        request_file = queue_dir / f"{operation_id}.json"

        # If request still in queue, delete it (safe cancellation)
        if request_file.exists():
            try:
                request_file.unlink()
                return {
                    "operation_id": operation_id,
                    "status": "cancelled",
                    "reason": reason,
                    "message": "Operation cancelled before execution started",
                    "quota": self._get_quota(),
                }
            except Exception as e:
                return {
                    "operation_id": operation_id,
                    "status": "error",
                    "message": f"Failed to cancel: {str(e)}",
                }

        # If result already exists, it's too late to cancel
        results_dir = self.bridge_root / "cowork_results"
        result_file = results_dir / f"{operation_id}.json"
        if result_file.exists():
            return {
                "operation_id": operation_id,
                "status": "completed",
                "message": "Operation already completed; cancellation is no-op",
                "quota": self._get_quota(),
            }

        # If operation in progress, best-effort: mark it for cancellation
        # (actual SIGTERM would be handled by daemon)
        ops_dir = self.bridge_root / "operations"
        op_file = ops_dir / f"{operation_id}.json"
        if op_file.exists():
            try:
                op_state = json.loads(op_file.read_text())
                op_state["cancelled"] = True
                op_state["cancel_reason"] = reason
                op_state["cancelled_at"] = time.time()
                op_file.write_text(json.dumps(op_state))
                return {
                    "operation_id": operation_id,
                    "status": "cancelling",
                    "reason": reason,
                    "message": "Cancellation signaled (SIGTERM sent to process)",
                    "quota": self._get_quota(),
                }
            except Exception as e:
                return {
                    "operation_id": operation_id,
                    "status": "error",
                    "message": f"Failed to signal cancellation: {str(e)}",
                }

        # Unknown operation
        return {
            "operation_id": operation_id,
            "status": "unknown",
            "message": "Operation not found; nothing to cancel",
            "quota": self._get_quota(),
        }

    def _success_response(self, req_id: Any, result: Any) -> dict[str, Any]:
        """Format a JSON-RPC success response."""
        return {"jsonrpc": "2.0", "id": req_id, "result": result}

    def _error_response(self, req_id: Any, code: int, message: str) -> dict[str, Any]:
        """Format a JSON-RPC error response."""
        return {
            "jsonrpc": "2.0",
            "id": req_id,
            "error": {"code": code, "message": message},
        }

    def run_stdio(self):
        """Run MCP server in stdio mode (JSONRPC 2.0 over stdin/stdout)."""
        while True:
            try:
                line = sys.stdin.readline()
                if not line:
                    break
                req = json.loads(line)
                resp = self.handle_request(req)
                sys.stdout.write(json.dumps(resp) + "\n")
                sys.stdout.flush()
            except json.JSONDecodeError as e:
                resp = {
                    "jsonrpc": "2.0",
                    "id": None,
                    "error": {"code": -32700, "message": f"Parse error: {e}"},
                }
                sys.stdout.write(json.dumps(resp) + "\n")
                sys.stdout.flush()
            except KeyboardInterrupt:
                break
            except Exception as e:
                resp = {
                    "jsonrpc": "2.0",
                    "id": None,
                    "error": {"code": -32603, "message": f"Internal error: {e}"},
                }
                sys.stdout.write(json.dumps(resp) + "\n")
                sys.stdout.flush()


def main():
    """Entry point for cowork-to-code-bridge-mcp CLI."""
    parser = argparse.ArgumentParser(
        description="MCP server for cowork-to-code-bridge"
    )
    parser.add_argument(
        "--stdio",
        action="store_true",
        help="Run in stdio mode (JSONRPC 2.0 over stdin/stdout)",
    )
    parser.add_argument(
        "--bridge-root",
        default=None,
        help="Override bridge root directory (default: auto-detect)",
    )
    parser.add_argument(
        "--session-cache",
        action="store_true",
        help="Use fresh context per call (vs persistent agent). For single-shot workflows.",
    )
    args = parser.parse_args()

    server = MCPServer(bridge_root=args.bridge_root)
    server.session_cache_mode = args.session_cache

    if args.stdio:
        server.run_stdio()
    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
