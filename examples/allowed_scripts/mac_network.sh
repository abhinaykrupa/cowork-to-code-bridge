#!/usr/bin/env bash
# mac_network.sh — network status (macOS or Linux). Args: none.
set -u
echo "=== interfaces (active) ==="
ip -brief addr 2>/dev/null | grep -v '127.0.0.1' \
  || ifconfig 2>/dev/null | grep -E "^[a-z]|inet " | grep -v "127.0.0.1" | head -20
echo "=== default route ==="
ip route show default 2>/dev/null || route -n get default 2>/dev/null | grep -E "gateway|interface"
echo "=== connectivity ==="
if ping -c 2 -W 3 1.1.1.1 >/dev/null 2>&1 || ping -c 2 -t 3 1.1.1.1 >/dev/null 2>&1; then
  echo "online (1.1.1.1 reachable)"
else
  echo "no connectivity"
fi
exit 0
