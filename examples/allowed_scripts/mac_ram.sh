#!/usr/bin/env bash
# mac_ram.sh — RAM usage summary. Args: none.
set -u
TOTAL=$(sysctl -n hw.memsize 2>/dev/null)
echo "Total RAM: $(( TOTAL / 1024 / 1024 / 1024 )) GB"
echo "--- vm_stat ---"; vm_stat 2>/dev/null
echo "--- memory pressure ---"; memory_pressure 2>/dev/null | tail -3 || echo "n/a"
exit 0
