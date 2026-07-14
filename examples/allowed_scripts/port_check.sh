#!/usr/bin/env bash
# port_check.sh — show what is listening on a TCP port (macOS or Linux).
# Usage: port_check.sh PORT [--json]
#   (no flag)   human-readable text (default)
#   --json      structured JSON — parse with json.loads() in Cowork
# JSON fields: port (int), listening (bool), tool (lsof|ss|netstat|null),
#   raw (the captured listener lines as a string; "" when nothing is listening).
set -u

JSON=0
PORT=""
for arg in "$@"; do
  if [ "$arg" = "--json" ]; then
    JSON=1
  else
    PORT="$arg"
  fi
done

usage() {
  echo "Usage: $0 PORT [--json]" >&2
  echo "PORT must be a number from 1 to 65535." >&2
  exit 2
}

case "$PORT" in
  ""|*[!0-9]*) usage ;;
esac

if [ "$PORT" -lt 1 ] || [ "$PORT" -gt 65535 ]; then
  usage
fi

found=0
tool=""
raw=""

if command -v lsof >/dev/null 2>&1; then
  raw="$(lsof -nP -iTCP:"$PORT" -sTCP:LISTEN 2>/dev/null || true)"
  if [ -n "$raw" ]; then found=1; tool="lsof"; fi
fi

if [ "$found" -eq 0 ] && command -v ss >/dev/null 2>&1; then
  raw="$(ss -H -ltnp "sport = :$PORT" 2>/dev/null || true)"
  if [ -n "$raw" ]; then found=1; tool="ss"; fi
fi

if [ "$found" -eq 0 ] && command -v netstat >/dev/null 2>&1; then
  raw="$(netstat -an 2>/dev/null | grep -E "([.:])${PORT}[[:space:]].*LISTEN" || true)"
  if [ -n "$raw" ]; then found=1; tool="netstat"; fi
fi

if [ "$JSON" -eq 1 ]; then
  jesc() { printf '%s' "$1" | sed 's/\\/\\\\/g; s/"/\\"/g' | awk 'BEGIN{ORS=""} {if(NR>1) printf "\\n"; print}'; }
  bool() { [ "$1" -eq 1 ] && printf 'true' || printf 'false'; }
  tool_json() { if [ -z "$tool" ]; then printf 'null'; else printf '"%s"' "$tool"; fi; }
  printf '{\n'
  printf '  "port": %s,\n' "$PORT"
  printf '  "listening": %s,\n' "$(bool "$found")"
  printf '  "tool": %s,\n' "$(tool_json)"
  printf '  "raw": "%s"\n' "$(jesc "$raw")"
  printf '}\n'
  exit 0
fi

echo "=== TCP LISTENERS ON PORT $PORT ==="
if [ "$found" -eq 1 ]; then
  [ "$tool" = "ss" ] && echo "State Recv-Q Send-Q Local Address:Port Peer Address:Port Process"
  echo "$raw"
else
  echo "No TCP listener found on port $PORT."
fi

exit 0
