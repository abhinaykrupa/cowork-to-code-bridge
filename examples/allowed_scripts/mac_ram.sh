#!/usr/bin/env bash
# mac_ram.sh — RAM usage summary (macOS or Linux).
#
# Usage: mac_ram.sh [--json]
#   (no flag)   human-readable text (default)
#   --json      structured JSON — parse with json.loads() in Cowork
#
# JSON fields: total_bytes, free_bytes, used_bytes, used_pct
# No external dependencies (no jq, no python).
set -u

JSON=0
for arg in "$@"; do [ "$arg" = "--json" ] && JSON=1; done

OS="$(uname -s)"

TOTAL_BYTES=0; FREE_BYTES=0; USED_BYTES=0; USED_PCT=0
if [ "$OS" = "Darwin" ]; then
  TOTAL_BYTES="$(sysctl -n hw.memsize 2>/dev/null || echo 0)"
  PAGE_SIZE="$(sysctl -n hw.pagesize 2>/dev/null || echo 4096)"
  PAGES_FREE="$(vm_stat 2>/dev/null | awk '/^Pages free/{gsub(/\./,"",$3); print $3}' || echo 0)"
  FREE_BYTES=$(( PAGES_FREE * PAGE_SIZE ))
  USED_BYTES=$(( TOTAL_BYTES - FREE_BYTES ))
  [ "$TOTAL_BYTES" -gt 0 ] && USED_PCT=$(( USED_BYTES * 100 / TOTAL_BYTES ))
elif command -v free >/dev/null 2>&1; then
  eval "$(free | awk '/^Mem:/{printf "TOTAL_BYTES=%d USED_BYTES=%d FREE_BYTES=%d", $2*1024, $3*1024, $4*1024}')"
  [ "$TOTAL_BYTES" -gt 0 ] && USED_PCT=$(( USED_BYTES * 100 / TOTAL_BYTES ))
fi

if [ "$JSON" -eq 1 ]; then
  cat <<EOF
{
  "total_bytes": ${TOTAL_BYTES:-0},
  "free_bytes": ${FREE_BYTES:-0},
  "used_bytes": ${USED_BYTES:-0},
  "used_pct": ${USED_PCT:-0}
}
EOF
else
  if [ "$OS" = "Darwin" ]; then
    echo "Total RAM: $(( TOTAL_BYTES / 1024 / 1024 / 1024 )) GB"
    echo "--- vm_stat ---"; vm_stat 2>/dev/null
  else
    free -h 2>/dev/null || cat /proc/meminfo 2>/dev/null | head -5
  fi
fi
exit 0
