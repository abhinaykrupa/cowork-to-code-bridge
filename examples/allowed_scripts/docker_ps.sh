#!/usr/bin/env bash
# docker_ps.sh — list running Docker containers (macOS or Linux).
# Usage from Cowork: call_remote("scripts/docker_ps.sh")
set -u

if ! command -v docker >/dev/null 2>&1; then
  echo "Docker is not installed or not in PATH." >&2
  exit 1
fi

if ! docker info >/dev/null 2>&1; then
  echo "Docker is installed but the daemon is not running or not reachable." >&2
  exit 1
fi

echo "=== RUNNING DOCKER CONTAINERS ==="
docker ps --format 'table {{.Names}}\t{{.Image}}\t{{.Status}}\t{{.Ports}}'

exit 0
