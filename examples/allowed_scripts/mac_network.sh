#!/usr/bin/env bash
# mac_network.sh — network status (macOS or Linux). Args: [--json]
#   (no flag)   human-readable text (default)
#   --json      structured JSON — parse with json.loads()
# JSON fields: interfaces[] (each: name, addr), default_route, online (bool)
# No external dependencies (no jq, no python).
set -u
JSON=0
for arg in "$@"; do [ "$arg" = "--json" ] && JSON=1; done

get_interfaces() {
  # one "name addr" pair per line, loopback excluded. Prefer `ip` (Linux),
  # fall back to `ifconfig` (macOS / older Linux).
  if command -v ip >/dev/null 2>&1; then
    ip -brief addr 2>/dev/null | grep -v '127.0.0.1' | awk 'NF>=3{print $1, $3}'
  else
    ifconfig 2>/dev/null | awk '
        /^[a-z]/{iface=$1; sub(/:$/,"",iface)}
        /inet /{if($2!="127.0.0.1") print iface, $2}'
  fi
}
get_default_route() {
  if command -v ip >/dev/null 2>&1; then
    ip route show default 2>/dev/null | awk '{print $3; exit}'
  else
    route -n get default 2>/dev/null | awk '/gateway/{print $2; exit}'
  fi
}
is_online() {
  ping -c 2 -W 3 1.1.1.1 >/dev/null 2>&1 || ping -c 2 -t 3 1.1.1.1 >/dev/null 2>&1
}

if [ "$JSON" -eq 1 ]; then
  IFACES_JSON="$(get_interfaces | awk 'BEGIN{first=1; printf "["}
    NF>=1{
      name=$1; addr=$2;
      gsub(/"/,"\\\"",name); gsub(/"/,"\\\"",addr);
      if(!first) printf ",";
      printf "{\"name\":\"%s\",\"addr\":\"%s\"}", name, addr;
      first=0
    }
    END{printf "]"}')"
  ROUTE="$(get_default_route)"
  if is_online; then ONLINE=true; else ONLINE=false; fi
  cat <<EOF
{
  "interfaces": ${IFACES_JSON:-[]},
  "default_route": "${ROUTE:-}",
  "online": ${ONLINE}
}
EOF
else
  echo "=== interfaces (active) ==="
  ip -brief addr 2>/dev/null | grep -v '127.0.0.1' \
    || ifconfig 2>/dev/null | grep -E "^[a-z]|inet " | grep -v "127.0.0.1" | head -20
  echo "=== default route ==="
  ip route show default 2>/dev/null || route -n get default 2>/dev/null | grep -E "gateway|interface"
  echo "=== connectivity ==="
  if is_online; then
    echo "online (1.1.1.1 reachable)"
  else
    echo "no connectivity"
  fi
fi
exit 0
