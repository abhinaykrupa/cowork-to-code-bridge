#!/usr/bin/env bash
# process_kill.sh — terminate a named process or PID on this machine.
#
# Usage
# -----
#   process_kill.sh <name|PID> [--all] [--json]
#
#   Name path : exact match via pgrep -x.
#               Refuses if >1 match unless --all is passed.
#   PID path  : numeric PID; must exist and be > 10.
#   --json    : emit a machine-parseable result object instead of text.
#
# Safety guards
# -------------
#   - PID ≤ 10 refused (kernel/init territory on all UNIX-like systems)
#   - Protected names refused: launchd, kernel_task, systemd, init, kernel, kthreadd
#   - Sends SIGTERM (graceful), never SIGKILL
#   - Confirms process is gone after the signal
#
# JSON output (--json)
# --------------------
# A stable object Cowork can consume without scraping text:
#   { "ok", "target", "mode": "pid"|"name", "killed": [pids],
#     "remaining": [pids], "error": "<msg or null>" }
# On refusal/error, ok=false and error is set; killed/remaining reflect state.
#
# Works on macOS and Linux. No deps beyond bash + coreutils.
#
# Testability hooks (used by tests/test_system_scripts.py)
#   BRIDGE_PGREP_CMD   override pgrep binary
#   BRIDGE_KILL_CMD    override kill binary
set -uo pipefail

BRIDGE_PGREP_CMD="${BRIDGE_PGREP_CMD:-pgrep}"
BRIDGE_KILL_CMD="${BRIDGE_KILL_CMD:-kill}"

TARGET="${1:?usage: process_kill.sh <name|PID> [--all] [--json]}"
ALL_FLAG=0
JSON=0
shift || true
for arg in "$@"; do
  case "$arg" in
    --all)  ALL_FLAG=1 ;;
    --json) JSON=1 ;;
  esac
done

PROTECTED_NAMES=("launchd" "kernel_task" "systemd" "init" "kernel" "kthreadd")

_is_protected() {
  local name="$1"
  for pname in "${PROTECTED_NAMES[@]}"; do
    [[ "$name" == "$pname" ]] && return 0
  done
  return 1
}

# ── JSON emitters ────────────────────────────────────────────────────────────
# Emit a JSON result and exit with the given code. Whitespace-separated PID
# lists are turned into JSON arrays; error is a string or null.
_json_emit() {
  local ok="$1" mode="$2" killed="$3" remaining="$4" err="$5" code="$6"
  python3 - "$ok" "$TARGET" "$mode" "$killed" "$remaining" "$err" <<'PY'
import json, sys
ok, target, mode, killed, remaining, err = sys.argv[1:7]
to_list = lambda s: [int(x) for x in s.split()] if s.strip() else []
print(json.dumps({
    "ok": ok == "1",
    "target": target,
    "mode": mode,
    "killed": to_list(killed),
    "remaining": to_list(remaining),
    "error": err if err else None,
}))
PY
  exit "$code"
}

# Fail helper: in JSON mode emit structured error, else print to stderr.
_fail() {
  local msg="$1" mode="${2:-}" code="${3:-1}"
  if [[ "$JSON" -eq 1 ]]; then
    _json_emit 0 "$mode" "" "" "$msg" "$code"
  fi
  echo "ERROR: $msg" >&2
  exit "$code"
}

# Refuse protected names before any pgrep/kill call.
if _is_protected "$TARGET"; then
  _fail "refusing to kill protected process: $TARGET" "" 1
fi

