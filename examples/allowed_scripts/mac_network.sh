#!/usr/bin/env bash
# mac_network.sh — network status. Args: none.
set -u
echo "=== interfaces (active) ==="; ifconfig 2>/dev/null | grep -E "^[a-z]|inet " | grep -v "127.0.0.1" | head -20
echo "=== default route ==="; route -n get default 2>/dev/null | grep -E "gateway|interface"
echo "=== connectivity ==="; ping -c 2 -t 3 1.1.1.1 2>/dev/null | tail -2 || echo "no connectivity"
exit 0
