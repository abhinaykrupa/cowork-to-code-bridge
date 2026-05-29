#!/usr/bin/env bash
# mac_disk.sh — disk usage (fast). Args: optional path (default /).
set -u
echo "=== DISK USAGE ==="
df -h "${1:-/}" 2>/dev/null
echo
echo "=== ALL MOUNTED VOLUMES ==="
df -h 2>/dev/null | grep -E "^/dev|Filesystem" | head -10
# Note: a full per-folder breakdown (du) can take minutes on large home dirs,
# so it's intentionally omitted here. For that, ask Claude Code via run_claude.sh
# ("what's using the most disk in ~/Downloads") and it will scope the scan.
exit 0
