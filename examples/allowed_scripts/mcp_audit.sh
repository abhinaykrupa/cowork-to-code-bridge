#!/usr/bin/env bash
# mcp_audit.sh — enumerate MCPs registered in local Claude Code (all scopes).
#
# Motivation
# ----------
# `claude mcp list` only shows one surface at a time. There is no built-in
# tool to compare what's registered locally vs what a remote surface (e.g.
# Cowork) can reach. This script captures the local side so Cowork can
# produce a side-by-side diff of local MCPs vs Cowork-reachable connectors.
# (ref: anthropics/claude-code#56353, labeled area:mcp + enhancement)
#
# Usage from Cowork
# -----------------
#   r = call_remote("scripts/mcp_audit.sh")
#   # r["stdout"] contains JSON with the local MCP registry snapshot
#
# Output format
# -------------
# {"claude_version":"...","mcps":[{"scope":"...","name":"...","type":"...","command":"..."},...]}
# Falls back to {"claude_version":"...","mcps_raw":"<plain text>"} for older
# Claude Code versions that do not support --output-format json on mcp list.
set -uo pipefail

find_claude() {
  local p; p="$(command -v claude 2>/dev/null || true)"
  if [[ -n "$p" && -x "$p" ]]; then echo "$p"; return 0; fi
  local cand
  for cand in /opt/homebrew/bin/claude /usr/local/bin/claude \
              "$HOME/.local/bin/claude" "$HOME/.claude/bin/claude"; do
    [[ -x "$cand" ]] && { echo "$cand"; return 0; }
  done
  local appdir="$HOME/Library/Application Support/Claude/claude-code"
  if [[ -d "$appdir" ]]; then
    local b; b="$(find "$appdir" -maxdepth 4 -type f -name claude -perm -u+x 2>/dev/null | sort -V | tail -1)"
    [[ -n "$b" && -x "$b" ]] && { echo "$b"; return 0; }
  fi
  return 1
}

CLAUDE_BIN="$(find_claude 2>/dev/null || true)"
if [[ -z "${CLAUDE_BIN:-}" ]]; then
  printf '{"error":"claude CLI not found — install it: curl -fsSL https://claude.ai/install.sh | bash","mcps":[]}\n'
  exit 127
fi

CLAUDE_VERSION="$("$CLAUDE_BIN" --version 2>/dev/null | head -1 | tr -d '\n' || echo 'unknown')"
HOSTNAME_VAL="$(hostname 2>/dev/null || echo 'unknown')"
TIMESTAMP="$(date -u +%Y-%m-%dT%H:%M:%SZ 2>/dev/null || echo 'unknown')"

# Try JSON output (supported in Claude Code >= 1.x with mcp list --output-format).
# If the flag is unrecognised, fall back to plain-text and wrap it.
if MCP_JSON="$("$CLAUDE_BIN" mcp list --output-format json 2>/dev/null)" && \
   echo "$MCP_JSON" | python3 -c "import json,sys; json.load(sys.stdin)" 2>/dev/null; then
  # Wrap with audit metadata so Cowork has context alongside the raw list.
  python3 - "$CLAUDE_VERSION" "$HOSTNAME_VAL" "$TIMESTAMP" "$MCP_JSON" <<'PY'
import json, sys
version, host, ts, raw = sys.argv[1], sys.argv[2], sys.argv[3], sys.argv[4]
mcps = json.loads(raw) if isinstance(json.loads(raw), list) else json.loads(raw).get("mcps", json.loads(raw))
print(json.dumps({
    "claude_version": version,
    "hostname": host,
    "timestamp": ts,
    "mcp_count": len(mcps) if isinstance(mcps, list) else "unknown",
    "mcps": mcps,
}))
PY
else
  # Older Claude Code: plain-text fallback.
  MCP_TEXT="$("$CLAUDE_BIN" mcp list 2>&1 || echo '(no MCPs registered or command failed)')"
  python3 - "$CLAUDE_VERSION" "$HOSTNAME_VAL" "$TIMESTAMP" "$MCP_TEXT" <<'PY'
import json, sys
version, host, ts, text = sys.argv[1], sys.argv[2], sys.argv[3], sys.argv[4]
print(json.dumps({
    "claude_version": version,
    "hostname": host,
    "timestamp": ts,
    "note": "plain-text fallback (upgrade claude CLI for structured JSON output)",
    "mcps_raw": text,
}))
PY
fi
