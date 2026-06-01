#!/usr/bin/env bash
# pkg_outdated.sh — list outdated system packages (macOS or Linux).
# Detects the package manager: brew on macOS; apt/dnf/yum/pacman on Linux.
# Usage from Cowork: call_remote("scripts/pkg_outdated.sh")
set -u

echo "=== OUTDATED PACKAGES ==="
found=0

if command -v brew >/dev/null 2>&1; then
  echo "--- Homebrew (brew outdated) ---"
  brew outdated || true
  found=1
fi

if [ "$found" -eq 0 ] && command -v apt >/dev/null 2>&1; then
  echo "--- APT (apt list --upgradable) ---"
  apt list --upgradable 2>/dev/null || true
  found=1
fi

if [ "$found" -eq 0 ] && command -v dnf >/dev/null 2>&1; then
  echo "--- DNF (dnf check-update) ---"
  # dnf check-update exits 100 when updates exist; don't treat that as an error.
  dnf check-update || true
  found=1
fi

if [ "$found" -eq 0 ] && command -v yum >/dev/null 2>&1; then
  echo "--- YUM (yum check-update) ---"
  yum check-update || true
  found=1
fi

if [ "$found" -eq 0 ] && command -v pacman >/dev/null 2>&1; then
  echo "--- pacman (pacman -Qu) ---"
  pacman -Qu || true
  found=1
fi

if [ "$found" -eq 0 ]; then
  echo "No supported package manager found (looked for brew, apt, dnf, yum, pacman)."
fi

exit 0
