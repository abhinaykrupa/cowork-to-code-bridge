#!/usr/bin/env bash
# mac_top.sh — top processes. Args: optional count (default 15).
set -u
N="${1:-15}"
echo "=== by CPU ==="; ps -arcwwwxo pid,pcpu,pmem,comm 2>/dev/null | head -"$((N+1))"
echo "=== by MEM ==="; ps -amcwwwxo pid,pcpu,pmem,comm 2>/dev/null | head -"$((N+1))"
exit 0
