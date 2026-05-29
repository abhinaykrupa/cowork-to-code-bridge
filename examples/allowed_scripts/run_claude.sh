#!/usr/bin/env bash
# run_claude.sh — the heart of the bridge: hand a task to Claude Code on the Mac.
#
# This is what makes the bridge a Cowork → Claude Code connector (not just a
# script runner). Cowork sends a free-form task; this invokes the local
# `claude` CLI headless so a real Claude Code agent does the work on your Mac,
# in your repos, with your tools. The result flows back through the bridge.
#
# Usage from Cowork:
#   call_remote(
#       "scripts/run_claude.sh",
#       args=["Run the test suite and tell me what fails", "/path/to/repo"],
#       timeout=600,
#       idempotency_key="...",   # strongly recommended — see note below
#   )
#
# Args:
#   $1  the task / prompt for Claude Code (required)
#   $2  working directory to run Claude Code in (optional; default: $PWD)
#
# Idempotency: Claude Code tasks can have side effects (edits, commits, pushes).
# Always pass an idempotency_key from Cowork so a retry after a TimeoutError
# returns the cached result instead of running the agent twice. The bridge
# daemon enforces this — see docs/architecture.md.
#
# Permissions: by default this runs Claude Code with its normal local
# permissions. To restrict what a Cowork-originated task can do unattended,
# edit the CLAUDE_FLAGS below (e.g. add a tool allowlist or a plan-only mode).
set -euo pipefail

TASK="${1:?run_claude.sh: a task/prompt is required as the first argument}"
WORKDIR="${2:-$PWD}"

# Locate the claude CLI (PATH first, then common Homebrew/desktop locations).
CLAUDE_BIN="$(command -v claude 2>/dev/null || true)"
if [[ -z "$CLAUDE_BIN" ]]; then
  for cand in /opt/homebrew/bin/claude /usr/local/bin/claude; do
    [[ -x "$cand" ]] && { CLAUDE_BIN="$cand"; break; }
  done
fi
if [[ -z "$CLAUDE_BIN" ]]; then
  echo "run_claude.sh: 'claude' CLI not found on this Mac." >&2
  echo "Install Claude Code, or ensure 'claude' is on PATH." >&2
  exit 127
fi

cd "$WORKDIR"

# CLAUDE_FLAGS: tune this to set the trust/permission scope for tasks that
# arrive from Cowork. Conservative default = print mode, text output.
# To sandbox harder, e.g.:  --permission-mode plan   or   --allowedTools "Read,Bash(git status)"
CLAUDE_FLAGS=(-p "$TASK" --output-format text)

exec "$CLAUDE_BIN" "${CLAUDE_FLAGS[@]}"
