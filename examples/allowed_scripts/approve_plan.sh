#!/usr/bin/env bash
# approve_plan.sh — plan approval gate for cowork-to-code-bridge.
#
# The bridge daemon runs this script BEFORE executing any task that includes a
# "plan" field. The plan text is passed on stdin.
#
# Exit codes:
#   0  — approved, proceed with execution
#   2  — rejected; print the reason to stderr and the bridge returns it to Cowork
#   (any other non-zero exit is also treated as a rejection)
#
# Install:
#   Copy this file to ~/.cowork-to-code-bridge/scripts/approve_plan.sh
#   and make it executable:  chmod +x ~/.cowork-to-code-bridge/scripts/approve_plan.sh
#
# If this file does NOT exist, the plan field is silently ignored and all tasks
# proceed normally. Create it only when you want a gate.
#
# Customise the BLOCKED_PATTERNS and REQUIRE_CONFIRMATION sections below for
# your own policy. The file ships as a no-op (approve everything) — uncomment
# the sections you want.

set -uo pipefail

PLAN="$(cat)"   # plan text arrives on stdin

# ── 1. Log every plan (always active) ────────────────────────────────────────
LOG_FILE="${BRIDGE_ROOT:-$HOME/.cowork-to-code-bridge}/plan_log.jsonl"
printf '{"ts":"%s","plan":%s}\n' \
    "$(date -u +%Y-%m-%dT%H:%M:%SZ)" \
    "$(printf '%s' "$PLAN" | python3 -c 'import json,sys; print(json.dumps(sys.stdin.read()))')" \
    >> "$LOG_FILE" 2>/dev/null || true

# ── 2. Block dangerous patterns ───────────────────────────────────────────────
# Uncomment and extend to block tasks whose plan contains specific phrases.
# Each pattern is a grep -iE regex tested against the plan text.
#
# BLOCKED_PATTERNS=(
#   "ALTER TABLE"
#   "DROP (TABLE|DATABASE|COLUMN)"
#   "DELETE FROM"
#   "git push --force"
#   "rm -rf"
# )
#
# for pattern in "${BLOCKED_PATTERNS[@]}"; do
#   if echo "$PLAN" | grep -qiE "$pattern"; then
#     echo "Plan contains blocked pattern: $pattern" >&2
#     echo "Full plan: $PLAN" >&2
#     exit 2
#   fi
# done

# ── 3. Notify (SMS / Pushover / Slack) ────────────────────────────────────────
# Uncomment to send a notification before every approved task.
# Replace with your preferred notification tool.
#
# SHORT_PLAN="${PLAN:0:200}"
# curl -s -X POST "https://api.pushover.net/1/messages.json" \
#   -d "token=${PUSHOVER_APP_TOKEN}" \
#   -d "user=${PUSHOVER_USER_KEY}" \
#   -d "title=Bridge task starting" \
#   -d "message=$SHORT_PLAN" >/dev/null 2>&1 || true

# ── 4. Interactive terminal approval ─────────────────────────────────────────
# Uncomment to require a human keystroke in the terminal where the daemon runs.
# NOTE: only works if the daemon is running interactively (foreground), not as
# a launchd/systemd service (where there's no tty to read from).
#
# echo "=== BRIDGE PLAN APPROVAL ===" >&2
# echo "$PLAN" >&2
# echo "" >&2
# read -r -t 60 -p "Approve this task? [y/N] " REPLY </dev/tty || { echo "No tty / timed out — rejected" >&2; exit 2; }
# case "$REPLY" in
#   [Yy]*) echo "Approved." ;;
#   *)     echo "Rejected by user." >&2; exit 2 ;;
# esac

# ── Default: approve everything ───────────────────────────────────────────────
exit 0
