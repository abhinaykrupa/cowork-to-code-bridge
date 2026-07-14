#!/usr/bin/env bash
# mac_disk.sh — disk usage (fast). Args: [path] [--json]   (path default /).
#   (no flag)   human-readable text (default)
#   --json      structured JSON for the queried path — parse with json.loads()
# JSON fields: path, total_1k, used_1k, avail_1k, used_pct
# No external dependencies (no jq, no python).
set -u
JSON=0; TARGET="/"
for arg in "$@"; do
  case "$arg" in
    --json) JSON=1 ;;
    *) TARGET="$arg" ;;
  esac
done
if [ "$JSON" -eq 1 ]; then
  # POSIX `df -P` gives stable 1K-block columns: Filesystem Blocks Used Avail Cap% Mount
  read -r TOTAL_1K USED_1K AVAIL_1K USED_PCT <<EOF
$(df -Pk "$TARGET" 2>/dev/null | awk 'NR==2{gsub(/%/,"",$5); print $2, $3, $4, $5}')
EOF
  cat <<EOF
{
  "path": "$TARGET",
  "total_1k": ${TOTAL_1K:-0},
  "used_1k": ${USED_1K:-0},
  "avail_1k": ${AVAIL_1K:-0},
  "used_pct": ${USED_PCT:-0}
}
EOF
else
  echo "=== DISK USAGE ==="; df -h "$TARGET" 2>/dev/null
  echo; echo "=== ALL MOUNTED VOLUMES ==="; df -h 2>/dev/null | grep -E "^/dev|Filesystem" | head -10
fi
exit 0
