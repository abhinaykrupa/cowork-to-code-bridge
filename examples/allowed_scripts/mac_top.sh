#!/usr/bin/env bash
# mac_top.sh — top processes by CPU and memory (macOS or Linux). Args: count (default 15).
set -u
N="${1:-15}"
echo "=== by CPU ==="; ps -eo pid,pcpu,pmem,comm 2>/dev/null | sort -k2 -rn | head -"$((N+1))"
echo "=== by MEM ==="; ps -eo pid,pcpu,pmem,comm 2>/dev/null | sort -k3 -rn | head -"$((N+1))"
exit 0
