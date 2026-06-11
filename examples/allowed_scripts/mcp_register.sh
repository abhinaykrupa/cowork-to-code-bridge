#!/usr/bin/env bash
# mcp_register.sh — register a local stdio MCP server in the bridge registry.
#
# Usage
# -----
#   mcp_register.sh --name <name> --command <cmd> [--args <json_array>] [--env <json_object>]
#   mcp_register.sh --remove <name>
#   mcp_register.sh --list
#
# Examples
# --------
#   # Register the MCP filesystem server (npx)
#   mcp_register.sh --name filesystem \
#     --command npx \
#     --args '["-y","@modelcontextprotocol/server-filesystem","/Users/me/projects"]'
#
#   # Register a postgres MCP server (uvx)
#   mcp_register.sh --name postgres \
#     --command uvx \
#     --args '["mcp-server-postgres","postgresql://localhost/mydb"]'
#
#   # Register a custom CLI tool
#   mcp_register.sh --name mytool --command /usr/local/bin/my-mcp-server
#
#   # Remove a server
#   mcp_register.sh --remove filesystem
#
# Registry: $BRIDGE_ROOT/mcp_servers.json
# Testability hooks
#   BRIDGE_MCP_REGISTRY  override registry file path
set -uo pipefail

BRIDGE_ROOT="${BRIDGE_ROOT:-$HOME/.cowork-to-code-bridge}"
REGISTRY="${BRIDGE_MCP_REGISTRY:-$BRIDGE_ROOT/mcp_servers.json}"

usage() {
  cat >&2 <<'EOF'
Usage:
  mcp_register.sh --name <name> --command <cmd> [--args <json_array>] [--env <json_object>]
  mcp_register.sh --remove <name>
  mcp_register.sh --list
EOF
  exit 1
}

MODE="register"
NAME=""
COMMAND=""
ARGS_JSON="[]"
ENV_JSON="{}"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --name)    NAME="$2";      shift 2 ;;
    --command) COMMAND="$2";   shift 2 ;;
    --args)    ARGS_JSON="$2"; shift 2 ;;
    --env)     ENV_JSON="$2";  shift 2 ;;
    --remove)  MODE="remove"; NAME="$2"; shift 2 ;;
    --list)    MODE="list";   shift ;;
    -h|--help) usage ;;
    *) echo "Unknown argument: $1" >&2; usage ;;
  esac
done

python3 - "$MODE" "$NAME" "$COMMAND" "$ARGS_JSON" "$ENV_JSON" "$REGISTRY" <<'PYEOF'
import sys, json, os

mode         = sys.argv[1]
name         = sys.argv[2]
command      = sys.argv[3]
args_raw     = sys.argv[4]
env_raw      = sys.argv[5]
registry_path = sys.argv[6]

# Load existing registry (or start fresh)
registry = {}
if os.path.exists(registry_path):
    try:
        registry = json.load(open(registry_path))
    except Exception as e:
        print(f"WARNING: could not parse existing registry, starting fresh: {e}", file=sys.stderr)

if mode == "list":
    if not registry:
        print("No MCP servers registered.")
        print(f"Registry: {registry_path}")
    else:
        print(f"Registered MCP servers ({len(registry)}):")
        for n, cfg in registry.items():
            args_str = " ".join(cfg.get("args", []))
            print(f"  {n:20s}  {cfg['command']} {args_str}")
        print(f"\nRegistry: {registry_path}")
    sys.exit(0)

if mode == "remove":
    if not name:
        print("ERROR: --remove requires a server name", file=sys.stderr)
        sys.exit(1)
    if name not in registry:
        print(f"ERROR: '{name}' is not registered", file=sys.stderr)
        sys.exit(1)
    del registry[name]
    os.makedirs(os.path.dirname(registry_path), exist_ok=True)
    with open(registry_path, "w") as f:
        json.dump(registry, f, indent=2)
    print(f"✓ Removed '{name}' from registry")
    sys.exit(0)

# register mode
if not name:
    print("ERROR: --name is required", file=sys.stderr)
    sys.exit(1)
if not command:
    print("ERROR: --command is required", file=sys.stderr)
    sys.exit(1)

try:
    args = json.loads(args_raw)
    if not isinstance(args, list):
        raise ValueError("--args must be a JSON array")
except Exception as e:
    print(f"ERROR: invalid --args JSON: {e}", file=sys.stderr)
    sys.exit(1)

try:
    env = json.loads(env_raw)
    if not isinstance(env, dict):
        raise ValueError("--env must be a JSON object")
except Exception as e:
    print(f"ERROR: invalid --env JSON: {e}", file=sys.stderr)
    sys.exit(1)

registry[name] = {"command": command, "args": args, "env": env}

os.makedirs(os.path.dirname(registry_path), exist_ok=True)
tmp = registry_path + ".tmp"
with open(tmp, "w") as f:
    json.dump(registry, f, indent=2)
os.replace(tmp, registry_path)

action = "Updated" if name in registry else "Registered"
print(f"✓ {action} '{name}'  →  {command} {' '.join(str(a) for a in args)}")
print(f"  Registry: {registry_path}")
print(f"  Total servers: {len(registry)}")
PYEOF
