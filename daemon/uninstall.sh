#!/usr/bin/env bash
# uninstall.sh — one-command Mac-side teardown for cowork-to-code-bridge.
#
# Prefers the installed console script (cowork-to-code-bridge-uninstall) when
# available, since it knows which Python interpreter installed the package.
# Falls back to direct shell teardown if the package isn't on PATH.
#
# Usage:
#   bash daemon/uninstall.sh                # interactive prompts
#   bash daemon/uninstall.sh --yes          # no prompts
#   bash daemon/uninstall.sh --keep-data    # leave ~/.cowork-to-code-bridge/
#   bash daemon/uninstall.sh --keep-package # leave the pip package

set -euo pipefail

# ─── Prefer the installed console script ─────────────────────────────────────
if command -v cowork-to-code-bridge-uninstall >/dev/null 2>&1; then
  exec cowork-to-code-bridge-uninstall "$@"
fi

# Try locating it via the same python that may have installed it
for PY in python3.13 python3.12 python3.11 python3.10 python3; do
  if command -v "$PY" >/dev/null 2>&1 && \
     "$PY" -c "import cowork_to_code_bridge.uninstall" 2>/dev/null; then
    exec "$PY" -m cowork_to_code_bridge.uninstall "$@"
  fi
done

# ─── Fallback: pure-shell teardown ───────────────────────────────────────────
echo "  ! cowork-to-code-bridge package not found on this system — running shell-only teardown."
echo "    (Daemon + plist + bridge data will be removed; pip uninstall is skipped.)"
echo

BRIDGE_ROOT="${BRIDGE_ROOT:-$HOME/.cowork-to-code-bridge}"
PLIST="$HOME/Library/LaunchAgents/dev.cowork-to-code-bridge.daemon.plist"

ASSUME_YES=0
KEEP_DATA=0
for arg in "$@"; do
  case "$arg" in
    --yes|-y) ASSUME_YES=1 ;;
    --keep-data) KEEP_DATA=1 ;;
  esac
done

confirm() {
  if [[ "$ASSUME_YES" -eq 1 ]]; then return 0; fi
  read -r -p "$1 [y/N] " response
  [[ "$response" =~ ^[Yy]$ ]]
}

if launchctl list 2>/dev/null | grep -q "dev.cowork-to-code-bridge.daemon"; then
  echo "→ unloading launchd agent"
  launchctl unload "$PLIST" 2>/dev/null || true
fi

if [[ -f "$PLIST" ]]; then
  echo "→ removing $PLIST"
  rm -f "$PLIST"
fi

if [[ "$KEEP_DATA" -eq 1 ]]; then
  echo "→ keeping $BRIDGE_ROOT (--keep-data)"
elif [[ -d "$BRIDGE_ROOT" ]]; then
  if confirm "Delete $BRIDGE_ROOT (contains your bridge token and processed-command history)?"; then
    rm -rf "$BRIDGE_ROOT"
    echo "✓ removed $BRIDGE_ROOT"
  else
    echo "  kept $BRIDGE_ROOT"
  fi
fi

echo "✓ daemon + plist removed."
echo "  Package was not on PATH so nothing to pip-uninstall. If you did install it via pip,"
echo "  remove it with: python3 -m pip uninstall cowork-to-code-bridge"
