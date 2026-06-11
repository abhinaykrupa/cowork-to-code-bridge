#!/usr/bin/env bash
# mcp_proxy.sh — relay a single MCP JSON-RPC call to a local stdio MCP server
# and return the response through the bridge queue.
#
# This lets Claude Cowork reach any local stdio MCP server — a database client,
# filesystem tool, or custom CLI — without a public HTTPS tunnel.
# Addresses: anthropics/claude-code#53476, anthropics/claude-code#48909
#
# Usage
# -----
#   mcp_proxy.sh --server <name> --method <method> [--params <json>]
#   mcp_proxy.sh --server <name> --request <full_jsonrpc_json>
#
# Server registry: $BRIDGE_ROOT/mcp_servers.json
# Register servers with: mcp_register.sh
#
# Output (stdout): JSON-RPC response object, always valid JSON.
# Exit code: always 0 — MCP-level errors are reported inside the JSON.
#
# Testability hooks
#   BRIDGE_MCP_REGISTRY  override registry file path
set -uo pipefail

BRIDGE_ROOT="${BRIDGE_ROOT:-$HOME/.cowork-to-code-bridge}"
REGISTRY="${BRIDGE_MCP_REGISTRY:-$BRIDGE_ROOT/mcp_servers.json}"

usage() {
  cat >&2 <<'EOF'
Usage:
  mcp_proxy.sh --server <name> --method <method> [--params <json>]
  mcp_proxy.sh --server <name> --request <full_jsonrpc_json>

Examples:
  mcp_proxy.sh --server filesystem --method tools/list --params '{}'
  mcp_proxy.sh --server postgres   --method tools/call \
    --params '{"name":"query","arguments":{"sql":"SELECT 1"}}'
EOF
  exit 1
}

SERVER_NAME=""
METHOD=""
PARAMS="null"
REQUEST_JSON=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --server)  SERVER_NAME="$2"; shift 2 ;;
    --method)  METHOD="$2";      shift 2 ;;
    --params)  PARAMS="$2";      shift 2 ;;
    --request) REQUEST_JSON="$2";shift 2 ;;
    -h|--help) usage ;;
    *) echo "Unknown argument: $1" >&2; usage ;;
  esac
done

[[ -z "$SERVER_NAME" ]] && { echo "ERROR: --server is required" >&2; usage; }
[[ -z "$METHOD" && -z "$REQUEST_JSON" ]] && { echo "ERROR: --method or --request is required" >&2; usage; }

# ── Python handles the MCP stdio protocol ─────────────────────────────────────
python3 - \
  "$SERVER_NAME" \
  "$METHOD" \
  "$PARAMS" \
  "$REQUEST_JSON" \
  "$REGISTRY" \
<<'PYEOF'
import sys, json, subprocess, time, os

server_name  = sys.argv[1]
method       = sys.argv[2]   # empty string if --request used
params_raw   = sys.argv[3]   # "null" if not provided
request_raw  = sys.argv[4]   # full JSON-RPC string if --request used
registry_path = sys.argv[5]

def die(msg):
    print(json.dumps({"jsonrpc": "2.0", "id": None, "error": {"code": -32000, "message": msg}}))
    sys.exit(0)

# ── Load registry ──────────────────────────────────────────────────────────────
if not os.path.exists(registry_path):
    die(f"No server registry at {registry_path}. Run mcp_register.sh first.")

try:
    registry = json.load(open(registry_path))
except Exception as e:
    die(f"Cannot read registry: {e}")

if server_name not in registry:
    known = list(registry.keys())
    die(f"Server '{server_name}' not registered. Known servers: {known}")

cfg = registry[server_name]
cmd = [cfg["command"]] + cfg.get("args", [])
env = {**os.environ, **cfg.get("env", {})}

# ── Build the user request ────────────────────────────────────────────────────
if request_raw:
    try:
        user_req = json.loads(request_raw)
    except Exception as e:
        die(f"Invalid --request JSON: {e}")
else:
    try:
        params = json.loads(params_raw)
    except Exception as e:
        die(f"Invalid --params JSON: {e}")
    user_req = {
        "jsonrpc": "2.0",
        "id": 2,
        "method": method,
        "params": params if params is not None else {},
    }

req_id = user_req.get("id", 2)

# ── MCP stdio: initialize → initialized → user_req → response ────────────────
INIT_REQ = json.dumps({
    "jsonrpc": "2.0", "id": 1, "method": "initialize",
    "params": {
        "protocolVersion": "2024-11-05",
        "capabilities": {},
        "clientInfo": {"name": "cowork-bridge-proxy", "version": "1.0"},
    }
})
INIT_NOTIF = json.dumps({"jsonrpc": "2.0", "method": "notifications/initialized"})

try:
    proc = subprocess.Popen(
        cmd, env=env,
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        text=True, bufsize=1,
    )
except FileNotFoundError:
    die(f"Command not found: {cmd[0]}")
except Exception as e:
    die(f"Failed to start server '{server_name}': {e}")

def readline_timeout(stream, timeout=10.0):
    """Read one line; return None on timeout or EOF."""
    import select
    deadline = time.time() + timeout
    buf = ""
    while time.time() < deadline:
        ready, _, _ = select.select([stream], [], [], 0.05)
        if ready:
            ch = stream.read(1)
            if not ch:
                return None
            if ch == "\n":
                return buf
            buf += ch
    return None

result = None
try:
    # 1. Send initialize
    proc.stdin.write(INIT_REQ + "\n")
    proc.stdin.flush()

    # 2. Read initialize response
    deadline = time.time() + 10
    while time.time() < deadline:
        line = readline_timeout(proc.stdout, timeout=2.0)
        if line is None:
            break
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
            if msg.get("id") == 1:
                if "error" in msg:
                    result = msg
                break
        except Exception:
            continue
    else:
        result = {"jsonrpc": "2.0", "id": req_id,
                  "error": {"code": -32001, "message": "Initialize timeout"}}

    if result is None:
        # 3. Send initialized notification
        proc.stdin.write(INIT_NOTIF + "\n")
        proc.stdin.flush()

        # 4. Send user request
        proc.stdin.write(json.dumps(user_req) + "\n")
        proc.stdin.flush()

        # 5. Read response (skip notifications)
        deadline = time.time() + 30
        while time.time() < deadline:
            line = readline_timeout(proc.stdout, timeout=2.0)
            if line is None:
                result = {"jsonrpc": "2.0", "id": req_id,
                          "error": {"code": -32002, "message": "Response timeout after 30s"}}
                break
            line = line.strip()
            if not line:
                continue
            try:
                msg = json.loads(line)
                # Skip notifications (no id field)
                if "id" in msg and msg["id"] == req_id:
                    result = msg
                    break
            except Exception:
                continue
        else:
            result = {"jsonrpc": "2.0", "id": req_id,
                      "error": {"code": -32002, "message": "Response timeout after 30s"}}

except Exception as e:
    result = {"jsonrpc": "2.0", "id": req_id,
              "error": {"code": -32603, "message": f"Protocol error: {e}"}}
finally:
    try:
        proc.stdin.close()
        proc.terminate()
        proc.wait(timeout=3)
    except Exception:
        try:
            proc.kill()
        except Exception:
            pass

if result is None:
    result = {"jsonrpc": "2.0", "id": req_id,
              "error": {"code": -32603, "message": "No response received"}}

print(json.dumps(result))
PYEOF
