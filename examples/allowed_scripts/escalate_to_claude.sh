#!/usr/bin/env bash
# escalate_to_claude.sh — hand a complex task from a daemon/agent to Claude Code
# on your machine, using your subscription (no token needed).
#
# Use from: Hermes, Open Claw, cron jobs, CI/CD workflows, or any external agent.
#
# Usage (from your escalating agent):
#   escalate_to_claude.sh "Debug the API health check failures and fix them" --wait 300
#   escalate_to_claude.sh "Summarize recent errors and suggest fixes"
#
# The request goes to BRIDGE_ROOT/to_cowork/ and waits for Claude Code in a
# Cowork chat to pick it up, debug, and reply to BRIDGE_ROOT/cowork_results/.
#
# Args:
#   $1            the escalation text (required)
#   --wait SECS   optional: poll for a reply for up to SECS (default: no wait)
#
set -euo pipefail

BRIDGE_ROOT="${BRIDGE_ROOT:-$HOME/.cowork-to-code-bridge}"
INBOX="$BRIDGE_ROOT/to_cowork"
REPLIES="$BRIDGE_ROOT/cowork_results"

REQUEST="${1:-}"
if [[ -z "$REQUEST" ]]; then
  echo "usage: escalate_to_claude.sh \"<escalation text>\" [--wait SECONDS]" >&2
  exit 2
fi
shift || true

WAIT=0
if [[ "${1:-}" == "--wait" ]]; then
  WAIT="${2:-300}"
  if [[ ! "$WAIT" =~ ^[0-9]+$ ]]; then
    echo "escalate_to_claude.sh: --wait expects a number of seconds, got: ${WAIT}" >&2
    exit 2
  fi
  shift 2 || true
fi

mkdir -p "$INBOX" "$REPLIES"
chmod 700 "$INBOX" "$REPLIES" 2>/dev/null || true

# Unique id. Avoid $RANDOM-only collisions; combine epoch + pid + a short rand.
ID="$(date +%s)_$$_${RANDOM}"
TOKEN=""
if [[ -f "$BRIDGE_ROOT/.env" ]]; then
  # Strip surrounding quotes then whitespace — same robust pipeline as install.sh.
  TOKEN="$(grep '^BRIDGE_TOKEN=' "$BRIDGE_ROOT/.env" 2>/dev/null | head -1 \
    | cut -d= -f2- | tr -d '"' | tr -d "'" | tr -d '[:space:]')"
fi

# Atomic write: .tmp then mv, so a polling Cowork session never reads a partial file.
TMP="$INBOX/.$ID.json.tmp"
OUT="$INBOX/$ID.json"

# Build JSON payload with escalation metadata.
python3 - "$ID" "$REQUEST" "$TOKEN" >"$TMP" <<'PY'
import json, sys, time, os
_id, req, tok = sys.argv[1], sys.argv[2], sys.argv[3]
obj = {
    "id": _id,
    "request": req,
    "ts": time.time(),
    "from": "escalation-daemon",
    "escalation_context": {
        "hostname": os.uname().nodename,
        "user": os.getenv("USER", "unknown"),
        "cwd": os.getcwd()
    }
}
if tok:
    obj["token"] = tok
print(json.dumps(obj))
PY
mv "$TMP" "$OUT"
echo "escalation queued for Claude Code: $OUT"
echo "  → waiting for a Cowork session to pick it up and reply..."

if [[ "$WAIT" -gt 0 ]]; then
  REPLY_FILE="$REPLIES/$ID.json"
  deadline=$(( $(date +%s) + WAIT ))
  while [[ "$(date +%s)" -lt "$deadline" ]]; do
    if [[ -f "$REPLY_FILE" ]]; then
      echo "=== Claude Code reply ==="
      cat "$REPLY_FILE"
      exit 0
    fi
    sleep 2
  done
  echo "  no reply within ${WAIT}s (Claude Code / Cowork may not be active right now)." >&2
  echo "  the escalation stays queued at $OUT until a Cowork session picks it up." >&2
  exit 0
fi
