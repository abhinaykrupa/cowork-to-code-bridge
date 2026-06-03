#!/usr/bin/env bash
# Regression tests for WSL/platform/service-manager detection (ubuntu-latest in CI).
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
# shellcheck source=scripts/lib/platform.sh
source "$ROOT/scripts/lib/platform.sh"

fail() { echo "FAIL: $*" >&2; exit 1; }
pass() { echo "PASS: $*"; }

# Real environment: ubuntu-latest is not WSL
if is_wsl; then
  if grep -qi microsoft /proc/version 2>/dev/null || [[ -n "${WSL_DISTRO_NAME:-}" ]]; then
    pass "is_wsl true on actual WSL"
  else
    fail "is_wsl true on CI ubuntu but /proc/version is not WSL"
  fi
else
  pass "is_wsl false on non-WSL Linux (expected in CI)"
fi

# Mocked /proc/version
PROC_BACKUP=""
if [[ -f /proc/version ]]; then
  PROC_BACKUP="$(mktemp)"
  cp /proc/version "$PROC_BACKUP"
fi

mock_proc() {
  printf '%s\n' "$1" > /proc/version 2>/dev/null || {
    echo "SKIP: cannot write /proc/version (need root); mocked checks skipped"
    return 1
  }
}

restore_proc() {
  [[ -n "$PROC_BACKUP" && -f "$PROC_BACKUP" ]] && cp "$PROC_BACKUP" /proc/version 2>/dev/null || true
  rm -f "$PROC_BACKUP"
}

if mock_proc "Linux version 5.15.0-microsoft-standard-WSL2 #1 SMP"; then
  is_wsl || fail "expected WSL from microsoft in /proc/version"
  pass "detects microsoft in /proc/version"
  restore_proc
fi

if mock_proc "Linux version 6.8.0-31-generic #1 SMP PREEMPT"; then
  is_wsl && fail "expected non-WSL generic kernel"
  pass "does not false-positive on generic Linux"
  restore_proc
fi

export WSL_DISTRO_NAME=Ubuntu
is_wsl || fail "expected WSL from WSL_DISTRO_NAME"
unset WSL_DISTRO_NAME
pass "detects WSL_DISTRO_NAME"

export BRIDGE_FORCE_SERVICE_MGR=manual
[[ "$(linux_service_mgr)" == "manual" ]] || fail "BRIDGE_FORCE_SERVICE_MGR=manual"
unset BRIDGE_FORCE_SERVICE_MGR
pass "BRIDGE_FORCE_SERVICE_MGR override"

if has_systemd_user_bus; then
  [[ "$(linux_service_mgr)" == "systemd" ]] || fail "expected systemd on bus-available host"
  pass "linux_service_mgr systemd when user bus works"
else
  mgr="$(linux_service_mgr)"
  [[ "$mgr" == "manual" || "$mgr" == "wsl_need_systemd" ]] || fail "unexpected mgr: $mgr"
  pass "linux_service_mgr fallback without user bus ($mgr)"
fi

echo "All platform detection checks passed."
