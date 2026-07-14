#!/usr/bin/env bash
# mac_health.sh — full health snapshot of this machine (macOS or Linux).
#
# Usage: mac_health.sh [--json]
#   (no flag)   human-readable text sections (default)
#   --json      structured JSON — parse with json.loads() in Cowork
#
# JSON fields: host, os, uptime, load_1m/5m/15m, cpu_usage_pct,
#   memory_total_bytes, memory_free_bytes, memory_used_bytes, memory_used_pct,
#   disk_total_1k, disk_used_1k, disk_avail_1k, disk_used_pct,
#   top_procs [{pid, cpu_pct, mem_pct, name}]
#
# No external dependencies (no jq, no python).
set -u

JSON=0
for arg in "$@"; do [ "$arg" = "--json" ] && JSON=1; done

OS="$(uname -s)"

# Escape a string for safe embedding in JSON (no jq required).
_jstr() { printf '%s' "$1" | sed 's/\\/\\\\/g; s/"/\\"/g; s/	/\\t/g' | tr -d '\r\n'; }

# ── collect ──────────────────────────────────────────────────────────────────
HOST="$(hostname 2>/dev/null)"
if [ "$OS" = "Darwin" ]; then
  OS_NAME="$(sw_vers -productName 2>/dev/null) $(sw_vers -productVersion 2>/dev/null)"
else
  OS_NAME="$(. /etc/os-release 2>/dev/null && echo "${PRETTY_NAME:-}" || uname -sr)"
fi

UPTIME_STR="$(uptime 2>/dev/null)"
LOAD_1="$(echo  "$UPTIME_STR" | grep -oE '[0-9]+\.[0-9]+' | sed -n '1p' || echo '')"
LOAD_5="$(echo  "$UPTIME_STR" | grep -oE '[0-9]+\.[0-9]+' | sed -n '2p' || echo '')"
LOAD_15="$(echo "$UPTIME_STR" | grep -oE '[0-9]+\.[0-9]+' | sed -n '3p' || echo '')"

CPU_USAGE=""
if [ "$OS" = "Darwin" ]; then
  CPU_USAGE="$(top -l 1 -n 0 2>/dev/null | grep -oE '[0-9]+\.[0-9]+% user' | grep -oE '^[0-9.]+' || echo '')"
fi

MEM_TOTAL_BYTES=0; MEM_FREE_BYTES=0; MEM_USED_BYTES=0; MEM_USED_PCT=0
if [ "$OS" = "Darwin" ]; then
  MEM_TOTAL_BYTES="$(sysctl -n hw.memsize 2>/dev/null || echo 0)"
  PAGE_SIZE="$(sysctl -n hw.pagesize 2>/dev/null || echo 4096)"
  PAGES_FREE="$(vm_stat 2>/dev/null | awk '/^Pages free/{gsub(/\./,"",$3); print $3}' || echo 0)"
  MEM_FREE_BYTES=$(( PAGES_FREE * PAGE_SIZE ))
  MEM_USED_BYTES=$(( MEM_TOTAL_BYTES - MEM_FREE_BYTES ))
  [ "$MEM_TOTAL_BYTES" -gt 0 ] && MEM_USED_PCT=$(( MEM_USED_BYTES * 100 / MEM_TOTAL_BYTES ))
elif command -v free >/dev/null 2>&1; then
  eval "$(free | awk '/^Mem:/{printf "MEM_TOTAL_BYTES=%d MEM_USED_BYTES=%d MEM_FREE_BYTES=%d", $2*1024, $3*1024, $4*1024}')"
  [ "$MEM_TOTAL_BYTES" -gt 0 ] && MEM_USED_PCT=$(( MEM_USED_BYTES * 100 / MEM_TOTAL_BYTES ))
fi

DISK_LINE="$(df -k / 2>/dev/null | awk 'NR==2{print}')"
DISK_TOTAL="$(echo "$DISK_LINE" | awk '{print $2}')"
DISK_USED="$(echo  "$DISK_LINE" | awk '{print $3}')"
DISK_AVAIL="$(echo "$DISK_LINE" | awk '{print $4}')"
DISK_PCT="$(echo   "$DISK_LINE" | awk '{gsub(/%/,"",$5); print $5}')"

TOP_PROCS_RAW="$(ps -eo pid,pcpu,pmem,comm 2>/dev/null | sort -k2 -rn | awk 'NR>1&&NR<=6{print}')"

# ── output ───────────────────────────────────────────────────────────────────
if [ "$JSON" -eq 1 ]; then
  PROCS_JSON="["; first=1
  while IFS= read -r line; do
    [ -z "$line" ] && continue
    [ "$first" -eq 0 ] && PROCS_JSON="$PROCS_JSON,"
    PROCS_JSON="$PROCS_JSON{\"pid\":$(echo "$line"|awk '{print $1}'),\"cpu_pct\":$(echo "$line"|awk '{print $2}'),\"mem_pct\":$(echo "$line"|awk '{print $3}'),\"name\":\"$(_jstr "$(echo "$line"|awk '{print $4}')")\"}"
    first=0
  done <<< "$TOP_PROCS_RAW"
  PROCS_JSON="$PROCS_JSON]"
  cat <<EOF
{
  "host": "$(_jstr "$HOST")",
  "os": "$(_jstr "$OS_NAME")",
  "uptime": "$(_jstr "$UPTIME_STR")",
  "load_1m": "$LOAD_1", "load_5m": "$LOAD_5", "load_15m": "$LOAD_15",
  "cpu_usage_pct": "$CPU_USAGE",
  "memory_total_bytes": $MEM_TOTAL_BYTES,
  "memory_free_bytes": $MEM_FREE_BYTES,
  "memory_used_bytes": $MEM_USED_BYTES,
  "memory_used_pct": $MEM_USED_PCT,
  "disk_total_1k": ${DISK_TOTAL:-0},
  "disk_used_1k": ${DISK_USED:-0},
  "disk_avail_1k": ${DISK_AVAIL:-0},
  "disk_used_pct": ${DISK_PCT:-0},
  "top_procs": $PROCS_JSON
}
EOF
else
  echo "=== HOST ==="; echo "$HOST"
  if [ "$OS" = "Darwin" ]; then sw_vers 2>/dev/null
  else (. /etc/os-release 2>/dev/null; echo "${PRETTY_NAME:-$(uname -sr)}"); fi
  echo "=== UPTIME / LOAD ==="; echo "$UPTIME_STR"
  echo "=== CPU ==="
  if [ "$OS" = "Darwin" ]; then top -l 1 -n 0 2>/dev/null | grep -E "CPU usage" || echo n/a
  else grep 'cpu ' /proc/stat >/dev/null 2>&1 && echo "load: $(cut -d' ' -f1-3 /proc/loadavg)" || echo n/a; fi
  echo "=== MEMORY ==="
  if [ "$OS" = "Darwin" ]; then vm_stat 2>/dev/null | head -6
  else free -h 2>/dev/null || head -3 /proc/meminfo; fi
  echo "=== DISK ==="; df -h / 2>/dev/null
  echo "=== TOP 5 PROCS BY CPU ==="; ps -eo pid,pcpu,pmem,comm 2>/dev/null | sort -k2 -rn | head -6
fi
exit 0
