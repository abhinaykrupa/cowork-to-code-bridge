#!/usr/bin/env bash
# Test the reverse-direction (Claude Code -> Cowork) inbox: request_cowork.sh
# drops a well-formed JSON request, atomically, with the token attached.
set -euo pipefail
TMP="$(mktemp -d)"
export BRIDGE_ROOT="$TMP/bridge"
mkdir -p "$BRIDGE_ROOT"
printf 'BRIDGE_TOKEN=testtok123\n' > "$BRIDGE_ROOT/.env"

SCRIPT="$(cd "$(dirname "$0")/.." && pwd)/examples/allowed_scripts/request_cowork.sh"
bash "$SCRIPT" "do a thing with \"quotes\" and a newline" >/dev/null

f="$(ls "$BRIDGE_ROOT"/to_cowork/*.json)"
[ -f "$f" ] || { echo "FAIL: no request file written"; exit 1; }
# no leftover .tmp (atomic write)
ls "$BRIDGE_ROOT"/to_cowork/.*.json.tmp >/dev/null 2>&1 && { echo "FAIL: leftover .tmp"; exit 1; }
# valid JSON with the right fields + token
python3 - "$f" <<'PY'
import json,sys
d=json.load(open(sys.argv[1]))
assert d["request"].startswith("do a thing"), d
assert d["from"]=="claude-code", d
assert d["token"]=="testtok123", "token must be attached"
assert "id" in d and "ts" in d
print("PASS: request_cowork.sh writes valid, atomic, token-attached JSON")
PY
rm -rf "$TMP"