# ─── PID path ─────────────────────────────────────────────────────────────────
if [[ "$TARGET" =~ ^[0-9]+$ ]]; then
  PID="$TARGET"

  if (( PID <= 10 )); then
    _fail "refusing to kill PID $PID (≤ 10 is kernel/init territory)" "pid" 1
  fi

  if ! "$BRIDGE_KILL_CMD" -0 "$PID" 2>/dev/null; then
    _fail "no process with PID $PID" "pid" 1
  fi

  PROC_NAME="$(ps -p "$PID" -o comm= 2>/dev/null | tr -d ' ' || echo '?')"
  if _is_protected "$PROC_NAME"; then
    _fail "refusing to kill protected process: $PROC_NAME (PID $PID)" "pid" 1
  fi

  [[ "$JSON" -eq 0 ]] && echo "Sending SIGTERM to PID $PID ($PROC_NAME)..."
  "$BRIDGE_KILL_CMD" -TERM "$PID"

  for i in 1 2 3 4 5 6; do
    sleep 0.5
    if ! "$BRIDGE_KILL_CMD" -0 "$PID" 2>/dev/null; then
      if [[ "$JSON" -eq 1 ]]; then
        _json_emit 1 "pid" "$PID" "" "" 0
      fi
      echo "✓ PID $PID ($PROC_NAME) is gone"
      exit 0
    fi
  done
  if [[ "$JSON" -eq 1 ]]; then
    _json_emit 0 "pid" "" "$PID" "PID $PID still alive after 3s — may need SIGKILL" 1
  fi
  echo "⚠ PID $PID ($PROC_NAME) still alive after 3s — may need SIGKILL" >&2
  exit 1
fi

# ─── Name path ────────────────────────────────────────────────────────────────
# pgrep -x: exact name match (won't kill 'rail' when asked for 'rails').
PIDS="$("$BRIDGE_PGREP_CMD" -x "$TARGET" 2>/dev/null || true)"

if [[ -z "$PIDS" ]]; then
  _fail "no process named '$TARGET' found" "name" 1
fi

PID_COUNT="$(echo "$PIDS" | wc -l | tr -d ' ')"

if [[ "$PID_COUNT" -gt 1 && "$ALL_FLAG" -eq 0 ]]; then
  if [[ "$JSON" -eq 1 ]]; then
    _json_emit 0 "name" "" "$(echo "$PIDS" | tr '\n' ' ')" \
      "$PID_COUNT processes named '$TARGET' found — pass --all to kill all, or use a specific PID" 1
  fi
  echo "ERROR: $PID_COUNT processes named '$TARGET' found (PIDs: $(echo "$PIDS" | tr '\n' ' '))" >&2
  echo "  Pass --all to kill all of them, or use a specific PID instead." >&2
  exit 1
fi

KILLED_PIDS=""
KILLED=0
while IFS= read -r pid; do
  [[ -z "$pid" ]] && continue
  if (( pid <= 10 )); then
    [[ "$JSON" -eq 0 ]] && echo "  skipping PID $pid (≤ 10)" >&2
    continue
  fi
  [[ "$JSON" -eq 0 ]] && echo "Sending SIGTERM to PID $pid ($TARGET)..."
  if "$BRIDGE_KILL_CMD" -TERM "$pid" 2>/dev/null; then
    KILLED=$(( KILLED + 1 ))
    KILLED_PIDS="$KILLED_PIDS $pid"
  else
    [[ "$JSON" -eq 0 ]] && echo "  WARNING: could not send SIGTERM to PID $pid" >&2
  fi
done <<< "$PIDS"

if [[ "$KILLED" -eq 0 ]]; then
  _fail "no processes were killed" "name" 1
fi

sleep 0.5
REMAINING_PIDS="$({ "$BRIDGE_PGREP_CMD" -x "$TARGET" 2>/dev/null || true; } | tr '\n' ' ')"
REMAINING="$(echo "$REMAINING_PIDS" | wc -w | tr -d ' ')"
if [[ "$REMAINING" -eq 0 ]]; then
  if [[ "$JSON" -eq 1 ]]; then
    _json_emit 1 "name" "$KILLED_PIDS" "" "" 0
  fi
  echo "✓ $KILLED '$TARGET' process(es) terminated"
else
  if [[ "$JSON" -eq 1 ]]; then
    _json_emit 0 "name" "$KILLED_PIDS" "$REMAINING_PIDS" \
      "$REMAINING '$TARGET' process(es) still alive after SIGTERM — may need SIGKILL" 1
  fi
  echo "⚠ $REMAINING '$TARGET' process(es) still alive after SIGTERM — may need SIGKILL" >&2
  exit 1
fi
