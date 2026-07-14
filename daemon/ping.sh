#!/usr/bin/env bash
# ping.sh — reference copy of the script install.sh writes into
# $BRIDGE_ROOT/scripts/ping.sh. Used by daemon_alive() to confirm the daemon
# is alive and able to execute scripts end-to-end.
echo "OK"
echo "pwd: $(pwd)"
echo "ts: $(date -u +%Y-%m-%dT%H:%M:%SZ)"
