#!/usr/bin/env bash
# Test manual daemon start/stop (non-systemd path). Linux only.
set -euo pipefail

if [[ "$(uname -s)" != "Linux" ]]; then
  echo "SKIP: test_manual_daemon.sh requires Linux"
  exit 0
fi

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
# shellcheck source=scripts/lib/daemon_service.sh
source "$ROOT/scripts/lib/daemon_service.sh"

fail() { echo "FAIL: $*" >&2; exit 1; }
pass() { echo "PASS: $*"; }

TMP="$(mktemp -d)"
trap 'bridge_stop_daemon_manual 2>/dev/null || true; rm -rf "$TMP"' EXIT

BRIDGE_ROOT="$TMP/bridge"
DAEMON_LOG="$BRIDGE_ROOT/daemon.log"
DAEMON_ERR="$BRIDGE_ROOT/daemon.err"
USER_SCRIPTS_DIR=""
mkdir -p "$BRIDGE_ROOT"

if python3 -c "import cowork_to_code_bridge.daemon" 2>/dev/null; then
  DAEMON_ARGS=(python3 -m cowork_to_code_bridge.daemon)
elif [[ -x "$ROOT/.venv/bin/python" ]]; then
  DAEMON_ARGS=("$ROOT/.venv/bin/python" -m cowork_to_code_bridge.daemon)
else
  echo "SKIP: cowork_to_code_bridge not installed"
  exit 0
fi

bridge_start_daemon_manual || fail "bridge_start_daemon_manual"
bridge_manual_daemon_running || fail "daemon not running after start"

for _ in $(seq 1 15); do
  if [[ -f "$DAEMON_LOG" ]] && grep -q "daemon up" "$DAEMON_LOG" 2>/dev/null; then
    pass "daemon logged heartbeat"
    break
  fi
  sleep 1
done
grep -q "daemon up" "$DAEMON_LOG" 2>/dev/null || fail "no daemon up in log"

bridge_stop_daemon_manual
bridge_manual_daemon_running && fail "daemon still running after stop"
pass "bridge_stop_daemon_manual"

echo "All manual daemon checks passed."
