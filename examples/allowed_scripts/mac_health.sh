#!/usr/bin/env bash
# mac_health.sh — full health snapshot of this Mac. Args: none.
set -u
echo "=== HOST ==="; scutil --get ComputerName 2>/dev/null; hostname; sw_vers 2>/dev/null
echo "=== UPTIME / LOAD ==="; uptime
echo "=== CPU ==="; top -l 1 -n 0 2>/dev/null | grep -E "CPU usage" || echo "n/a"
echo "=== MEMORY (pages) ==="; vm_stat 2>/dev/null | head -6
echo "=== DISK ==="; df -h / 2>/dev/null
echo "=== BATTERY ==="; pmset -g batt 2>/dev/null | head -2 || echo "n/a"
echo "=== TOP 5 PROCS BY CPU ==="; ps -arcwwwxo pid,pcpu,pmem,comm 2>/dev/null | head -6
exit 0
