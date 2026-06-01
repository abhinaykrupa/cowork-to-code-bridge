#!/usr/bin/env bash
# Regression tests for WSL/platform detection (run on ubuntu-latest in CI).
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

# WSL_DISTRO_NAME env
export WSL_DISTRO_NAME=Ubuntu
is_wsl || fail "expected WSL from WSL_DISTRO_NAME"
unset WSL_DISTRO_NAME
pass "detects WSL_DISTRO_NAME"

echo "All platform detection checks passed."
