#!/usr/bin/env bash
# mcp_list_servers.sh — list all MCP servers registered in the bridge registry.
#
# Usage
# -----
#   mcp_list_servers.sh [--json]
#
# Without --json: human-readable table.
# With    --json: raw JSON of the registry (for programmatic use).
#
# Registry: $BRIDGE_ROOT/mcp_servers.json
# Testability hooks
#   BRIDGE_MCP_REGISTRY  override registry file path
set -uo pipefail

BRIDGE_ROOT="${BRIDGE_ROOT:-$HOME/.cowork-to-code-bridge}"
REGISTRY="${BRIDGE_MCP_REGISTRY:-$BRIDGE_ROOT/mcp_servers.json}"
JSON_OUT=0

while [[ $# -gt 0 ]]; do
  case "$1" in
    --json) JSON_OUT=1; shift ;;
    -h|--help)
      echo "Usage: mcp_list_servers.sh [--json]" >&2
      exit 0 ;;
    *) echo "Unknown argument: $1" >&2; exit 1 ;;
  esac
done

if [[ ! -f "$REGISTRY" ]]; then
  if [[ "$JSON_OUT" -eq 1 ]]; then
    echo '{"servers":{},"count":0,"registry":null}'
  else
    echo "No MCP servers registered."
    echo "Register one with: mcp_register.sh --name <name> --command <cmd>"
  fi
  exit 0
fi

python3 - "$REGISTRY" "$JSON_OUT" <<'PYEOF'
import sys, json

registry_path = sys.argv[1]
json_out      = sys.argv[2] == "1"

try:
    registry = json.load(open(registry_path))
except Exception as e:
    if json_out:
        print(json.dumps({"error": str(e), "servers": {}, "count": 0}))
    else:
        print(f"ERROR reading registry: {e}")
    sys.exit(0)

if json_out:
    print(json.dumps({
        "servers": registry,
        "count": len(registry),
        "registry": registry_path,
    }, indent=2))
    sys.exit(0)

if not registry:
    print("No MCP servers registered.")
    print(f"Registry: {registry_path}")
    sys.exit(0)

print(f"Registered MCP servers ({len(registry)}):\n")
print(f"  {'NAME':<20}  {'COMMAND':<12}  ARGS")
print(f"  {'-'*20}  {'-'*12}  {'-'*30}")
for name, cfg in sorted(registry.items()):
    args_str = " ".join(str(a) for a in cfg.get("args", []))
    if len(args_str) > 40:
        args_str = args_str[:37] + "..."
    print(f"  {name:<20}  {cfg['command']:<12}  {args_str}")

print(f"\nRegistry: {registry_path}")
print(f"Use mcp_proxy.sh to call any of these from Cowork.")
PYEOF
