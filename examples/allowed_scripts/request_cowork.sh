#!/usr/bin/env bash
# request_cowork.sh — REVERSE direction: hand a request from this machine
# (Claude Code) to a Claude Cowork session.
#
# Why this is an async INBOX, not a live call:
#   The Cowork sandbox has no inbound address — nothing on the Mac can "call"
#   it. So this drops a request into BRIDGE_ROOT/to_cowork/, and a Cowork
#   session picks it up the next time one is open and checks its inbox. There
#   is no always-on agent on the Cowork side, so delivery is best-effort /
#   whenever-Cowork-is-next-open. If you need a guaranteed live exchange, just
#   open Cowork and ask directly.
#
# Usage (from Claude Code on the Mac, or any shell):
#   request_cowork.sh "Summarize the latest PRs and draft release notes"
#   request_cowork.sh "Research X and write a doc" --wait 300   # poll for a reply
#
# Args:
#   $1            the request text for Cowork (required)
#   --wait SECS   optional: poll cowork_results/ for a reply for up to SECS
set -euo pipefail

BRIDGE_ROOT="${BRIDGE_ROOT:-$HOME/.cowork-to-code-bridge}"
INBOX="$BRIDGE_ROOT/to_cowork"
REPLIES="$BRIDGE_ROOT/cowork_results"

REQUEST="${1:-}"
if [[ -z "$REQUEST" ]]; then
  echo "usage: request_cowork.sh \"<request text>\" [--wait SECONDS]" >&2
  exit 2
fi
shift || true

WAIT=0
if [[ "${1:-}" == "--wait" ]]; then
  WAIT="${2:-300}"
fi

mkdir -p "$INBOX" "$REPLIES"
chmod 700 "$INBOX" "$REPLIES" 2>/dev/null || true

# Unique id. Avoid $RANDOM-only collisions; combine epoch + pid + a short rand.
ID="$(date +%s)_$$_${RANDOM}"
TOKEN=""
if [[ -f "$BRIDGE_ROOT/.env" ]]; then
  TOKEN="$(grep '^BRIDGE_TOKEN=' "$BRIDGE_ROOT/.env" 2>/dev/null | head -1 | cut -d= -f2- | tr -d '"'"'"' [:space:]')"
fi

# Atomic write: .tmp then mv, so a polling Cowork session never reads a partial file.
TMP="$INBOX/.$ID.json.tmp"
OUT="$INBOX/$ID.json"
# JSON-escape the request via python (stdlib) for safety with quotes/newlines.
python3 - "$ID" "$REQUEST" "$TOKEN" >"$TMP" <<'PY'
import json, sys, time
_id, req, tok = sys.argv[1], sys.argv[2], sys.argv[3]
obj = {"id": _id, "request": req, "ts": time.time(), "from": "claude-code"}
if tok:
    obj["token"] = tok
print(json.dumps(obj))
PY
mv "$TMP" "$OUT"
echo "queued request for Cowork: $OUT"
echo "  → a Cowork session will see it next time one is open and checks its inbox."

if [[ "$WAIT" -gt 0 ]]; then
  echo "  waiting up to ${WAIT}s for a reply in $REPLIES/$ID.json ..."
  REPLY_FILE="$REPLIES/$ID.json"
  deadline=$(( $(date +%s) + WAIT ))
  while [[ "$(date +%s)" -lt "$deadline" ]]; do
    if [[ -f "$REPLY_FILE" ]]; then
      echo "=== reply from Cowork ==="
      cat "$REPLY_FILE"
      exit 0
    fi
    sleep 2
  done
  echo "  no reply within ${WAIT}s (Cowork may not be open right now)." >&2
  echo "  the request stays queued at $OUT until a Cowork session picks it up." >&2
  exit 0
fi
