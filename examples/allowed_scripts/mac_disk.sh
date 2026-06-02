#!/usr/bin/env bash
# mac_disk.sh — disk usage (fast). Args: optional path (default /).
set -u
echo "=== DISK USAGE ==="; df -h "${1:-/}" 2>/dev/null
echo; echo "=== ALL MOUNTED VOLUMES ==="; df -h 2>/dev/null | grep -E "^/dev|Filesystem" | head -10
exit 0
