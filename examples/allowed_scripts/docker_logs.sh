#!/usr/bin/env bash
# docker_logs.sh — tail a container's logs (macOS or Linux).
# Args: $1 = container name/ID (required), $2 = line count (optional, default 50).
# Usage from Cowork: call_remote("scripts/docker_logs.sh", args=["my-app", "100"])
set -u

usage() {
  echo "Usage: $0 CONTAINER [LINES]" >&2
  exit 2
}

CONTAINER="${1:-}"
LINES="${2:-50}"

[[ -n "$CONTAINER" ]] || usage

case "$LINES" in
  *[!0-9]*|'') usage ;;
esac
if [ "$LINES" -lt 1 ] || [ "$LINES" -gt 10000 ]; then
  echo "LINES must be a number from 1 to 10000." >&2
  exit 2
fi

if ! command -v docker >/dev/null 2>&1; then
  echo "Docker is not installed or not in PATH." >&2
  exit 1
fi

if ! docker info >/dev/null 2>&1; then
  echo "Docker is installed but the daemon is not running or not reachable." >&2
  exit 1
fi

if ! docker inspect "$CONTAINER" >/dev/null 2>&1; then
  echo "Container not found: $CONTAINER" >&2
  exit 1
fi

echo "=== DOCKER LOGS (last $LINES lines): $CONTAINER ==="
docker logs --tail "$LINES" "$CONTAINER"

exit 0
