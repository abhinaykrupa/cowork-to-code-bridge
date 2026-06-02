#!/usr/bin/env bash
# mac_ram.sh — RAM usage summary (macOS or Linux). Args: none.
set -u
if [ "$(uname -s)" = "Darwin" ]; then
  TOTAL=$(sysctl -n hw.memsize 2>/dev/null)
  echo "Total RAM: $(( TOTAL / 1024 / 1024 / 1024 )) GB"
  echo "--- vm_stat ---"; vm_stat 2>/dev/null
else
  free -h 2>/dev/null || cat /proc/meminfo 2>/dev/null | head -5
fi
exit 0
