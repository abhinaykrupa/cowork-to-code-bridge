#!/usr/bin/env bash
# env_check.sh — show the environment values Cowork and Claude Code care about.
# Never prints secret VALUES (only whether they are set).
# Usage: env_check.sh [--json]
#   (no flag)   human-readable text (default)
#   --json      structured JSON — parse with json.loads() in Cowork
# JSON fields: bridge_root, bridge_root_exists, bridge_token_set,
#   claude_flags (null if unset), shell, home, os, claude_cli (null if missing).
set -uo pipefail

JSON=0
for arg in "$@"; do [ "$arg" = "--json" ] && JSON=1; done

root="${BRIDGE_ROOT:-$HOME/.cowork-to-code-bridge}"
[ -d "$root" ] && ROOT_EXISTS=1 || ROOT_EXISTS=0

if [ -n "${BRIDGE_TOKEN:-}" ]; then
  TOKEN_SET=1
elif [ -f "$root/.env" ] && grep -q '^BRIDGE_TOKEN=' "$root/.env" 2>/dev/null; then
  TOKEN_SET=1
else
  TOKEN_SET=0
fi

if [ "$(uname)" = "Darwin" ]; then
  OS_DESC="macOS $(sw_vers -productVersion 2>/dev/null || echo '?')"
elif [ -r /etc/os-release ]; then
  OS_DESC="$(. /etc/os-release && echo "$PRETTY_NAME")"
else
  OS_DESC="$(uname -s) $(uname -r)"
fi

claude_path="$(command -v claude 2>/dev/null || true)"

if [ "$JSON" -eq 1 ]; then
  jesc() { printf '%s' "$1" | sed 's/\\/\\\\/g; s/"/\\"/g'; }
  jstr_or_null() { if [ -z "$1" ]; then printf 'null'; else printf '"%s"' "$(jesc "$1")"; fi; }
  bool() { [ "$1" -eq 1 ] && printf 'true' || printf 'false'; }
  printf '{\n'
  printf '  "bridge_root": "%s",\n' "$(jesc "$root")"
  printf '  "bridge_root_exists": %s,\n' "$(bool "$ROOT_EXISTS")"
  printf '  "bridge_token_set": %s,\n' "$(bool "$TOKEN_SET")"
  printf '  "claude_flags": %s,\n' "$(jstr_or_null "${CLAUDE_FLAGS:-}")"
  printf '  "shell": "%s",\n' "$(jesc "${SHELL:-unknown}")"
  printf '  "home": "%s",\n' "$(jesc "${HOME:-unknown}")"
  printf '  "os": "%s",\n' "$(jesc "$OS_DESC")"
  printf '  "claude_cli": %s\n' "$(jstr_or_null "$claude_path")"
  printf '}\n'
  exit 0
fi

echo "=== BRIDGE ENVIRONMENT ==="
printf '%-13s: %s\n' "PATH" "${PATH:-}"
if [ "$ROOT_EXISTS" -eq 1 ]; then
  printf '%-13s: %s  (exists)\n' "BRIDGE_ROOT" "$root"
else
  printf '%-13s: %s  (MISSING)\n' "BRIDGE_ROOT" "$root"
fi
if [ "$TOKEN_SET" -eq 1 ]; then
  if [ -n "${BRIDGE_TOKEN:-}" ]; then
    printf '%-13s: set\n' "BRIDGE_TOKEN"
  else
    printf '%-13s: set (in .env)\n' "BRIDGE_TOKEN"
  fi
else
  printf '%-13s: not set\n' "BRIDGE_TOKEN"
fi
printf '%-13s: %s\n' "CLAUDE_FLAGS" "${CLAUDE_FLAGS:-(not set)}"
printf '%-13s: %s\n' "SHELL" "${SHELL:-unknown}"
printf '%-13s: %s\n' "HOME" "${HOME:-unknown}"
printf '%-13s: %s\n' "OS" "$OS_DESC"
printf '%-13s: %s\n' "claude CLI" "${claude_path:-not found on PATH}"
exit 0
