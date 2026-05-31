#!/usr/bin/env bash
# port_check.sh — show what is listening on a TCP port (macOS or Linux).
# Usage from Cowork: call_remote("scripts/port_check.sh", args=["3000"])
set -u

usage() {
  echo "Usage: $0 PORT" >&2
  echo "PORT must be a number from 1 to 65535." >&2
  exit 2
}

PORT="${1:-}"
case "$PORT" in
  ""|*[!0-9]*) usage ;;
esac

if [ "$PORT" -lt 1 ] || [ "$PORT" -gt 65535 ]; then
  usage
fi

echo "=== TCP LISTENERS ON PORT $PORT ==="
found=0

if command -v lsof >/dev/null 2>&1; then
  if lsof -nP -iTCP:"$PORT" -sTCP:LISTEN 2>/dev/null; then
    found=1
  fi
fi

if [ "$found" -eq 0 ] && command -v ss >/dev/null 2>&1; then
  ss_output="$(ss -H -ltnp "sport = :$PORT" 2>/dev/null || true)"
  if [ -n "$ss_output" ]; then
    echo "State Recv-Q Send-Q Local Address:Port Peer Address:Port Process"
    echo "$ss_output"
    found=1
  fi
fi

if [ "$found" -eq 0 ] && command -v netstat >/dev/null 2>&1; then
  netstat_output="$(netstat -an 2>/dev/null | grep -E "([.:])${PORT}[[:space:]].*LISTEN" || true)"
  if [ -n "$netstat_output" ]; then
    echo "$netstat_output"
    found=1
  fi
fi

if [ "$found" -eq 0 ]; then
  echo "No TCP listener found on port $PORT."
fi

exit 0
