#!/usr/bin/env bash
# process_kill.sh — terminate a named process or PID on this machine.
#
# Usage
# -----
#   process_kill.sh <name|PID> [--all]
#
#   Name path : exact match via pgrep -x.
#               Refuses if >1 match unless --all is passed.
#   PID path  : numeric PID; must exist and be > 10.
#
# Safety guards
# -------------
#   - PID ≤ 10 refused (kernel/init territory on all UNIX-like systems)
#   - Protected names refused: launchd, kernel_task, systemd, init, kernel, kthreadd
#   - Sends SIGTERM (graceful), never SIGKILL
#   - Confirms process is gone after the signal
#
# Works on macOS and Linux. No deps beyond bash + coreutils.
#
# Testability hooks (used by tests/test_system_scripts.py)
#   BRIDGE_PGREP_CMD   override pgrep binary
#   BRIDGE_KILL_CMD    override kill binary
set -uo pipefail

BRIDGE_PGREP_CMD="${BRIDGE_PGREP_CMD:-pgrep}"
BRIDGE_KILL_CMD="${BRIDGE_KILL_CMD:-kill}"

TARGET="${1:?usage: process_kill.sh <name|PID> [--all]}"
ALL_FLAG=0
shift || true
for arg in "$@"; do [[ "$arg" == "--all" ]] && ALL_FLAG=1; done

PROTECTED_NAMES=("launchd" "kernel_task" "systemd" "init" "kernel" "kthreadd")

_is_protected() {
  local name="$1"
  for pname in "${PROTECTED_NAMES[@]}"; do
    [[ "$name" == "$pname" ]] && return 0
  done
  return 1
}

# Refuse protected names before any pgrep/kill call.
if _is_protected "$TARGET"; then
  echo "ERROR: refusing to kill protected process: $TARGET" >&2
  exit 1
fi

# ─── PID path ─────────────────────────────────────────────────────────────────
if [[ "$TARGET" =~ ^[0-9]+$ ]]; then
  PID="$TARGET"

  if (( PID <= 10 )); then
    echo "ERROR: refusing to kill PID $PID (≤ 10 is kernel/init territory)" >&2
    exit 1
  fi

  if ! "$BRIDGE_KILL_CMD" -0 "$PID" 2>/dev/null; then
    echo "ERROR: no process with PID $PID" >&2
    exit 1
  fi

  PROC_NAME="$(ps -p "$PID" -o comm= 2>/dev/null | tr -d ' ' || echo '?')"
  if _is_protected "$PROC_NAME"; then
    echo "ERROR: refusing to kill protected process: $PROC_NAME (PID $PID)" >&2
    exit 1
  fi

  echo "Sending SIGTERM to PID $PID ($PROC_NAME)..."
  "$BRIDGE_KILL_CMD" -TERM "$PID"

  for i in 1 2 3 4 5 6; do
    sleep 0.5
    if ! "$BRIDGE_KILL_CMD" -0 "$PID" 2>/dev/null; then
      echo "✓ PID $PID ($PROC_NAME) is gone"
      exit 0
    fi
  done
  echo "⚠ PID $PID ($PROC_NAME) still alive after 3s — may need SIGKILL" >&2
  exit 1
fi

# ─── Name path ────────────────────────────────────────────────────────────────
# pgrep -x: exact name match (won't kill 'rail' when asked for 'rails').
PIDS="$("$BRIDGE_PGREP_CMD" -x "$TARGET" 2>/dev/null || true)"

if [[ -z "$PIDS" ]]; then
  echo "ERROR: no process named '$TARGET' found" >&2
  exit 1
fi

PID_COUNT="$(echo "$PIDS" | wc -l | tr -d ' ')"

if [[ "$PID_COUNT" -gt 1 && "$ALL_FLAG" -eq 0 ]]; then
  echo "ERROR: $PID_COUNT processes named '$TARGET' found (PIDs: $(echo "$PIDS" | tr '\n' ' '))" >&2
  echo "  Pass --all to kill all of them, or use a specific PID instead." >&2
  exit 1
fi

KILLED=0
while IFS= read -r pid; do
  [[ -z "$pid" ]] && continue
  if (( pid <= 10 )); then
    echo "  skipping PID $pid (≤ 10)" >&2
    continue
  fi
  echo "Sending SIGTERM to PID $pid ($TARGET)..."
  if "$BRIDGE_KILL_CMD" -TERM "$pid" 2>/dev/null; then
    KILLED=$(( KILLED + 1 ))
  else
    echo "  WARNING: could not send SIGTERM to PID $pid" >&2
  fi
done <<< "$PIDS"

if [[ "$KILLED" -eq 0 ]]; then
  echo "ERROR: no processes were killed" >&2
  exit 1
fi

sleep 0.5
REMAINING="$({ "$BRIDGE_PGREP_CMD" -x "$TARGET" 2>/dev/null || true; } | wc -l | tr -d ' ')"
if [[ "$REMAINING" -eq 0 ]]; then
  echo "✓ $KILLED '$TARGET' process(es) terminated"
else
  echo "⚠ $REMAINING '$TARGET' process(es) still alive after SIGTERM — may need SIGKILL" >&2
  exit 1
fi
