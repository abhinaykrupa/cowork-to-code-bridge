#!/usr/bin/env bash
# run_claude.sh — the heart of the bridge: hand a task to Claude Code on the Mac.
#
# Cowork sends a free-form task; this invokes the local `claude` CLI headless so
# a real Claude Code agent does the work on your Mac. Result flows back through
# the bridge.
#
# Usage from Cowork:
#   call_remote("scripts/run_claude.sh",
#       args=["Build a Flask app with one /health route", "/path/to/project"],
#       timeout=600, idempotency_key="...")
#
# Args:
#   $1  the task / prompt for Claude Code (required)
#   $2  working directory to run Claude Code in (optional; default: $PWD)
#
# CLI RESOLUTION (handles "Desktop app but no CLI on PATH"):
#   1. `claude` on PATH
#   2. Common install locations (Homebrew, official installer, ~/.local/bin)
#   3. The Claude Desktop app's bundled claude-code binary
#   4. Auto-install the CLI on the fly (Homebrew cask, else official installer)
#      — gated by BRIDGE_CLAUDE_AUTOINSTALL (default: on). Set to 0 to disable
#        and get a clear "install it yourself" message instead.
#   5. If all fail: exit 127 with the exact command the user should run.
#
# Idempotency: Claude Code tasks have side effects (edits, commits, pushes).
# Always pass an idempotency_key so a retry returns the cached result instead of
# running the agent twice.
set -uo pipefail

TASK="${1:?run_claude.sh: a task/prompt is required as the first argument}"
WORKDIR="${2:-$PWD}"
AUTOINSTALL="${BRIDGE_CLAUDE_AUTOINSTALL:-1}"

log() { echo "run_claude.sh: $*" >&2; }

# ── 1+2+3: locate an existing claude binary ──────────────────────────────────
find_claude() {
  # PATH first
  local p; p="$(command -v claude 2>/dev/null || true)"
  if [[ -n "$p" && -x "$p" ]]; then echo "$p"; return 0; fi
  # Common standalone install locations
  local cand
  for cand in \
    /opt/homebrew/bin/claude \
    /usr/local/bin/claude \
    "$HOME/.local/bin/claude" \
    "$HOME/.claude/bin/claude"; do
    [[ -x "$cand" ]] && { echo "$cand"; return 0; }
  done
  # Claude Desktop app's bundled claude-code binary (newest version dir wins)
  local appdir="$HOME/Library/Application Support/Claude/claude-code"
  if [[ -d "$appdir" ]]; then
    local bundled
    bundled="$(find "$appdir" -maxdepth 4 -type f -name claude -perm -u+x 2>/dev/null | sort -V | tail -1)"
    [[ -n "$bundled" && -x "$bundled" ]] && { echo "$bundled"; return 0; }
  fi
  return 1
}

# ── 4: auto-install on the fly ───────────────────────────────────────────────
install_claude() {
  log "claude CLI not found — attempting on-the-fly install (set BRIDGE_CLAUDE_AUTOINSTALL=0 to disable)."
  # Prefer Homebrew if present (cleanest, matches how it's usually installed).
  if command -v brew >/dev/null 2>&1; then
    log "installing via: brew install claude-code"
    if brew install claude-code >&2 2>&1; then
      hash -r 2>/dev/null || true
      return 0
    fi
    log "brew install failed — trying official installer."
  fi
  # Fallback: official installer script.
  if command -v curl >/dev/null 2>&1; then
    log "installing via official installer (curl)"
    if curl -fsSL https://claude.ai/install.sh | bash >&2 2>&1; then
      hash -r 2>/dev/null || true
      # Official installer typically drops it in ~/.local/bin
      export PATH="$HOME/.local/bin:$PATH"
      return 0
    fi
  fi
  return 1
}

CLAUDE_BIN="$(find_claude || true)"

if [[ -z "${CLAUDE_BIN:-}" ]]; then
  if [[ "$AUTOINSTALL" == "1" ]] && install_claude; then
    CLAUDE_BIN="$(find_claude || true)"
  fi
fi

if [[ -z "${CLAUDE_BIN:-}" ]]; then
  cat >&2 <<MSG
run_claude.sh: the Claude Code CLI is not installed on this Mac, and it could
not be installed automatically.

Install it once with ONE of these, then retry:
  brew install claude-code
  # or:
  curl -fsSL https://claude.ai/install.sh | bash

(Having the Claude Desktop app is NOT enough — it bundles its own copy but does
not expose a 'claude' command. The CLI is a separate, one-time install.)
MSG
  exit 127
fi

log "using claude at: $CLAUDE_BIN"
cd "$WORKDIR" || { log "cannot cd to $WORKDIR"; exit 1; }

# CLAUDE_FLAGS (env): set the trust/permission scope for Cowork-originated tasks.
# If you export CLAUDE_FLAGS in the environment (e.g. in the launchd/systemd unit
# or your shell profile), those flags are passed to Claude Code. Examples:
#   CLAUDE_FLAGS="--permission-mode plan"                  # plan-only, no edits/exec
#   CLAUDE_FLAGS="--allowedTools Edit,Write,Read,Glob,Grep" # edits only, no shell
# Unset/empty = the default (full agent). The task prompt + output format are
# always appended and can't be overridden.
read -r -a EXTRA_FLAGS <<< "${CLAUDE_FLAGS:-}"

exec "$CLAUDE_BIN" "${EXTRA_FLAGS[@]}" -p "$TASK" --output-format text
