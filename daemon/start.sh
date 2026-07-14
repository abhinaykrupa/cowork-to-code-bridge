#!/usr/bin/env bash
# start.sh — start the daemon in the foreground for testing.
# For production use, install.sh sets up a launchd agent that auto-restarts.
#
# Usage:
#   bash daemon/start.sh                  # foreground, ctrl+c to stop
#   nohup bash daemon/start.sh > out.log 2>&1 &   # background
set -euo pipefail

BRIDGE_ROOT="${BRIDGE_ROOT:-$HOME/.cowork-to-code-bridge}"
export BRIDGE_ROOT

if [[ ! -f "$BRIDGE_ROOT/.env" ]]; then
  echo "✗ $BRIDGE_ROOT/.env not found. Run install.sh first."
  exit 1
fi

# Prefer the installed console script
if command -v cowork-to-code-bridge-daemon >/dev/null 2>&1; then
  exec cowork-to-code-bridge-daemon
fi

# Fallback to module form
exec python3 -m cowork_to_code_bridge.daemon
