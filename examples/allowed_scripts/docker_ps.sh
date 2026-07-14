#!/usr/bin/env bash
# docker_ps.sh — list running Docker containers (macOS or Linux).
# Usage: docker_ps.sh [--json]
#   (no flag)   human-readable table (default)
#   --json      structured JSON — parse with json.loads() in Cowork
# JSON shape: {"ok": bool, "error": str|null, "containers": [{name,image,status,ports}, ...]}
set -u

JSON=0
for arg in "$@"; do [ "$arg" = "--json" ] && JSON=1; done

emit_error() {
  # $1 = error message
  if [ "$JSON" -eq 1 ]; then
    esc="$(printf '%s' "$1" | sed 's/\\/\\\\/g; s/"/\\"/g')"
    printf '{\n  "ok": false,\n  "error": "%s",\n  "containers": []\n}\n' "$esc"
    exit 0
  fi
  echo "$1" >&2
  exit 1
}

if ! command -v docker >/dev/null 2>&1; then
  emit_error "Docker is not installed or not in PATH."
fi

if ! docker info >/dev/null 2>&1; then
  emit_error "Docker is installed but the daemon is not running or not reachable."
fi

if [ "$JSON" -eq 1 ]; then
  # docker emits one JSON object per running container; wrap them into an array.
  first=1
  printf '{\n  "ok": true,\n  "error": null,\n  "containers": ['
  while IFS= read -r line; do
    [ -z "$line" ] && continue
    name="$(printf '%s' "$line"  | sed -n 's/.*"Names":"\([^"]*\)".*/\1/p')"
    image="$(printf '%s' "$line" | sed -n 's/.*"Image":"\([^"]*\)".*/\1/p')"
    status="$(printf '%s' "$line"| sed -n 's/.*"Status":"\([^"]*\)".*/\1/p')"
    ports="$(printf '%s' "$line" | sed -n 's/.*"Ports":"\([^"]*\)".*/\1/p')"
    esc() { printf '%s' "$1" | sed 's/\\/\\\\/g; s/"/\\"/g'; }
    [ "$first" -eq 1 ] && first=0 || printf ','
    printf '\n    {"name": "%s", "image": "%s", "status": "%s", "ports": "%s"}' \
      "$(esc "$name")" "$(esc "$image")" "$(esc "$status")" "$(esc "$ports")"
  done <<EOF
$(docker ps --format '{{json .}}' 2>/dev/null)
EOF
  [ "$first" -eq 1 ] && printf ']\n}\n' || printf '\n  ]\n}\n'
  exit 0
fi

echo "=== RUNNING DOCKER CONTAINERS ==="
docker ps --format 'table {{.Names}}\t{{.Image}}\t{{.Status}}\t{{.Ports}}'

exit 0
