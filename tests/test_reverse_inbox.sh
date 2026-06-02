#!/usr/bin/env bash
# Test the reverse-direction (Claude Code -> Cowork) inbox: request_cowork.sh
# drops a well-formed JSON request, atomically, with the token attached.
set -euo pipefail
TMP="$(mktemp -d)"
export BRIDGE_ROOT="$TMP/bridge"
mkdir -p "$BRIDGE_ROOT"
printf 'BRIDGE_TOKEN=testtok123\n' > "$BRIDGE_ROOT/.env"

SCRIPT="$(cd "$(dirname "$0")/.." && pwd)/examples/allowed_scripts/request_cowork.sh"
# Real embedded newline + quotes, to exercise JSON escaping.
bash "$SCRIPT" $'do a thing with "quotes"\nand a real newline' >/dev/null

# Collect request files robustly (nullglob avoids aborting under set -e if no match).
shopt -s nullglob
reqs=("$BRIDGE_ROOT"/to_cowork/*.json)
tmps=("$BRIDGE_ROOT"/to_cowork/.*.json.tmp)
shopt -u nullglob

[ "${#reqs[@]}" -eq 1 ] || { echo "FAIL: expected exactly 1 request file, got ${#reqs[@]}"; exit 1; }
[ "${#tmps[@]}" -eq 0 ] || { echo "FAIL: leftover .tmp file (atomic write broken)"; exit 1; }
f="${reqs[0]}"

# valid JSON with the right fields + token (incl. the embedded newline preserved)
python3 - "$f" <<'PY'
import json, sys
d = json.load(open(sys.argv[1]))
assert d["request"].startswith("do a thing"), d
assert "\n" in d["request"], "embedded newline must be preserved in JSON"
assert d["from"] == "claude-code", d
assert d["token"] == "testtok123", "token must be attached"
assert "id" in d and "ts" in d
print("PASS: request_cowork.sh writes valid, atomic, token-attached JSON (newline preserved)")
PY
rm -rf "$TMP"
