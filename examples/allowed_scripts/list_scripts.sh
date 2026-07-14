#!/usr/bin/env bash
# list_scripts.sh — list every script the bridge can run, with its one-line description.
# Lets Cowork discover what's available instead of guessing.
#
# Usage: list_scripts.sh [--json]
#   (no flag)   human-readable text (default)
#   --json      structured JSON — parse with json.loads() in Cowork
#
# JSON shape: {"scripts":[{"name":"mac_ram.sh","description":"..."},...],"count":N}
# No external dependencies (no jq, no python).
# Usage from Cowork: call_remote("scripts/list_scripts.sh")  # or ("scripts/list_scripts.sh", "--json")
set -uo pipefail
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

JSON=0
for arg in "$@"; do [ "$arg" = "--json" ] && JSON=1; done

# Escape a string for safe embedding in JSON (no jq required).
_jstr() {
  local s="$1"
  s="${s//\\/\\\\}"   # backslash first
  s="${s//\"/\\\"}"   # then double-quote
  s="${s//	/\\t}"    # literal tab
  printf '%s' "$s"
}

shopt -s nullglob

if [ "$JSON" -eq 1 ]; then
  out="{\"scripts\":["
  first=1
  count=0
  for f in "$DIR"/*.sh; do
    name="$(basename "$f")"
    [ "$name" = "list_scripts.sh" ] && continue
    desc="$(awk 'NR>1 && /^#/ {sub(/^# */,""); print; exit}' "$f")"
    [ "$first" -eq 0 ] && out="$out,"
    out="$out{\"name\":\"$(_jstr "$name")\",\"description\":\"$(_jstr "${desc:-}")\"}"
    first=0
    count=$((count + 1))
  done
  out="$out],\"count\":$count}"
  printf '%s\n' "$out"
  exit 0
fi

echo "=== AVAILABLE BRIDGE SCRIPTS ==="
echo "(call any of these with call_remote(\"scripts/<name>\"))"
echo
found=0
for f in "$DIR"/*.sh; do
  name="$(basename "$f")"
  [ "$name" = "list_scripts.sh" ] && continue
  # Pull the first comment line after the shebang as the description.
  desc="$(awk 'NR>1 && /^#/ {sub(/^# */,""); print; exit}' "$f")"
  printf '  %-22s %s\n' "$name" "${desc:-(no description)}"
  found=$((found + 1))
done
[ "$found" -eq 0 ] && echo "  (no scripts found in $DIR)"
exit 0
