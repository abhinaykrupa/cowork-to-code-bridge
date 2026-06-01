#!/usr/bin/env bash
# mac_health.sh — full health snapshot of this machine (macOS or Linux). Args: none.
set -u
echo "=== HOST ==="; hostname
if [ "$(uname -s)" = "Darwin" ]; then sw_vers 2>/dev/null; else (. /etc/os-release 2>/dev/null; echo "${PRETTY_NAME:-$(uname -sr)}"); fi
echo "=== UPTIME / LOAD ==="; uptime
echo "=== CPU ==="
if [ "$(uname -s)" = "Darwin" ]; then top -l 1 -n 0 2>/dev/null | grep -E "CPU usage" || echo n/a
else grep 'cpu ' /proc/stat >/dev/null 2>&1 && echo "load: $(cut -d' ' -f1-3 /proc/loadavg)" || echo n/a; fi
echo "=== MEMORY ==="
if [ "$(uname -s)" = "Darwin" ]; then vm_stat 2>/dev/null | head -6; else free -h 2>/dev/null || cat /proc/meminfo | head -3; fi
echo "=== DISK ==="; df -h / 2>/dev/null
echo "=== TOP 5 PROCS BY CPU ==="; ps -eo pid,pcpu,pmem,comm 2>/dev/null | sort -k2 -rn | head -6
exit 0
