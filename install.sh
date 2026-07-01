#!/usr/bin/env bash
# install.sh — one-shot installer for cowork-to-code-bridge (macOS, Linux, WSL2).
#
# Usage (macOS Terminal, Linux shell, or WSL Ubuntu — not PowerShell/Git Bash):
#   curl -fsSL https://raw.githubusercontent.com/abhinaykrupa/cowork-to-code-bridge/main/install.sh | bash
#
# What this does:
#   1. Locates a usable Python 3.10+ interpreter (probes python3.14 → 3.10, then python3).
#   2. pip-installs the cowork-to-code-bridge package (PyPI, fallback GitHub main).
#   3. Creates ~/.cowork-to-code-bridge/ with queue/, results/, processed/, scripts/.
#   4. Generates BRIDGE_TOKEN and writes it to ~/.cowork-to-code-bridge/.env.
#   5. Installs ping.sh + hello.sh + system-info starter scripts.
#   6. Installs a launchd plist with absolute Python interpreter path so the
#      daemon auto-starts on login and survives reboots.
#   7. Bootstraps the daemon via `launchctl bootstrap` (fallback `load -w`).
#   8. Verifies daemon-up heartbeat (20s window).
#   9. Detects whether the user's PATH includes the per-user pip scripts dir
#      and offers to append it to ~/.zshrc.
#  10. Prints the Cowork paste snippet.
#
# Re-runnable: skips already-completed steps. Regenerates BRIDGE_TOKEN if the
# existing value is empty.

set -euo pipefail
trap 'echo "✗ Install failed at line $LINENO. Run cowork-to-code-bridge-uninstall (or: curl -fsSL https://raw.githubusercontent.com/abhinaykrupa/cowork-to-code-bridge/main/daemon/uninstall.sh | bash) to clean up partial state." >&2' ERR

REPO="abhinaykrupa/cowork-to-code-bridge"
BRIDGE_ROOT="$HOME/.cowork-to-code-bridge"
PLIST="$HOME/Library/LaunchAgents/dev.cowork-to-code-bridge.daemon.plist"
PACKAGE="cowork-to-code-bridge"
PACKAGE_SPEC="cowork-to-code-bridge>=0.5.1"
DAEMON_LOG="$BRIDGE_ROOT/daemon.log"
DAEMON_ERR="$BRIDGE_ROOT/daemon.err"

c_green()  { printf "\033[0;32m%s\033[0m\n" "$1"; }
c_yellow() { printf "\033[0;33m%s\033[0m\n" "$1"; }
c_red()    { printf "\033[0;31m%s\033[0m\n" "$1"; }
step()     { printf "\n\033[1;36m==> %s\033[0m\n" "$1"; }

# ─── 0. Preflight: detect OS / service manager ───────────────────────────────
# macOS uses launchd; Linux uses systemd --user when available, else manual
# (setsid/nohup + optional @reboot cron). WSL2 uses systemd when enabled.
NO_SYSTEMD_DOC="https://github.com/abhinaykrupa/cowork-to-code-bridge/blob/main/docs/LINUX-NO-SYSTEMD.md"
WSL_DOC="https://github.com/abhinaykrupa/cowork-to-code-bridge/blob/main/docs/WSL.md"
_INSTALL_DIR="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" 2>/dev/null && pwd)" || true
if [[ -n "$_INSTALL_DIR" && -f "$_INSTALL_DIR/scripts/lib/platform.sh" ]]; then
  # shellcheck source=scripts/lib/platform.sh
  source "$_INSTALL_DIR/scripts/lib/platform.sh"
fi
if [[ -n "$_INSTALL_DIR" && -f "$_INSTALL_DIR/scripts/lib/daemon_service.sh" ]]; then
  # shellcheck source=scripts/lib/daemon_service.sh
  source "$_INSTALL_DIR/scripts/lib/daemon_service.sh"
fi

# Inline fallbacks when install.sh is piped (curl | bash) and lib/ is unavailable.
if ! declare -F linux_service_mgr >/dev/null 2>&1; then
  is_wsl() {
    [[ -n "${WSL_DISTRO_NAME:-}" ]] || grep -qiE 'microsoft|wsl' /proc/version 2>/dev/null
  }
  has_systemctl() { command -v systemctl >/dev/null 2>&1; }
  has_systemd_user_bus() {
    has_systemctl && systemctl --user ping >/dev/null 2>&1
  }
  linux_service_mgr() {
    local forced="${BRIDGE_FORCE_SERVICE_MGR:-}"
    if [[ -n "$forced" ]]; then echo "$forced"; return 0; fi
    if has_systemd_user_bus; then echo "systemd"; return 0; fi
    if is_wsl; then echo "wsl_need_systemd"; return 0; fi
    echo "manual"
  }
fi

OS="$(uname -s)"
IS_WSL=0
if declare -F is_wsl >/dev/null 2>&1 && is_wsl; then IS_WSL=1; fi
PLATFORM_NOTE=""

case "$OS" in
  Darwin)
    SERVICE_MGR="launchd"
    PLATFORM_NOTE="macOS (launchd)"
    ;;
  Linux)
    _linux_mgr="$(linux_service_mgr)"
    case "$_linux_mgr" in
      systemd)
        SERVICE_MGR="systemd"
        if [[ "$IS_WSL" -eq 1 ]]; then
          PLATFORM_NOTE="Linux (WSL2, systemd --user)"
        else
          PLATFORM_NOTE="Linux (systemd --user)"
        fi
        ;;
      manual)
        SERVICE_MGR="manual"
        PLATFORM_NOTE="Linux (manual daemon, no systemd)"
        ;;
      wsl_need_systemd)
        c_red "✗ WSL2 without systemd is not supported."
        echo "  Enable systemd in WSL, then re-run this installer:"
        echo
        echo "    1. In WSL: sudo tee /etc/wsl.conf >/dev/null <<'EOF'"
        echo "       [boot]"
        echo "       systemd=true"
        echo "       EOF"
        echo "    2. In Windows PowerShell: wsl --shutdown"
        echo "    3. Re-open your Ubuntu/WSL app and run this installer again."
        echo
        echo "  Full guide: $WSL_DOC"
        exit 1
        ;;
      *)
        c_red "✗ Unsupported Linux service manager: $_linux_mgr"
        exit 1
        ;;
    esac
    ;;
  MINGW*|MSYS*|CYGWIN*)
    c_red "✗ Native Windows shell is not supported."
    echo "  Run this installer inside WSL2 (Ubuntu), not PowerShell, cmd, or Git Bash."
    echo "  Open the Ubuntu app (or: wsl), then paste the install command there."
    echo
    echo "  Guide: $WSL_DOC"
    exit 1
    ;;
  *)
    c_red "✗ Unsupported OS: $OS"
    echo "  Supported: macOS (launchd), Linux (systemd or manual), and WSL2 with systemd."
    echo "  Native Windows is not supported — use WSL2. Guide: $WSL_DOC"
    exit 1
    ;;
esac
c_green "  ✓ OS: $PLATFORM_NOTE"

# ─── 1. Preflight: locate a Python 3.10+ interpreter ─────────────────────────
step "Locating Python 3.10+ interpreter"

PY=""
PY_VER=""
for candidate in python3.14 python3.13 python3.12 python3.11 python3.10 python3; do
  if command -v "$candidate" >/dev/null 2>&1; then
    cand_path="$(command -v "$candidate")"
    # Resolve to absolute, dereferenced path so launchd doesn't depend on PATH.
    if command -v readlink >/dev/null 2>&1; then
      resolved="$(readlink -f "$cand_path" 2>/dev/null || echo "$cand_path")"
    else
      resolved="$cand_path"
    fi
    ver=$("$resolved" -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")' 2>/dev/null || echo "")
    if [[ -z "$ver" ]]; then continue; fi
    major=$(echo "$ver" | cut -d. -f1)
    minor=$(echo "$ver" | cut -d. -f2)
    if [[ "$major" -eq 3 ]] && [[ "$minor" -ge 10 ]]; then
      PY="$resolved"
      PY_VER="$ver"
      break
    fi
  fi
done

# Re-scan helper: look again for a usable python3.10+ after an install attempt.
rescan_python() {
  PY=""; PY_VER=""
  local candidate cand_path resolved ver major minor
  for candidate in python3.14 python3.13 python3.12 python3.11 python3.10 python3; do
    command -v "$candidate" >/dev/null 2>&1 || continue
    cand_path="$(command -v "$candidate")"
    if command -v readlink >/dev/null 2>&1; then
      resolved="$(readlink -f "$cand_path" 2>/dev/null || echo "$cand_path")"
    else
      resolved="$cand_path"
    fi
    ver=$("$resolved" -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")' 2>/dev/null || echo "")
    [[ -z "$ver" ]] && continue
    major=$(echo "$ver" | cut -d. -f1); minor=$(echo "$ver" | cut -d. -f2)
    if [[ "$major" -eq 3 ]] && [[ "$minor" -ge 10 ]]; then
      PY="$resolved"; PY_VER="$ver"; return 0
    fi
  done
  return 1
}

# Auto-install Python 3.12 on the fly: ensure Homebrew, then brew install.
# Gated by BRIDGE_PYTHON_AUTOINSTALL (default 1; set 0 to get instructions).
AUTO_PY="${BRIDGE_PYTHON_AUTOINSTALL:-1}"
autoinstall_python() {
  c_yellow "  No Python 3.10+ found — attempting on-the-fly install."
  c_yellow "  (Set BRIDGE_PYTHON_AUTOINSTALL=0 to skip this and get manual steps.)"

  # 1. Ensure Homebrew exists (it ships its own Python as a dep).
  local BREW=""
  for b in brew /opt/homebrew/bin/brew /usr/local/bin/brew; do
    command -v "$b" >/dev/null 2>&1 && { BREW="$(command -v "$b")"; break; }
    [[ -x "$b" ]] && { BREW="$b"; break; }
  done

  if [[ -z "$BREW" ]]; then
    c_yellow "  Homebrew not found. Installing Homebrew first (this can take a few"
    c_yellow "  minutes and may ask for your Mac password — that's expected)."
    # Official Homebrew installer. NONINTERACTIVE avoids the 'press RETURN' prompt;
    # it may still prompt for sudo password, which we cannot bypass safely.
    if ! command -v curl >/dev/null 2>&1; then
      c_red "  ✗ curl not available — cannot install Homebrew automatically."
      return 1
    fi
    NONINTERACTIVE=1 /bin/bash -c \
      "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)" \
      </dev/null || { c_red "  ✗ Homebrew install failed."; return 1; }
    # Put brew on PATH for the rest of this script (Apple Silicon vs Intel).
    for b in /opt/homebrew/bin/brew /usr/local/bin/brew; do
      [[ -x "$b" ]] && { BREW="$b"; eval "$("$b" shellenv)"; break; }
    done
    [[ -z "$BREW" ]] && { c_red "  ✗ Homebrew installed but 'brew' not found on PATH."; return 1; }
    c_green "  ✓ Homebrew ready ($BREW)"
  fi

  # 2. brew install python@3.12
  c_yellow "  Installing python@3.12 via Homebrew…"
  "$BREW" install python@3.12 >&2 2>&1 || { c_red "  ✗ brew install python@3.12 failed."; return 1; }
  # Make sure the brew bin dir is on PATH so python3.12 resolves on rescan.
  eval "$("$BREW" shellenv)" 2>/dev/null || true
  hash -r 2>/dev/null || true
  return 0
}

if [[ -z "$PY" ]]; then
  installed_ok=0
  if [[ "$AUTO_PY" == "1" ]] && [[ "$OS" == "Darwin" ]] && autoinstall_python && rescan_python; then
    installed_ok=1
  fi
  if [[ "$installed_ok" -ne 1 ]]; then
    c_red "  ✗ No Python 3.10+ interpreter available."
    echo
    if [[ "$OS" == "Darwin" ]]; then
      echo "  Apple's stock /usr/bin/python3 is too old (3.8) and is intentionally"
      echo "  ignored here. Install a modern Python, then re-run this installer:"
      echo
      echo "    # if you have Homebrew:"
      echo "    brew install python@3.12"
      echo
      echo "    # if you don't have Homebrew, install it first (one paste):"
      echo '    /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"'
      echo "    # then: brew install python@3.12"
    else
      echo "  Install Python 3.10+, then re-run this installer:"
      echo
      if [[ -f /etc/os-release ]] && grep -qiE 'ubuntu|debian' /etc/os-release 2>/dev/null; then
        echo "    # Ubuntu / Debian (typical WSL):"
        echo "    sudo apt update && sudo apt install -y python3.12 python3.12-venv"
        echo "    # or, if your distro ships 3.10+ as python3:"
        echo "    sudo apt install -y python3 python3-venv"
      else
        echo "    # use your distro package manager, or:"
        echo "    https://www.python.org/downloads/"
      fi
      if [[ "$IS_WSL" -eq 1 ]]; then
        echo
        echo "  WSL setup guide: $WSL_DOC"
      fi
    fi
    echo
    echo "  After install, verify: command -v python3.12 || command -v python3"
    exit 1
  fi
fi
export PY
c_green "  ✓ using $PY (Python $PY_VER)"

# pip sanity
if ! "$PY" -m pip --version >/dev/null 2>&1; then
  c_yellow "  ! pip missing for $PY — bootstrapping with ensurepip"
  "$PY" -m ensurepip --upgrade || {
    c_red "  ✗ ensurepip failed. Install pip manually for $PY and re-run."
    exit 1
  }
fi
c_green "  ✓ pip available for $PY"

# ─── 2. Install package (handle PEP 668 externally-managed) ──────────────────
step "Installing $PACKAGE"

# pip_install_user <args...> — try --user, retry with --break-system-packages
# if PEP 668 blocks. Returns non-zero only if both attempts fail.
pip_install_user() {
  local out rc
  out=$("$PY" -m pip install --user --upgrade "$@" 2>&1) && rc=0 || rc=$?
  if [[ $rc -eq 0 ]]; then
    return 0
  fi
  # PEP 668 marker: "externally-managed-environment"
  if echo "$out" | grep -qi "externally-managed-environment"; then
    c_yellow "  ! PEP 668: this Python is marked externally-managed."
    c_yellow "    Retrying with --break-system-packages (per-user install, won't touch system site-packages)."
    "$PY" -m pip install --user --break-system-packages --upgrade "$@"
    return $?
  fi
  # Some other failure — surface the original output and bubble up.
  echo "$out" >&2
  return $rc
}

if pip_install_user "$PACKAGE_SPEC" 2>/dev/null; then
  c_green "  ✓ installed from PyPI"
else
  c_yellow "  PyPI install failed (package may not be published yet) — falling back to GitHub"
  pip_install_user "git+https://github.com/$REPO.git@main"
  c_green "  ✓ installed from GitHub main"
fi

# Resolve where pip put the console scripts (per-user "scripts" path).
# Example on Mac: ~/Library/Python/3.12/bin
# Python 3.10+ exposes `get_preferred_scheme('user')`; we fall back to manual
# probes for older interpreters or oddly-configured frameworks (where
# get_default_scheme returns e.g. 'osx_framework_library' which has no _user variant).
USER_SCRIPTS_DIR=$("$PY" - <<'PYEOF'
import sysconfig, sys, os
# Preferred: 3.10+ API
try:
    scheme = sysconfig.get_preferred_scheme('user')
    print(sysconfig.get_path('scripts', scheme))
    sys.exit(0)
except Exception:
    pass
# Fallback 1: '<default>_user' (works when the default scheme has a _user variant)
try:
    scheme = f"{sysconfig.get_default_scheme()}_user"
    if scheme in sysconfig.get_scheme_names():
        print(sysconfig.get_path('scripts', scheme))
        sys.exit(0)
except Exception:
    pass
# Fallback 2: pick any *_user scheme that exists
for s in sysconfig.get_scheme_names():
    if s.endswith('_user'):
        print(sysconfig.get_path('scripts', s))
        sys.exit(0)
# Last resort: derive from site.USER_BASE
import site
print(os.path.join(site.getuserbase(), 'bin'))
PYEOF
)
if [[ -z "$USER_SCRIPTS_DIR" ]]; then
  c_red "  ✗ could not resolve user scripts dir from $PY"
  exit 1
fi
c_green "  ✓ user scripts dir: $USER_SCRIPTS_DIR"

# ─── 3. Bridge directory layout ──────────────────────────────────────────────
step "Setting up $BRIDGE_ROOT"
mkdir -p "$BRIDGE_ROOT"/{queue,results,processed,scripts}
c_green "  ✓ directories created"

# ─── 4. Token ────────────────────────────────────────────────────────────────
step "Generating bridge token"
ENV_FILE="$BRIDGE_ROOT/.env"

existing_token=""
if [[ -f "$ENV_FILE" ]] && grep -q "^BRIDGE_TOKEN=" "$ENV_FILE"; then
  existing_token=$(grep "^BRIDGE_TOKEN=" "$ENV_FILE" | head -1 | cut -d= -f2- | tr -d '"' | tr -d "'" | tr -d '[:space:]')
fi

if [[ -n "$existing_token" ]]; then
  BRIDGE_TOKEN="$existing_token"
  c_yellow "  → BRIDGE_TOKEN already set in $ENV_FILE — keeping existing token"
else
  if [[ -f "$ENV_FILE" ]] && grep -q "^BRIDGE_TOKEN=" "$ENV_FILE"; then
    c_yellow "  → existing BRIDGE_TOKEN line is empty — regenerating"
    # Strip the empty line; we'll append a fresh one.
    tmp="$(mktemp)"
    grep -v "^BRIDGE_TOKEN=" "$ENV_FILE" > "$tmp" || true
    mv "$tmp" "$ENV_FILE"
  fi
  BRIDGE_TOKEN=$(openssl rand -hex 16)
  {
    echo "BRIDGE_TOKEN=$BRIDGE_TOKEN"
    # Only add BRIDGE_ROOT if not already present.
    if ! [[ -f "$ENV_FILE" ]] || ! grep -q "^BRIDGE_ROOT=" "$ENV_FILE"; then
      echo "BRIDGE_ROOT=$BRIDGE_ROOT"
    fi
  } >> "$ENV_FILE"
  chmod 600 "$ENV_FILE"
  c_green "  ✓ token generated and saved (chmod 600)"
fi

# ─── 5. Starter scripts ──────────────────────────────────────────────────────
step "Installing starter scripts"
cat > "$BRIDGE_ROOT/scripts/ping.sh" <<'PING'
#!/usr/bin/env bash
# ping.sh — minimal health check. Used by daemon_alive() from the client.
echo "OK"
echo "pwd: $(pwd)"
echo "ts: $(date -u +%Y-%m-%dT%H:%M:%SZ)"
PING
chmod +x "$BRIDGE_ROOT/scripts/ping.sh"

cat > "$BRIDGE_ROOT/scripts/hello.sh" <<'HELLO'
#!/usr/bin/env bash
# hello.sh — sample script you can call via the bridge.
echo "hello from $(hostname) — args: $*"
HELLO
chmod +x "$BRIDGE_ROOT/scripts/hello.sh"

# run_claude.sh — THE bridge's purpose: hand a task to Claude Code on the Mac.
cat > "$BRIDGE_ROOT/scripts/run_claude.sh" <<'RUNCLAUDE'
#!/usr/bin/env bash
# run_claude.sh — hand a task to Claude Code (the `claude` CLI) on this Mac.
# This is what makes the bridge a Cowork -> Claude Code connector.
# Args: $1 = task/prompt (required), $2 = working dir (optional, default $PWD).
# Always pass an idempotency_key from Cowork — Claude Code tasks have side effects.
#
# CLI resolution: PATH -> common install dirs -> Desktop app bundle ->
# auto-install (brew, else official installer) -> clear failure. Auto-install
# is gated by BRIDGE_CLAUDE_AUTOINSTALL (default 1; set 0 to disable).
set -uo pipefail
TASK="${1:?run_claude.sh: a task/prompt is required as the first argument}"
WORKDIR="${2:-$PWD}"
AUTOINSTALL="${BRIDGE_CLAUDE_AUTOINSTALL:-1}"
log() { echo "run_claude.sh: $*" >&2; }

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

install_claude() {
  log "claude CLI not found — attempting on-the-fly install (BRIDGE_CLAUDE_AUTOINSTALL=0 to disable)."
  if command -v brew >/dev/null 2>&1; then
    log "installing via: brew install claude-code"
    brew install claude-code >&2 2>&1 && { hash -r 2>/dev/null||true; return 0; }
    log "brew install failed — trying official installer."
  fi
  if command -v curl >/dev/null 2>&1; then
    log "installing via official installer (curl)"
    curl -fsSL https://claude.ai/install.sh | bash >&2 2>&1 && {
      hash -r 2>/dev/null||true; export PATH="$HOME/.local/bin:$PATH"; return 0; }
  fi
  return 1
}

CLAUDE_BIN="$(find_claude || true)"
if [[ -z "${CLAUDE_BIN:-}" && "$AUTOINSTALL" == "1" ]] && install_claude; then
  CLAUDE_BIN="$(find_claude || true)"
fi
if [[ -z "${CLAUDE_BIN:-}" ]]; then
  cat >&2 <<MSG
run_claude.sh: the Claude Code CLI is not installed on this machine, and it
could not be installed automatically. Install it once, then retry:
  curl -fsSL https://claude.ai/install.sh | bash   # macOS or Linux
  # or, with Homebrew: brew install claude-code
(Having the Claude Desktop app is NOT enough — the CLI is a separate install.)
MSG
  exit 127
fi
log "using claude at: $CLAUDE_BIN"
cd "$WORKDIR" || { log "cannot cd to $WORKDIR"; exit 1; }
# CLAUDE_FLAGS (env): restrict Cowork-originated tasks. Examples:
#   CLAUDE_FLAGS="--permission-mode plan"                   # plan-only
#   CLAUDE_FLAGS="--allowedTools Edit,Write,Read,Glob,Grep" # edits only, no shell
# Unset = full agent. The prompt + output format are always appended.
read -r -a EXTRA_FLAGS <<< "${CLAUDE_FLAGS:-}"

# ── Budget cap ────────────────────────────────────────────────────────────────
# MAX_BUDGET_USD: per-task spend ceiling passed in by the client.
# BRIDGE_MAX_BUDGET_USD: owner-set global ceiling (env / launchd unit).
# Rule: the effective ceiling = min(caller_value, owner_ceiling).
# If the owner sets BRIDGE_MAX_BUDGET_USD=5.00 and Cowork sends 10.00,
# the task is capped at $5. If Cowork sends 1.00, it's capped at $1.
BUDGET_FLAGS=()
CALLER_BUDGET="${MAX_BUDGET_USD:-}"
OWNER_CEILING="${BRIDGE_MAX_BUDGET_USD:-}"

if [[ -n "$OWNER_CEILING" && -n "$CALLER_BUDGET" ]]; then
  # Both set — use the smaller of the two.
  # Use awk for float comparison (bash can't do it natively).
  EFFECTIVE=$(awk -v a="$CALLER_BUDGET" -v b="$OWNER_CEILING" \
    'BEGIN { print (a < b) ? a : b }')
  BUDGET_FLAGS=(--max-budget-usd "$EFFECTIVE")
elif [[ -n "$CALLER_BUDGET" ]]; then
  BUDGET_FLAGS=(--max-budget-usd "$CALLER_BUDGET")
elif [[ -n "$OWNER_CEILING" ]]; then
  BUDGET_FLAGS=(--max-budget-usd "$OWNER_CEILING")
fi

# ── Model tier → --model ────────────────────────────────────────────────────
# CLAUDE_MODEL_TIER: routing tier injected by the daemon (haiku|sonnet|opus|fable).
# Map it to the concrete model ID the claude CLI expects. Keep in sync with
# cowork_to_code_bridge/model_router.py's TIER_TO_MODEL_ID (the canonical source).
# An unset/unknown tier means: don't pass --model, let the CLI pick its default.
MODEL_FLAGS=()
tier_to_model_id() {
  case "$1" in
    haiku)  echo "claude-haiku-4-5-20251001" ;;
    sonnet) echo "claude-sonnet-4-6" ;;
    opus)   echo "claude-opus-4-8" ;;
    fable)  echo "claude-fable-5" ;;
    *)      echo "" ;;
  esac
}
if [[ -n "${CLAUDE_MODEL_TIER:-}" ]]; then
  MODEL_ID="$(tier_to_model_id "$(echo "$CLAUDE_MODEL_TIER" | tr '[:upper:]' '[:lower:]')")"
  if [[ -n "$MODEL_ID" ]]; then
    log "model tier '$CLAUDE_MODEL_TIER' → --model $MODEL_ID"
    MODEL_FLAGS=(--model "$MODEL_ID")
  else
    log "unknown CLAUDE_MODEL_TIER='$CLAUDE_MODEL_TIER' — using CLI default model"
  fi
fi

exec "$CLAUDE_BIN" "${EXTRA_FLAGS[@]}" "${MODEL_FLAGS[@]}" "${BUDGET_FLAGS[@]}" -p "$TASK" --output-format text
RUNCLAUDE
chmod +x "$BRIDGE_ROOT/scripts/run_claude.sh"

# ─── System-info scripts: let Cowork check the Mac directly ──────────────────
# These answer "check my Mac's health / RAM / disk / processes / network" with
# real data, fast, without invoking the agent. This is the thing Cowork can't
# do on its own — the bridge makes it possible.
cat > "$BRIDGE_ROOT/scripts/mac_health.sh" <<'MH'
#!/usr/bin/env bash
# mac_health.sh — full health snapshot of this machine (macOS or Linux).
#
# Usage: mac_health.sh [--json]
#   (no flag)   human-readable text sections (default)
#   --json      structured JSON — parse with json.loads() in Cowork
#
# JSON fields: host, os, uptime, load_1m/5m/15m, cpu_usage_pct,
#   memory_total_bytes, memory_free_bytes, memory_used_bytes, memory_used_pct,
#   disk_total_1k, disk_used_1k, disk_avail_1k, disk_used_pct,
#   top_procs [{pid, cpu_pct, mem_pct, name}]
#
# No external dependencies (no jq, no python).
set -u

JSON=0
for arg in "$@"; do [ "$arg" = "--json" ] && JSON=1; done

OS="$(uname -s)"

# Escape a string for safe embedding in JSON (no jq required).
_jstr() { printf '%s' "$1" | sed 's/\\/\\\\/g; s/"/\\"/g; s/	/\\t/g' | tr -d '\r\n'; }

# ── collect ──────────────────────────────────────────────────────────────────
HOST="$(hostname 2>/dev/null)"
if [ "$OS" = "Darwin" ]; then
  OS_NAME="$(sw_vers -productName 2>/dev/null) $(sw_vers -productVersion 2>/dev/null)"
else
  OS_NAME="$(. /etc/os-release 2>/dev/null && echo "${PRETTY_NAME:-}" || uname -sr)"
fi

UPTIME_STR="$(uptime 2>/dev/null)"
LOAD_1="$(echo  "$UPTIME_STR" | grep -oE '[0-9]+\.[0-9]+' | sed -n '1p' || echo '')"
LOAD_5="$(echo  "$UPTIME_STR" | grep -oE '[0-9]+\.[0-9]+' | sed -n '2p' || echo '')"
LOAD_15="$(echo "$UPTIME_STR" | grep -oE '[0-9]+\.[0-9]+' | sed -n '3p' || echo '')"

CPU_USAGE=""
if [ "$OS" = "Darwin" ]; then
  CPU_USAGE="$(top -l 1 -n 0 2>/dev/null | grep -oE '[0-9]+\.[0-9]+% user' | grep -oE '^[0-9.]+' || echo '')"
fi

MEM_TOTAL_BYTES=0; MEM_FREE_BYTES=0; MEM_USED_BYTES=0; MEM_USED_PCT=0
if [ "$OS" = "Darwin" ]; then
  MEM_TOTAL_BYTES="$(sysctl -n hw.memsize 2>/dev/null || echo 0)"
  PAGE_SIZE="$(sysctl -n hw.pagesize 2>/dev/null || echo 4096)"
  PAGES_FREE="$(vm_stat 2>/dev/null | awk '/^Pages free/{gsub(/\./,"",$3); print $3}' || echo 0)"
  MEM_FREE_BYTES=$(( PAGES_FREE * PAGE_SIZE ))
  MEM_USED_BYTES=$(( MEM_TOTAL_BYTES - MEM_FREE_BYTES ))
  [ "$MEM_TOTAL_BYTES" -gt 0 ] && MEM_USED_PCT=$(( MEM_USED_BYTES * 100 / MEM_TOTAL_BYTES ))
elif command -v free >/dev/null 2>&1; then
  eval "$(free | awk '/^Mem:/{printf "MEM_TOTAL_BYTES=%d MEM_USED_BYTES=%d MEM_FREE_BYTES=%d", $2*1024, $3*1024, $4*1024}')"
  [ "$MEM_TOTAL_BYTES" -gt 0 ] && MEM_USED_PCT=$(( MEM_USED_BYTES * 100 / MEM_TOTAL_BYTES ))
fi

DISK_LINE="$(df -k / 2>/dev/null | awk 'NR==2{print}')"
DISK_TOTAL="$(echo "$DISK_LINE" | awk '{print $2}')"
DISK_USED="$(echo  "$DISK_LINE" | awk '{print $3}')"
DISK_AVAIL="$(echo "$DISK_LINE" | awk '{print $4}')"
DISK_PCT="$(echo   "$DISK_LINE" | awk '{gsub(/%/,"",$5); print $5}')"

TOP_PROCS_RAW="$(ps -eo pid,pcpu,pmem,comm 2>/dev/null | sort -k2 -rn | awk 'NR>1&&NR<=6{print}')"

# ── output ───────────────────────────────────────────────────────────────────
if [ "$JSON" -eq 1 ]; then
  PROCS_JSON="["; first=1
  while IFS= read -r line; do
    [ -z "$line" ] && continue
    [ "$first" -eq 0 ] && PROCS_JSON="$PROCS_JSON,"
    PROCS_JSON="$PROCS_JSON{\"pid\":$(echo "$line"|awk '{print $1}'),\"cpu_pct\":$(echo "$line"|awk '{print $2}'),\"mem_pct\":$(echo "$line"|awk '{print $3}'),\"name\":\"$(_jstr "$(echo "$line"|awk '{print $4}')")\"}"
    first=0
  done <<< "$TOP_PROCS_RAW"
  PROCS_JSON="$PROCS_JSON]"
  cat <<EOF
{
  "host": "$(_jstr "$HOST")",
  "os": "$(_jstr "$OS_NAME")",
  "uptime": "$(_jstr "$UPTIME_STR")",
  "load_1m": "$LOAD_1", "load_5m": "$LOAD_5", "load_15m": "$LOAD_15",
  "cpu_usage_pct": "$CPU_USAGE",
  "memory_total_bytes": $MEM_TOTAL_BYTES,
  "memory_free_bytes": $MEM_FREE_BYTES,
  "memory_used_bytes": $MEM_USED_BYTES,
  "memory_used_pct": $MEM_USED_PCT,
  "disk_total_1k": ${DISK_TOTAL:-0},
  "disk_used_1k": ${DISK_USED:-0},
  "disk_avail_1k": ${DISK_AVAIL:-0},
  "disk_used_pct": ${DISK_PCT:-0},
  "top_procs": $PROCS_JSON
}
EOF
else
  echo "=== HOST ==="; echo "$HOST"
  if [ "$OS" = "Darwin" ]; then sw_vers 2>/dev/null
  else (. /etc/os-release 2>/dev/null; echo "${PRETTY_NAME:-$(uname -sr)}"); fi
  echo "=== UPTIME / LOAD ==="; echo "$UPTIME_STR"
  echo "=== CPU ==="
  if [ "$OS" = "Darwin" ]; then top -l 1 -n 0 2>/dev/null | grep -E "CPU usage" || echo n/a
  else grep 'cpu ' /proc/stat >/dev/null 2>&1 && echo "load: $(cut -d' ' -f1-3 /proc/loadavg)" || echo n/a; fi
  echo "=== MEMORY ==="
  if [ "$OS" = "Darwin" ]; then vm_stat 2>/dev/null | head -6
  else free -h 2>/dev/null || head -3 /proc/meminfo; fi
  echo "=== DISK ==="; df -h / 2>/dev/null
  echo "=== TOP 5 PROCS BY CPU ==="; ps -eo pid,pcpu,pmem,comm 2>/dev/null | sort -k2 -rn | head -6
fi
exit 0
MH
cat > "$BRIDGE_ROOT/scripts/mac_ram.sh" <<'MR'
#!/usr/bin/env bash
# mac_ram.sh — RAM usage summary (macOS or Linux).
#
# Usage: mac_ram.sh [--json]
#   (no flag)   human-readable text (default)
#   --json      structured JSON — parse with json.loads() in Cowork
#
# JSON fields: total_bytes, free_bytes, used_bytes, used_pct
# No external dependencies (no jq, no python).
set -u

JSON=0
for arg in "$@"; do [ "$arg" = "--json" ] && JSON=1; done

OS="$(uname -s)"

TOTAL_BYTES=0; FREE_BYTES=0; USED_BYTES=0; USED_PCT=0
if [ "$OS" = "Darwin" ]; then
  TOTAL_BYTES="$(sysctl -n hw.memsize 2>/dev/null || echo 0)"
  PAGE_SIZE="$(sysctl -n hw.pagesize 2>/dev/null || echo 4096)"
  PAGES_FREE="$(vm_stat 2>/dev/null | awk '/^Pages free/{gsub(/\./,"",$3); print $3}' || echo 0)"
  FREE_BYTES=$(( PAGES_FREE * PAGE_SIZE ))
  USED_BYTES=$(( TOTAL_BYTES - FREE_BYTES ))
  [ "$TOTAL_BYTES" -gt 0 ] && USED_PCT=$(( USED_BYTES * 100 / TOTAL_BYTES ))
elif command -v free >/dev/null 2>&1; then
  eval "$(free | awk '/^Mem:/{printf "TOTAL_BYTES=%d USED_BYTES=%d FREE_BYTES=%d", $2*1024, $3*1024, $4*1024}')"
  [ "$TOTAL_BYTES" -gt 0 ] && USED_PCT=$(( USED_BYTES * 100 / TOTAL_BYTES ))
fi

if [ "$JSON" -eq 1 ]; then
  cat <<EOF
{
  "total_bytes": ${TOTAL_BYTES:-0},
  "free_bytes": ${FREE_BYTES:-0},
  "used_bytes": ${USED_BYTES:-0},
  "used_pct": ${USED_PCT:-0}
}
EOF
else
  if [ "$OS" = "Darwin" ]; then
    echo "Total RAM: $(( TOTAL_BYTES / 1024 / 1024 / 1024 )) GB"
    echo "--- vm_stat ---"; vm_stat 2>/dev/null
  else
    free -h 2>/dev/null || cat /proc/meminfo 2>/dev/null | head -5
  fi
fi
exit 0
MR
cat > "$BRIDGE_ROOT/scripts/mac_disk.sh" <<'MD'
#!/usr/bin/env bash
# mac_disk.sh — disk usage (fast). Args: [path] [--json]   (path default /).
#   (no flag)   human-readable text (default)
#   --json      structured JSON for the queried path — parse with json.loads()
# JSON fields: path, total_1k, used_1k, avail_1k, used_pct
# No external dependencies (no jq, no python).
set -u
JSON=0; TARGET="/"
for arg in "$@"; do
  case "$arg" in
    --json) JSON=1 ;;
    *) TARGET="$arg" ;;
  esac
done
if [ "$JSON" -eq 1 ]; then
  # POSIX `df -P` gives stable 1K-block columns: Filesystem Blocks Used Avail Cap% Mount
  read -r TOTAL_1K USED_1K AVAIL_1K USED_PCT <<EOF
$(df -Pk "$TARGET" 2>/dev/null | awk 'NR==2{gsub(/%/,"",$5); print $2, $3, $4, $5}')
EOF
  cat <<EOF
{
  "path": "$TARGET",
  "total_1k": ${TOTAL_1K:-0},
  "used_1k": ${USED_1K:-0},
  "avail_1k": ${AVAIL_1K:-0},
  "used_pct": ${USED_PCT:-0}
}
EOF
else
  echo "=== DISK USAGE ==="; df -h "$TARGET" 2>/dev/null
  echo; echo "=== ALL MOUNTED VOLUMES ==="; df -h 2>/dev/null | grep -E "^/dev|Filesystem" | head -10
fi
exit 0
MD
cat > "$BRIDGE_ROOT/scripts/mac_top.sh" <<'MT'
#!/usr/bin/env bash
# mac_top.sh — top processes by CPU and memory (macOS or Linux).
# Args: [count] [--json]   (count default 15).
#   (no flag)   human-readable text (default)
#   --json      structured JSON — parse with json.loads()
# JSON fields: count, by_cpu[], by_mem[]   (each entry: pid, cpu_pct, mem_pct, name)
# No external dependencies (no jq, no python).
set -u
JSON=0; N=15
for arg in "$@"; do
  case "$arg" in
    --json) JSON=1 ;;
    *) [[ "$arg" =~ ^[0-9]+$ ]] && N="$arg" ;;
  esac
done
if [ "$JSON" -eq 1 ]; then
  # Emit a JSON array of the top-N rows, sorted by the given column ($1=cpu, $2=mem).
  emit_procs() {
    ps -eo pid,pcpu,pmem,comm 2>/dev/null | sort -k"$1" -rn | head -"$N" \
      | awk 'BEGIN{first=1; printf "["}
             {
               name=$4; for(i=5;i<=NF;i++) name=name" "$i;
               gsub(/\\/,"\\\\",name); gsub(/"/,"\\\"",name);
               if(!first) printf ",";
               printf "{\"pid\":%d,\"cpu_pct\":%s,\"mem_pct\":%s,\"name\":\"%s\"}", $1, $2, $3, name;
               first=0
             }
             END{printf "]"}'
  }
  printf '{\n  "count": %d,\n  "by_cpu": %s,\n  "by_mem": %s\n}\n' \
    "$N" "$(emit_procs 2)" "$(emit_procs 3)"
else
  echo "=== by CPU ==="; ps -eo pid,pcpu,pmem,comm 2>/dev/null | sort -k2 -rn | head -"$((N+1))"
  echo "=== by MEM ==="; ps -eo pid,pcpu,pmem,comm 2>/dev/null | sort -k3 -rn | head -"$((N+1))"
fi
exit 0
MT
cat > "$BRIDGE_ROOT/scripts/mac_network.sh" <<'MN'
#!/usr/bin/env bash
# mac_network.sh — network status (macOS or Linux). Args: [--json]
#   (no flag)   human-readable text (default)
#   --json      structured JSON — parse with json.loads()
# JSON fields: interfaces[] (each: name, addr), default_route, online (bool)
# No external dependencies (no jq, no python).
set -u
JSON=0
for arg in "$@"; do [ "$arg" = "--json" ] && JSON=1; done

get_interfaces() {
  # one "name addr" pair per line, loopback excluded. Prefer `ip` (Linux),
  # fall back to `ifconfig` (macOS / older Linux).
  if command -v ip >/dev/null 2>&1; then
    ip -brief addr 2>/dev/null | grep -v '127.0.0.1' | awk 'NF>=3{print $1, $3}'
  else
    ifconfig 2>/dev/null | awk '
        /^[a-z]/{iface=$1; sub(/:$/,"",iface)}
        /inet /{if($2!="127.0.0.1") print iface, $2}'
  fi
}
get_default_route() {
  if command -v ip >/dev/null 2>&1; then
    ip route show default 2>/dev/null | awk '{print $3; exit}'
  else
    route -n get default 2>/dev/null | awk '/gateway/{print $2; exit}'
  fi
}
is_online() {
  ping -c 2 -W 3 1.1.1.1 >/dev/null 2>&1 || ping -c 2 -t 3 1.1.1.1 >/dev/null 2>&1
}

if [ "$JSON" -eq 1 ]; then
  IFACES_JSON="$(get_interfaces | awk 'BEGIN{first=1; printf "["}
    NF>=1{
      name=$1; addr=$2;
      gsub(/"/,"\\\"",name); gsub(/"/,"\\\"",addr);
      if(!first) printf ",";
      printf "{\"name\":\"%s\",\"addr\":\"%s\"}", name, addr;
      first=0
    }
    END{printf "]"}')"
  ROUTE="$(get_default_route)"
  if is_online; then ONLINE=true; else ONLINE=false; fi
  cat <<EOF
{
  "interfaces": ${IFACES_JSON:-[]},
  "default_route": "${ROUTE:-}",
  "online": ${ONLINE}
}
EOF
else
  echo "=== interfaces (active) ==="
  ip -brief addr 2>/dev/null | grep -v '127.0.0.1' \
    || ifconfig 2>/dev/null | grep -E "^[a-z]|inet " | grep -v "127.0.0.1" | head -20
  echo "=== default route ==="
  ip route show default 2>/dev/null || route -n get default 2>/dev/null | grep -E "gateway|interface"
  echo "=== connectivity ==="
  if is_online; then
    echo "online (1.1.1.1 reachable)"
  else
    echo "no connectivity"
  fi
fi
exit 0
MN
cat > "$BRIDGE_ROOT/scripts/port_check.sh" <<'PC'
#!/usr/bin/env bash
# port_check.sh — show what is listening on a TCP port (macOS or Linux).
# Args: port number, e.g. 3000.
set -u

usage() {
  echo "Usage: $0 PORT" >&2
  echo "PORT must be a number from 1 to 65535." >&2
  exit 2
}

PORT="${1:-}"
case "$PORT" in
  ""|*[!0-9]*) usage ;;
esac

if [ "$PORT" -lt 1 ] || [ "$PORT" -gt 65535 ]; then
  usage
fi

echo "=== TCP LISTENERS ON PORT $PORT ==="
found=0

if command -v lsof >/dev/null 2>&1; then
  if lsof -nP -iTCP:"$PORT" -sTCP:LISTEN 2>/dev/null; then
    found=1
  fi
fi

if [ "$found" -eq 0 ] && command -v ss >/dev/null 2>&1; then
  ss_output="$(ss -H -ltnp "sport = :$PORT" 2>/dev/null || true)"
  if [ -n "$ss_output" ]; then
    echo "State Recv-Q Send-Q Local Address:Port Peer Address:Port Process"
    echo "$ss_output"
    found=1
  fi
fi

if [ "$found" -eq 0 ] && command -v netstat >/dev/null 2>&1; then
  netstat_output="$(netstat -an 2>/dev/null | grep -E "([.:])${PORT}[[:space:]].*LISTEN" || true)"
  if [ -n "$netstat_output" ]; then
    echo "$netstat_output"
    found=1
  fi
fi

if [ "$found" -eq 0 ]; then
  echo "No TCP listener found on port $PORT."
fi

exit 0
PC
cat > "$BRIDGE_ROOT/scripts/docker_ps.sh" <<'DPS'
#!/usr/bin/env bash
# docker_ps.sh — list running Docker containers (macOS or Linux).
# Args: none.
set -u

if ! command -v docker >/dev/null 2>&1; then
  echo "Docker is not installed or not in PATH." >&2
  exit 1
fi

if ! docker info >/dev/null 2>&1; then
  echo "Docker is installed but the daemon is not running or not reachable." >&2
  exit 1
fi

echo "=== RUNNING DOCKER CONTAINERS ==="
docker ps --format 'table {{.Names}}\t{{.Image}}\t{{.Status}}\t{{.Ports}}'

exit 0
DPS
cat > "$BRIDGE_ROOT/scripts/docker_logs.sh" <<'DLG'
#!/usr/bin/env bash
# docker_logs.sh — tail a container's logs (macOS or Linux).
# Args: $1 = container name/ID (required), $2 = line count (optional, default 50).
# Usage from Cowork: call_remote("scripts/docker_logs.sh", args=["my-app", "100"])
set -u

usage() {
  echo "Usage: $0 CONTAINER [LINES]" >&2
  exit 2
}

CONTAINER="${1:-}"
LINES="${2:-50}"

[[ -n "$CONTAINER" ]] || usage

case "$LINES" in
  *[!0-9]*|'') usage ;;
esac
if [ "$LINES" -lt 1 ] || [ "$LINES" -gt 10000 ]; then
  echo "LINES must be a number from 1 to 10000." >&2
  exit 2
fi

if ! command -v docker >/dev/null 2>&1; then
  echo "Docker is not installed or not in PATH." >&2
  exit 1
fi

if ! docker info >/dev/null 2>&1; then
  echo "Docker is installed but the daemon is not running or not reachable." >&2
  exit 1
fi

if ! docker inspect "$CONTAINER" >/dev/null 2>&1; then
  echo "Container not found: $CONTAINER" >&2
  exit 1
fi

echo "=== DOCKER LOGS (last $LINES lines): $CONTAINER ==="
docker logs --tail "$LINES" "$CONTAINER"

exit 0
DLG
cat > "$BRIDGE_ROOT/scripts/git_status.sh" <<'GS'
#!/usr/bin/env bash
# git_status.sh — git status in any repo directory.
#
# Text (default): the familiar `git status --short --branch` output.
# JSON (--json):   a parseable object Cowork can consume without scraping text —
#   { "repo", "branch", "upstream", "ahead", "behind", "clean", "files": [ {x,y,path} ] }
#
# Usage from Cowork:
#   call_remote("scripts/git_status.sh", args=["/path/to/repo"])
#   call_remote("scripts/git_status.sh", args=["/path/to/repo", "--json"])
set -euo pipefail

REPO="$PWD"
JSON=0
for arg in "$@"; do
  case "$arg" in
    --json) JSON=1 ;;
    *)      REPO="$arg" ;;
  esac
done
cd "$REPO"

if [ "$JSON" -eq 0 ]; then
  git status --short --branch
  exit 0
fi

# ── JSON mode ────────────────────────────────────────────────────────────────
# Use porcelain v2 + branch headers: stable, machine-oriented, locale-independent.
status="$(git status --porcelain=v2 --branch 2>/dev/null)"

branch=""
upstream=""
ahead=0
behind=0

while IFS= read -r line; do
  case "$line" in
    "# branch.head "*)     branch="${line#\# branch.head }" ;;
    "# branch.upstream "*) upstream="${line#\# branch.upstream }" ;;
    "# branch.ab "*)
      ab="${line#\# branch.ab }"
      a="${ab%% *}"; b="${ab##* }"
      ahead="${a#+}"; behind="${b#-}"
      ;;
  esac
done <<< "$status"

json_escape() { printf '%s' "$1" | sed 's/\\/\\\\/g; s/"/\\"/g'; }

files_json=""
append_file() {
  local x="$1" y="$2" path="$3"
  local entry
  entry="{\"x\":\"$(json_escape "$x")\",\"y\":\"$(json_escape "$y")\",\"path\":\"$(json_escape "$path")\"}"
  if [ -z "$files_json" ]; then files_json="$entry"; else files_json="$files_json,$entry"; fi
}

unquote_path() {
  local p="$1"
  case "$p" in
    \"*\")
      p="${p#\"}"; p="${p%\"}"
      p="${p//\\\"/\"}"; p="${p//\\\\/\\}"
      ;;
  esac
  printf '%s' "$p"
}

while IFS= read -r line; do
  case "$line" in
    "1 "*)
      xy="$(printf '%s' "$line" | cut -d' ' -f2)"
      path="$(printf '%s' "$line" | cut -d' ' -f9-)"
      append_file "${xy:0:1}" "${xy:1:1}" "$path"
      ;;
    "2 "*)
      xy="$(printf '%s' "$line" | cut -d' ' -f2)"
      rest="$(printf '%s' "$line" | cut -d' ' -f10-)"
      path="${rest%%$'\t'*}"
      append_file "${xy:0:1}" "${xy:1:1}" "$path"
      ;;
    "u "*)
      xy="$(printf '%s' "$line" | cut -d' ' -f2)"
      path="$(printf '%s' "$line" | cut -d' ' -f11-)"
      append_file "${xy:0:1}" "${xy:1:1}" "$path"
      ;;
    "? "*)
      append_file "?" "?" "$(unquote_path "${line#\? }")"
      ;;
  esac
done <<< "$status"

clean=true
[ -n "$files_json" ] && clean=false

repo_abs="$(pwd)"
printf '{"repo":"%s","branch":"%s","upstream":"%s","ahead":%s,"behind":%s,"clean":%s,"files":[%s]}\n' \
  "$(json_escape "$repo_abs")" \
  "$(json_escape "$branch")" \
  "$(json_escape "$upstream")" \
  "${ahead:-0}" "${behind:-0}" "$clean" "$files_json"
GS
cat > "$BRIDGE_ROOT/scripts/list_scripts.sh" <<'LS'
#!/usr/bin/env bash
# list_scripts.sh — list every script the bridge can run, with its one-line description.
# Lets Cowork discover what's available instead of guessing.
#
# Usage: list_scripts.sh [--json]
#   (no flag)   human-readable text (default)
#   --json      structured JSON — parse with json.loads() in Cowork
#
# JSON shape: {"scripts":[{"name":"mac_ram.sh","description":"..."},...],"count":N}
# No external dependencies (no jq, no python).
# Usage from Cowork: call_remote("scripts/list_scripts.sh")  # or ("scripts/list_scripts.sh", "--json")
set -uo pipefail
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

JSON=0
for arg in "$@"; do [ "$arg" = "--json" ] && JSON=1; done

# Escape a string for safe embedding in JSON (no jq required).
_jstr() {
  local s="$1"
  s="${s//\\/\\\\}"   # backslash first
  s="${s//\"/\\\"}"   # then double-quote
  s="${s//	/\\t}"    # literal tab
  printf '%s' "$s"
}

shopt -s nullglob

if [ "$JSON" -eq 1 ]; then
  out="{\"scripts\":["
  first=1
  count=0
  for f in "$DIR"/*.sh; do
    name="$(basename "$f")"
    [ "$name" = "list_scripts.sh" ] && continue
    desc="$(awk 'NR>1 && /^#/ {sub(/^# */,""); print; exit}' "$f")"
    [ "$first" -eq 0 ] && out="$out,"
    out="$out{\"name\":\"$(_jstr "$name")\",\"description\":\"$(_jstr "${desc:-}")\"}"
    first=0
    count=$((count + 1))
  done
  out="$out],\"count\":$count}"
  printf '%s\n' "$out"
  exit 0
fi

echo "=== AVAILABLE BRIDGE SCRIPTS ==="
echo "(call any of these with call_remote(\"scripts/<name>\"))"
echo
found=0
for f in "$DIR"/*.sh; do
  name="$(basename "$f")"
  [ "$name" = "list_scripts.sh" ] && continue
  # Pull the first comment line after the shebang as the description.
  desc="$(awk 'NR>1 && /^#/ {sub(/^# */,""); print; exit}' "$f")"
  printf '  %-22s %s\n' "$name" "${desc:-(no description)}"
  found=$((found + 1))
done
[ "$found" -eq 0 ] && echo "  (no scripts found in $DIR)"
exit 0
LS
cat > "$BRIDGE_ROOT/scripts/env_check.sh" <<'EC'
#!/usr/bin/env bash
# env_check.sh — show the environment values Cowork and Claude Code care about.
# Never prints secret VALUES (only whether they are set).
# Usage: env_check.sh [--json]
#   (no flag)   human-readable text (default)
#   --json      structured JSON — parse with json.loads() in Cowork
# JSON fields: bridge_root, bridge_root_exists, bridge_token_set,
#   claude_flags (null if unset), shell, home, os, claude_cli (null if missing).
set -uo pipefail

JSON=0
for arg in "$@"; do [ "$arg" = "--json" ] && JSON=1; done

root="${BRIDGE_ROOT:-$HOME/.cowork-to-code-bridge}"
[ -d "$root" ] && ROOT_EXISTS=1 || ROOT_EXISTS=0

if [ -n "${BRIDGE_TOKEN:-}" ]; then
  TOKEN_SET=1
elif [ -f "$root/.env" ] && grep -q '^BRIDGE_TOKEN=' "$root/.env" 2>/dev/null; then
  TOKEN_SET=1
else
  TOKEN_SET=0
fi

if [ "$(uname)" = "Darwin" ]; then
  OS_DESC="macOS $(sw_vers -productVersion 2>/dev/null || echo '?')"
elif [ -r /etc/os-release ]; then
  OS_DESC="$(. /etc/os-release && echo "$PRETTY_NAME")"
else
  OS_DESC="$(uname -s) $(uname -r)"
fi

claude_path="$(command -v claude 2>/dev/null || true)"

if [ "$JSON" -eq 1 ]; then
  jesc() { printf '%s' "$1" | sed 's/\\/\\\\/g; s/"/\\"/g'; }
  jstr_or_null() { if [ -z "$1" ]; then printf 'null'; else printf '"%s"' "$(jesc "$1")"; fi; }
  bool() { [ "$1" -eq 1 ] && printf 'true' || printf 'false'; }
  printf '{\n'
  printf '  "bridge_root": "%s",\n' "$(jesc "$root")"
  printf '  "bridge_root_exists": %s,\n' "$(bool "$ROOT_EXISTS")"
  printf '  "bridge_token_set": %s,\n' "$(bool "$TOKEN_SET")"
  printf '  "claude_flags": %s,\n' "$(jstr_or_null "${CLAUDE_FLAGS:-}")"
  printf '  "shell": "%s",\n' "$(jesc "${SHELL:-unknown}")"
  printf '  "home": "%s",\n' "$(jesc "${HOME:-unknown}")"
  printf '  "os": "%s",\n' "$(jesc "$OS_DESC")"
  printf '  "claude_cli": %s\n' "$(jstr_or_null "$claude_path")"
  printf '}\n'
  exit 0
fi

echo "=== BRIDGE ENVIRONMENT ==="
printf '%-13s: %s\n' "PATH" "${PATH:-}"
if [ "$ROOT_EXISTS" -eq 1 ]; then
  printf '%-13s: %s  (exists)\n' "BRIDGE_ROOT" "$root"
else
  printf '%-13s: %s  (MISSING)\n' "BRIDGE_ROOT" "$root"
fi
if [ "$TOKEN_SET" -eq 1 ]; then
  if [ -n "${BRIDGE_TOKEN:-}" ]; then
    printf '%-13s: set\n' "BRIDGE_TOKEN"
  else
    printf '%-13s: set (in .env)\n' "BRIDGE_TOKEN"
  fi
else
  printf '%-13s: not set\n' "BRIDGE_TOKEN"
fi
printf '%-13s: %s\n' "CLAUDE_FLAGS" "${CLAUDE_FLAGS:-(not set)}"
printf '%-13s: %s\n' "SHELL" "${SHELL:-unknown}"
printf '%-13s: %s\n' "HOME" "${HOME:-unknown}"
printf '%-13s: %s\n' "OS" "$OS_DESC"
printf '%-13s: %s\n' "claude CLI" "${claude_path:-not found on PATH}"
exit 0
EC
cat > "$BRIDGE_ROOT/scripts/disk_hogs.sh" <<'DH'
#!/usr/bin/env bash
# disk_hogs.sh — biggest files and folders in a directory (default: home).
# Args: [path] [count] [--json]   e.g. call_remote("scripts/disk_hogs.sh", args=["~/Downloads","15"])
#   (no flag)   human-readable text (default)
#   --json      structured JSON — parse with json.loads()
# JSON fields: path, count, items[] (each: size_bytes, size_human, name)
set -uo pipefail
JSON=0; POS=()
for arg in "$@"; do
  case "$arg" in
    --json) JSON=1 ;;
    *) POS+=("$arg") ;;
  esac
done
TARGET="${POS[0]:-$HOME}"
COUNT="${POS[1]:-15}"
# expand a leading ~ since args arrive as literal strings
case "$TARGET" in "~"|"~/"*) TARGET="$HOME${TARGET#\~}";; esac
if ! [[ "$COUNT" =~ ^[0-9]+$ ]]; then
  echo "count must be a number, got: $COUNT" >&2; exit 1
fi
if [ ! -d "$TARGET" ]; then
  echo "not a directory: $TARGET" >&2; exit 1
fi
if [ "$JSON" -eq 1 ]; then
  # `du -k` gives sizes in 1K blocks (portable across macOS/Linux); convert to bytes.
  ITEMS="$(du -k "$TARGET"/* "$TARGET"/.[!.]* 2>/dev/null \
    | sort -rn \
    | head -n "$COUNT" \
    | awk 'BEGIN{first=1; printf "["}
           {
             bytes=$1*1024; name=$2; for(i=3;i<=NF;i++) name=name" "$i;
             gsub(/\\/,"\\\\",name); gsub(/"/,"\\\"",name);
             # compact human size
             h=$1; u="K"; if(h>=1048576){h=h/1048576; u="G"} else if(h>=1024){h=h/1024; u="M"}
             hs=sprintf("%.1f%s", h, u);
             if(!first) printf ",";
             printf "{\"size_bytes\":%d,\"size_human\":\"%s\",\"name\":\"%s\"}", bytes, hs, name;
             first=0
           }
           END{printf "]"}')"
  cat <<EOF
{
  "path": "$TARGET",
  "count": $COUNT,
  "items": ${ITEMS:-[]}
}
EOF
else
  echo "=== TOP $COUNT LARGEST ITEMS IN $TARGET ==="
  # du over immediate children; sort by size desc; human-readable.
  du -sh "$TARGET"/* "$TARGET"/.[!.]* 2>/dev/null \
    | sort -rh \
    | head -n "$COUNT"
fi
exit 0
DH
cat > "$BRIDGE_ROOT/scripts/open_browser.sh" <<'OB'
#!/usr/bin/env bash
# open_browser.sh — open a URL in the machine's default browser.
# Args: <url>   e.g. call_remote("scripts/open_browser.sh", args=["http://localhost:3000"])
set -uo pipefail
URL="${1:-}"
if [ -z "$URL" ]; then
  echo "usage: open_browser.sh <url>" >&2; exit 1
fi
# Only allow http(s) and localhost-style targets; reject file:// and bare paths.
if ! [[ "$URL" =~ ^https?:// ]] \
   && ! [[ "$URL" =~ ^(localhost|127\.0\.0\.1)(:[0-9]+)?(/.*)?$ ]]; then
  echo "refusing to open non-http URL: $URL" >&2; exit 1
fi
# normalise a bare localhost:PORT into a full URL
[[ "$URL" =~ ^https?:// ]] || URL="http://$URL"
if [ "$(uname)" = "Darwin" ]; then
  open "$URL" && echo "opened: $URL"
elif command -v xdg-open >/dev/null 2>&1; then
  xdg-open "$URL" >/dev/null 2>&1 && echo "opened: $URL"
else
  echo "no display / no opener available — open manually: $URL"
fi
exit 0
OB
cat > "$BRIDGE_ROOT/scripts/pkg_outdated.sh" <<'POD'
#!/usr/bin/env bash
# pkg_outdated.sh — list outdated system packages (macOS or Linux).
# Detects the package manager: brew on macOS; apt/dnf/yum/pacman on Linux.
# Args: none.
set -u

echo "=== OUTDATED PACKAGES ==="
found=0

if command -v brew >/dev/null 2>&1; then
  echo "--- Homebrew (brew outdated) ---"
  brew outdated || true
  found=1
fi

if [ "$found" -eq 0 ] && command -v apt >/dev/null 2>&1; then
  echo "--- APT (apt list --upgradable) ---"
  apt list --upgradable 2>/dev/null || true
  found=1
fi

if [ "$found" -eq 0 ] && command -v dnf >/dev/null 2>&1; then
  echo "--- DNF (dnf check-update) ---"
  # dnf check-update exits 100 when updates exist; don't treat that as an error.
  dnf check-update || true
  found=1
fi

if [ "$found" -eq 0 ] && command -v yum >/dev/null 2>&1; then
  echo "--- YUM (yum check-update) ---"
  yum check-update || true
  found=1
fi

if [ "$found" -eq 0 ] && command -v pacman >/dev/null 2>&1; then
  echo "--- pacman (pacman -Qu) ---"
  pacman -Qu || true
  found=1
fi

if [ "$found" -eq 0 ]; then
  echo "No supported package manager found (looked for brew, apt, dnf, yum, pacman)."
fi

exit 0
POD
# request_cowork.sh — REVERSE direction: hand a request from this machine to a
# Cowork session (async inbox; Cowork picks it up next time one is open).
cat > "$BRIDGE_ROOT/scripts/request_cowork.sh" <<'REQCW'
#!/usr/bin/env bash
# request_cowork.sh — drop a request for a Claude Cowork session (async inbox).
# Cowork has no inbound address, so this queues to BRIDGE_ROOT/to_cowork/ and a
# Cowork session picks it up next time one is open and checks its inbox.
# Usage: request_cowork.sh "<request text>" [--wait SECONDS]
set -euo pipefail
BRIDGE_ROOT="${BRIDGE_ROOT:-$HOME/.cowork-to-code-bridge}"
INBOX="$BRIDGE_ROOT/to_cowork"; REPLIES="$BRIDGE_ROOT/cowork_results"
REQUEST="${1:?usage: request_cowork.sh \"<request>\" [--wait SECONDS]}"; shift || true
WAIT=0
if [[ "${1:-}" == "--wait" ]]; then
  WAIT="${2:-300}"
  [[ "$WAIT" =~ ^[0-9]+$ ]] || { echo "--wait expects seconds, got: $WAIT" >&2; exit 2; }
  shift 2 || true
fi
mkdir -p "$INBOX" "$REPLIES"; chmod 700 "$INBOX" "$REPLIES" 2>/dev/null || true
ID="$(date +%s)_$$_${RANDOM}"
TOKEN=""
[[ -f "$BRIDGE_ROOT/.env" ]] && TOKEN="$(grep '^BRIDGE_TOKEN=' "$BRIDGE_ROOT/.env" 2>/dev/null | head -1 | cut -d= -f2- | tr -d '"' | tr -d "'" | tr -d '[:space:]')"
TMP="$INBOX/.$ID.json.tmp"; OUT="$INBOX/$ID.json"
PARENT="${BRIDGE_CMD_ID:-}"
python3 - "$ID" "$REQUEST" "$TOKEN" "$PARENT" >"$TMP" <<'PY'
import json,sys,time
_id,req,tok,parent=sys.argv[1],sys.argv[2],sys.argv[3],sys.argv[4]
o={"id":_id,"request":req,"ts":time.time(),"from":"claude-code"}
if tok:o["token"]=tok
if parent:o["parent"]=parent
print(json.dumps(o))
PY
mv "$TMP" "$OUT"; echo "queued request for Cowork: $OUT"
if [[ "$WAIT" -gt 0 ]]; then
  RF="$REPLIES/$ID.json"; dl=$(( $(date +%s)+WAIT ))
  while [[ "$(date +%s)" -lt "$dl" ]]; do [[ -f "$RF" ]] && { echo "=== reply ==="; cat "$RF"; exit 0; }; sleep 2; done
  echo "no reply within ${WAIT}s (Cowork may not be open); request stays queued." >&2
  exit 1
fi
REQCW
chmod +x "$BRIDGE_ROOT/scripts/request_cowork.sh"
mkdir -p "$BRIDGE_ROOT/to_cowork" "$BRIDGE_ROOT/cowork_results"
chmod 700 "$BRIDGE_ROOT/to_cowork" "$BRIDGE_ROOT/cowork_results" 2>/dev/null || true

# escalate_to_claude.sh — hand a task from an external agent (Hermes, cron, etc.)
# to Claude Code running on this machine.
cat > "$BRIDGE_ROOT/scripts/escalate_to_claude.sh" <<'ESCL'
#!/usr/bin/env bash
# escalate_to_claude.sh — hand a task from Hermes/daemon to Claude Code on this machine.
# Usage: escalate_to_claude.sh "Debug the API issue" [--wait SECONDS]
set -euo pipefail
BRIDGE_ROOT="${BRIDGE_ROOT:-$HOME/.cowork-to-code-bridge}"
INBOX="$BRIDGE_ROOT/to_cowork"; REPLIES="$BRIDGE_ROOT/cowork_results"
REQUEST="${1:?usage: escalate_to_claude.sh \"<escalation text>\" [--wait SECONDS]}"; shift || true
WAIT=0
if [[ "${1:-}" == "--wait" ]]; then
  WAIT="${2:-300}"
  [[ "$WAIT" =~ ^[0-9]+$ ]] || { echo "--wait expects seconds, got: $WAIT" >&2; exit 2; }
  shift 2 || true
fi
mkdir -p "$INBOX" "$REPLIES"; chmod 700 "$INBOX" "$REPLIES" 2>/dev/null || true
ID="$(date +%s)_$$_${RANDOM}"
TOKEN=""
[[ -f "$BRIDGE_ROOT/.env" ]] && TOKEN="$(grep '^BRIDGE_TOKEN=' "$BRIDGE_ROOT/.env" 2>/dev/null | head -1 | cut -d= -f2- | tr -d '"' | tr -d "'" | tr -d '[:space:]')"
TMP="$INBOX/.$ID.json.tmp"; OUT="$INBOX/$ID.json"
python3 - "$ID" "$REQUEST" "$TOKEN" >"$TMP" <<'PY'
import json,sys,time,os
_id,req,tok=sys.argv[1],sys.argv[2],sys.argv[3]
o={"id":_id,"request":req,"ts":time.time(),"from":"escalation-daemon","escalation_context":{"hostname":os.uname().nodename,"user":os.getenv("USER","unknown"),"cwd":os.getcwd()}}
if tok:o["token"]=tok
print(json.dumps(o))
PY
mv "$TMP" "$OUT"; echo "escalation queued for Claude Code: $OUT"
if [[ "$WAIT" -gt 0 ]]; then
  RF="$REPLIES/$ID.json"; dl=$(( $(date +%s)+WAIT ))
  while [[ "$(date +%s)" -lt "$dl" ]]; do [[ -f "$RF" ]] && { echo "=== Claude Code reply ==="; cat "$RF"; exit 0; }; sleep 2; done
  echo "no reply within ${WAIT}s; escalation stays queued." >&2
fi
ESCL
chmod +x "$BRIDGE_ROOT/scripts/escalate_to_claude.sh"

chmod +x "$BRIDGE_ROOT"/scripts/mac_*.sh "$BRIDGE_ROOT/scripts/port_check.sh" "$BRIDGE_ROOT/scripts/docker_ps.sh" "$BRIDGE_ROOT/scripts/docker_logs.sh" "$BRIDGE_ROOT/scripts/pkg_outdated.sh" "$BRIDGE_ROOT/scripts/git_status.sh" "$BRIDGE_ROOT/scripts/list_scripts.sh" "$BRIDGE_ROOT/scripts/env_check.sh" "$BRIDGE_ROOT/scripts/disk_hogs.sh" "$BRIDGE_ROOT/scripts/open_browser.sh" "$BRIDGE_ROOT/scripts/escalate_to_claude.sh"

# process_kill.sh — terminate a named process or PID from Cowork.
# Safety guards: refuses PID ≤ 10, refuses protected names (launchd/kernel_task/
# systemd/init/kernel/kthreadd), refuses >1 name match unless --all is passed.
# Sends SIGTERM (graceful); never SIGKILL.
# Testability: BRIDGE_PGREP_CMD / BRIDGE_KILL_CMD env vars let tests inject fakes.
cat > "$BRIDGE_ROOT/scripts/process_kill.sh" <<'PK'
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
PK
chmod +x "$BRIDGE_ROOT/scripts/process_kill.sh"

# mcp_audit.sh — cross-surface MCP audit.
# Addresses: anthropics/claude-code#56353 — no first-class tool to compare
# MCPs registered in local Claude Code vs what a Cowork session can reach.
# This script runs on the machine side; Cowork receives the JSON output and
# can diff it against its own session's available connectors/plugins.
cat > "$BRIDGE_ROOT/scripts/mcp_audit.sh" <<'MCPAUDIT'
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
MCPAUDIT
chmod +x "$BRIDGE_ROOT/scripts/mcp_audit.sh"


c_green "  ✓ scripts installed: ping, hello, run_claude, mac_health, mac_ram, mac_disk, mac_top, mac_network, port_check, docker_ps, docker_logs, pkg_outdated, git_status, list_scripts, env_check, disk_hogs, open_browser, request_cowork, process_kill, mcp_audit"

# ─── 5b. Fetch the single-file Cowork client (one source of truth) ───────────
# bridge_client.py is the EXACT file the Cowork sandbox imports. To avoid drift,
# we fetch the canonical copy from the repo at install time (the Mac has network
# — this runs in the user's terminal, not the sandbox). Falls back to the
# installed package's client if the fetch fails offline.
CLIENT_URL="https://raw.githubusercontent.com/$REPO/main/bridge_client.py"
if curl -fsSL "$CLIENT_URL" -o "$BRIDGE_ROOT/bridge_client.py" 2>/dev/null \
   && head -1 "$BRIDGE_ROOT/bridge_client.py" | grep -q "bridge_client"; then
  c_green "  ✓ Cowork client fetched to $BRIDGE_ROOT/bridge_client.py"
else
  # Offline fallback: copy from the just-installed package.
  PKG_CLIENT="$("$PY" -c 'import cowork_to_code_bridge, os; print(os.path.join(os.path.dirname(cowork_to_code_bridge.__file__), "client.py"))' 2>/dev/null || true)"
  if [[ -n "$PKG_CLIENT" && -f "$PKG_CLIENT" ]]; then
    cp "$PKG_CLIENT" "$BRIDGE_ROOT/bridge_client.py"
    c_yellow "  ! fetch failed; used the installed package client as fallback"
  else
    c_red "  ✗ could not obtain bridge_client.py (no network and no package copy)."
    exit 1
  fi
fi

# ─── 5c. Install the GLOBAL Cowork skill (~/.claude/skills) ──────────────────
# This is what makes the bridge work in EVERY Cowork session, every project,
# with zero fetch / zero paste / zero popups: a skill in ~/.claude/skills auto-
# loads into all sessions. We drop the SKILL.md + the client + a tiny config
# pointing at BRIDGE_ROOT. No /plugin, no marketplace.
step "Installing the global Cowork skill"
SKILLS_DIR="$HOME/.claude/skills/cowork-to-code-bridge"
mkdir -p "$SKILLS_DIR"
# The client (same single file) lives next to the skill so Cowork can import it.
cp "$BRIDGE_ROOT/bridge_client.py" "$SKILLS_DIR/bridge_client.py"
# Config so the skill knows BRIDGE_ROOT without the user pasting a path.
printf '{ "BRIDGE_ROOT": "%s" }\n' "$BRIDGE_ROOT" > "$SKILLS_DIR/bridge_env.json"

cat > "$SKILLS_DIR/SKILL.md" <<SKILLMD
---
name: cowork-to-code-bridge
description: Connects Claude Cowork to Claude Code running on the user's own computer (macOS or Linux), so the whole machine is reachable from a Cowork chat. Use this skill whenever the user asks to do something that needs their actual machine and can't be done in the Cowork sandbox — building or running an app, running tests, git push/pull, installing packages, npm/pip/brew/docker, checking the machine's health/RAM/disk/processes, or any task they describe as "on my Mac" or "on my machine/server". Also triggers on "build me an app", "run this on my machine", "use Claude Code on my computer", "connect to my Mac", "check my machine". The bridge hands the task to a real Claude Code agent on the machine; it is idempotent and survives reboots.
---

# cowork-to-code-bridge

You are in a Cowork sandbox. This skill reaches **Claude Code on the user's Mac**
through a local daemon. The client (\`bridge_client.py\`) is already installed next
to this file. Do NOT fetch/download anything; do NOT use \`/plugin\`.

## Step 1 — connect (always first)

\`\`\`python
import os, sys, json
SKILL_DIR = os.path.expanduser("~/.claude/skills/cowork-to-code-bridge")
sys.path.insert(0, SKILL_DIR)
cfg = os.path.join(SKILL_DIR, "bridge_env.json")
if os.path.exists(cfg):
    os.environ.setdefault("BRIDGE_ROOT", json.load(open(cfg)).get("BRIDGE_ROOT", ""))
from bridge_client import daemon_alive, call_remote
print("BRIDGE LIVE" if daemon_alive(ping_timeout=10) else "DAEMON NOT REACHABLE")
\`\`\`

If DAEMON NOT REACHABLE, the Mac side isn't set up: tell the user to run, once,
in their Mac Terminal — \`curl -fsSL https://raw.githubusercontent.com/$REPO/main/install.sh | bash\`
— then retry. (macOS, Linux with systemd or manual path, or WSL2 with systemd; native Windows not supported.)

## Step 2 — hand a task to Claude Code (main use)

\`\`\`python
r = call_remote("scripts/run_claude.sh",
    args=["Build a Flask app with a /health route, install deps, run it", "/Users/<them>/projects/app"],
    timeout=600, idempotency_key="unique-key-per-task")
print(r["exit_code"]); print(r["stdout"])
\`\`\`
Always pass a unique \`idempotency_key\` — Claude Code tasks have side effects, so a
retry must not run twice.

### Per-task cost cap
Pass \`max_budget_usd=2.00\` to stop the agent when that amount is spent.
The owner can set \`BRIDGE_MAX_BUDGET_USD\` as a global ceiling that can never
be exceeded regardless of what Cowork sends (effective = min(caller, owner)).

## Step 3 — streaming + interactive tasks

For long tasks use \`call_remote_streaming\`. Add \`interactive=True\` to handle
mid-task questions from the script (approval gates, config requests, decision points).

\`\`\`python
from bridge_client import call_remote_streaming, reply_to_machine, resume_remote

r = call_remote_streaming("scripts/run_claude.sh",
    args=["Deploy to prod", "/path/to/repo"],
    timeout=900, interactive=True)

while r.get("state") == "awaiting_reply":
    # Script paused and asked a question — show it to the user, get answer.
    answer = input(f"Script asks: {r['question']} > ")
    reply_to_machine(r["request_id"], answer, bridge_root=r["_bridge_root"])
    r = resume_remote(r["cmd_id"], r["_deadline"], bridge_root=r["_bridge_root"])

print(r["exit_code"], r["stdout"])
\`\`\`

Return shape when a question arrives:
\`\`\`json
{"state": "awaiting_reply", "cmd_id": "...", "request_id": "...",
 "question": "Deploy to production?", "from": "claude-code",
 "_deadline": 1234567890.0, "_bridge_root": "/Users/.../.cowork-to-code-bridge"}
\`\`\`

On the script side, \`request_cowork.sh "question" --wait 120\` blocks until Cowork
replies or times out. Timeout exits 1 (not 0) — scripts can detect and handle it.
Set a generous \`timeout=\` for interactive tasks; the clock doesn't pause while
waiting for an answer.

## Step 4 — quick system checks (no agent)
\`call_remote("scripts/mac_health.sh")\` · \`mac_ram.sh\` · \`mac_disk.sh\` · \`mac_top.sh\` · \`mac_network.sh\` · \`port_check.sh\` · \`docker_ps.sh\` · \`docker_logs.sh\` · \`pkg_outdated.sh\` · \`git_status.sh <path>\`

## Results
Dict with exit_code/stdout/stderr. Codes: -1 refused, -2 timeout, -3 internal,
-4 crashed-midrun (indeterminate, not retried). \`idempotent_replay: True\` = cached.
Be brief with the user; never claim success without exit_code 0 / BRIDGE LIVE.
SKILLMD
c_green "  ✓ global skill installed at $SKILLS_DIR (loads in every Cowork session)"

# ─── 5d. Drop a CLAUDE.md INTO the bridge folder ─────────────────────────────
# When a Cowork session mounts BRIDGE_ROOT, this note tells the agent exactly
# how to use the bridge — so the connection is self-documenting after the mount.
cat > "$BRIDGE_ROOT/CLAUDE.md" <<CLAUDEMD
# cowork-to-code-bridge — you are connected to the user's machine

If you can read this file, the bridge folder ($BRIDGE_ROOT) is mounted into your
sandbox. That means you can run things on the user's real machine (macOS, Linux, or WSL2)
through this bridge. Use it for anything the sandbox can't do: builds, tests,
git, installs, system checks, or handing a task to Claude Code.

## Connect (do this first)

\`\`\`python
import sys, os, json
sys.path.insert(0, "$SKILLS_DIR")
os.environ.setdefault("BRIDGE_ROOT", "$BRIDGE_ROOT")
from bridge_client import daemon_alive, call_remote, call_remote_streaming
print("BRIDGE LIVE" if daemon_alive(ping_timeout=10) else "DAEMON NOT REACHABLE")
\`\`\`

(If \`bridge_client.py\` isn't importable, it's also at \`$BRIDGE_ROOT/bridge_client.py\` —
add that dir to sys.path instead.)

## Hand a task to Claude Code on the machine
\`\`\`python
r = call_remote("scripts/run_claude.sh",
    args=["<your task>", "<working dir>"], timeout=600, idempotency_key="<unique>")
print(r["exit_code"]); print(r["stdout"])
\`\`\`
Always pass a unique idempotency_key (tasks have side effects). For long builds,
use call_remote_streaming(..., on_progress=cb). For a live spinner/ticker:
\`\`\`python
def on_status(s):
    sp = "⣾⣽⣻⢿⡿⣟⣯⣷"
    print(f"\r  {sp[s['elapsed_s']%8]} {s['last_line'][:60]}… ({s['elapsed_s']}s)", end="", flush=True)
call_remote_streaming("scripts/run_claude.sh", args=[...], timeout=900, on_status=on_status)
\`\`\`
Status dict keys: elapsed_s (int), last_line (str), state ("running"|"done"|"error").

## Quick checks (no agent)
scripts/mac_health.sh · mac_ram.sh · mac_disk.sh · mac_top.sh · mac_network.sh · port_check.sh <port> · docker_ps.sh · docker_logs.sh <container> · pkg_outdated.sh · git_status.sh <path>

Results: dict with exit_code/stdout/stderr (-1 refused, -2 timeout, -3 internal,
-4 crashed). Never claim success without exit_code 0 / BRIDGE LIVE.
CLAUDEMD
c_green "  ✓ wrote $BRIDGE_ROOT/CLAUDE.md (self-documents the bridge once mounted)"

# ─── 6. Install + start the daemon as a per-user service ─────────────────────
step "Installing background service ($SERVICE_MGR, auto-start + reboot-safe)"

# Resolve the daemon entry point to an ABSOLUTE path. Prefer the installed
# console script under the per-user scripts dir (independent of PATH).
DAEMON_ARGS=()
CONSOLE_SCRIPT="$USER_SCRIPTS_DIR/cowork-to-code-bridge-daemon"

if [[ -x "$CONSOLE_SCRIPT" ]]; then
  DAEMON_ARGS=("$CONSOLE_SCRIPT")
elif command -v cowork-to-code-bridge-daemon >/dev/null 2>&1; then
  DAEMON_ARGS=("$(command -v cowork-to-code-bridge-daemon)")
elif "$PY" -c "import cowork_to_code_bridge.daemon" 2>/dev/null; then
  DAEMON_ARGS=("$PY" "-m" "cowork_to_code_bridge.daemon")
else
  c_red "  ✗ cowork-to-code-bridge daemon module not found after install"
  exit 1
fi
c_green "  ✓ daemon entry: ${DAEMON_ARGS[*]}"

LABEL="dev.cowork-to-code-bridge.daemon"
daemon_up=0

if [[ "$SERVICE_MGR" == "launchd" ]]; then
  # ── macOS: launchd user agent ──────────────────────────────────────────────
  mkdir -p "$(dirname "$PLIST")"
  {
    echo '<?xml version="1.0" encoding="UTF-8"?>'
    echo '<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">'
    echo '<plist version="1.0">'
    echo '<dict>'
    echo "  <key>Label</key><string>$LABEL</string>"
    echo '  <key>ProgramArguments</key>'
    echo '  <array>'
    for arg in "${DAEMON_ARGS[@]}"; do
      safe=$(printf '%s' "$arg" | sed -e 's/&/\&amp;/g' -e 's/</\&lt;/g' -e 's/>/\&gt;/g')
      echo "    <string>$safe</string>"
    done
    echo '  </array>'
    echo '  <key>EnvironmentVariables</key>'
    echo '  <dict>'
    echo "    <key>BRIDGE_ROOT</key><string>$BRIDGE_ROOT</string>"
    echo "    <key>PATH</key><string>$USER_SCRIPTS_DIR:/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin</string>"
    echo '  </dict>'
    echo '  <key>RunAtLoad</key><true/>'
    echo '  <key>KeepAlive</key><true/>'
    echo "  <key>StandardOutPath</key><string>$DAEMON_LOG</string>"
    echo "  <key>StandardErrorPath</key><string>$DAEMON_ERR</string>"
    echo "  <key>WorkingDirectory</key><string>$BRIDGE_ROOT</string>"
    echo '</dict>'
    echo '</plist>'
  } > "$PLIST"
  c_green "  ✓ plist written: $PLIST"

  UID_NUM="$(id -u)"
  DOMAIN="gui/$UID_NUM"
  if launchctl print "$DOMAIN/$LABEL" >/dev/null 2>&1; then
    c_yellow "  → bootout existing agent"
    launchctl bootout "$DOMAIN/$LABEL" 2>/dev/null || true
  fi
  launchctl unload "$PLIST" 2>/dev/null || true
  if launchctl bootstrap "$DOMAIN" "$PLIST" 2>/dev/null; then
    c_green "  ✓ launchctl bootstrap $DOMAIN succeeded"
  else
    c_yellow "  ! launchctl bootstrap failed — falling back to legacy load -w"
    launchctl load -w "$PLIST"
  fi
  launchctl enable "$DOMAIN/$LABEL" 2>/dev/null || true
  sleep 2

  step "Verifying daemon"
  if launchctl print "$DOMAIN/$LABEL" >/dev/null 2>&1 || \
     launchctl list 2>/dev/null | grep -q "$LABEL"; then
    c_green "  ✓ daemon registered with launchd"
  else
    c_red "  ✗ daemon failed to register"
    tail -20 "$DAEMON_ERR" 2>/dev/null || true
    exit 1
  fi

elif [[ "$SERVICE_MGR" == "systemd" ]]; then
  # ── Linux: systemd --user unit ─────────────────────────────────────────────
  UNIT_DIR="$HOME/.config/systemd/user"
  UNIT="$UNIT_DIR/cowork-to-code-bridge.service"
  mkdir -p "$UNIT_DIR"
  # Build ExecStart with each arg shell-quoted.
  EXECSTART=""
  for arg in "${DAEMON_ARGS[@]}"; do EXECSTART+="'$arg' "; done
  {
    echo '[Unit]'
    echo 'Description=cowork-to-code-bridge daemon (connect Claude to this machine)'
    echo 'After=default.target'
    echo
    echo '[Service]'
    echo 'Type=simple'
    echo "Environment=BRIDGE_ROOT=$BRIDGE_ROOT"
    echo "Environment=PATH=$USER_SCRIPTS_DIR:/usr/local/bin:/usr/bin:/bin"
    echo "WorkingDirectory=$BRIDGE_ROOT"
    echo "ExecStart=/bin/sh -lc \"exec $EXECSTART\""
    echo 'Restart=always'
    echo 'RestartSec=2'
    echo "StandardOutput=append:$DAEMON_LOG"
    echo "StandardError=append:$DAEMON_ERR"
    echo
    echo '[Install]'
    echo 'WantedBy=default.target'
  } > "$UNIT"
  c_green "  ✓ systemd unit written: $UNIT"

  # Enable lingering so the user service survives logout and starts at boot.
  linger_ok=0
  if command -v loginctl >/dev/null 2>&1; then
    if loginctl enable-linger "$(id -un)" 2>/dev/null; then
      c_green "  ✓ lingering enabled (survives logout/reboot)"
      linger_ok=1
    else
      c_yellow "  ! could not enable lingering (service still runs while logged in)"
    fi
  fi
  if [[ "$IS_WSL" -eq 1 ]] && [[ "$linger_ok" -eq 0 ]]; then
    c_yellow "  ! On WSL2, lingering may not survive Windows sleep/reboot like on a server;"
    c_yellow "    the daemon runs while your WSL session is up."
  fi
  systemctl --user daemon-reload 2>/dev/null || true
  systemctl --user enable --now cowork-to-code-bridge.service 2>/dev/null \
    || systemctl --user restart cowork-to-code-bridge.service 2>/dev/null || true
  sleep 2

  step "Verifying daemon"
  if systemctl --user is-active --quiet cowork-to-code-bridge.service; then
    c_green "  ✓ daemon active under systemd --user"
  else
    c_red "  ✗ systemd service is not active"
    systemctl --user status cowork-to-code-bridge.service --no-pager 2>/dev/null | tail -15 || true
    tail -20 "$DAEMON_ERR" 2>/dev/null || true
    exit 1
  fi

else
  # ── Linux: manual daemon (no systemd user bus) ───────────────────────────
  mkdir -p "$BRIDGE_ROOT/lib"
  if [[ -n "$_INSTALL_DIR" && -f "$_INSTALL_DIR/scripts/lib/daemon_service.sh" ]]; then
    cp "$_INSTALL_DIR/scripts/lib/daemon_service.sh" "$BRIDGE_ROOT/lib/daemon_service.sh"
  elif ! curl -fsSL "https://raw.githubusercontent.com/$REPO/main/scripts/lib/daemon_service.sh" \
      -o "$BRIDGE_ROOT/lib/daemon_service.sh" 2>/dev/null; then
    c_red "  ✗ could not install daemon_service.sh (offline?)"
    exit 1
  fi
  if ! declare -F bridge_start_daemon_manual >/dev/null 2>&1; then
    # shellcheck source=/dev/null
    source "$BRIDGE_ROOT/lib/daemon_service.sh"
  fi

  START_SCRIPT="$BRIDGE_ROOT/start-daemon.sh"
  {
    echo '#!/usr/bin/env bash'
    echo '# start-daemon.sh — start the bridge daemon (non-systemd Linux).'
    echo 'set -euo pipefail'
    echo "BRIDGE_ROOT=\"$BRIDGE_ROOT\""
    echo "export BRIDGE_ROOT"
    echo "DAEMON_LOG=\"$DAEMON_LOG\""
    echo "DAEMON_ERR=\"$DAEMON_ERR\""
    echo "USER_SCRIPTS_DIR=\"$USER_SCRIPTS_DIR\""
    echo 'export PATH="'"$USER_SCRIPTS_DIR"':$PATH:/usr/local/bin:/usr/bin:/bin"'
    echo 'DAEMON_ARGS=('
    for arg in "${DAEMON_ARGS[@]}"; do
      printf '  %q\n' "$arg"
    done
    echo ')'
    echo 'source "$BRIDGE_ROOT/lib/daemon_service.sh"'
    echo 'bridge_start_daemon_manual'
  } > "$START_SCRIPT"
  chmod +x "$START_SCRIPT"
  c_green "  ✓ wrote $START_SCRIPT"

  if bridge_start_daemon_manual; then
    c_green "  ✓ daemon started (setsid/nohup, pid in $BRIDGE_ROOT/daemon.pid)"
  else
    c_red "  ✗ failed to start daemon manually"
    tail -20 "$DAEMON_ERR" 2>/dev/null || true
    exit 1
  fi

  if bridge_install_cron_reboot "$START_SCRIPT"; then
    c_green "  ✓ @reboot cron entry installed (survives reboot when crond runs)"
  else
    c_yellow "  ! no @reboot cron (crontab missing or BRIDGE_SKIP_CRON=1)"
    c_yellow "    After reboot, run: $START_SCRIPT"
    c_yellow "    Guide: $NO_SYSTEMD_DOC"
  fi

  step "Verifying daemon"
  if bridge_manual_daemon_running; then
    c_green "  ✓ daemon process running (manual)"
  else
    c_red "  ✗ manual daemon is not running"
    tail -20 "$DAEMON_ERR" 2>/dev/null || true
    exit 1
  fi
fi

# Wait up to 20s for the daemon to log its first heartbeat (cold caches are slow).
for i in $(seq 1 20); do
  if [[ -f "$DAEMON_LOG" ]] && grep -q "daemon up" "$DAEMON_LOG" 2>/dev/null; then
    c_green "  ✓ daemon log shows 'daemon up' (after ${i}s)"
    daemon_up=1
    break
  fi
  sleep 1
done

if [[ "$daemon_up" -eq 0 ]]; then
  c_yellow "  ! daemon hasn't logged 'daemon up' within 20s — last stderr lines:"
  tail -20 "$DAEMON_ERR" 2>/dev/null || true
  c_yellow "    (Not aborting — the daemon may still come up. Check $DAEMON_LOG manually.)"
fi

# ─── 8. PATH hygiene ─────────────────────────────────────────────────────────
step "Checking PATH for $USER_SCRIPTS_DIR"

path_has_dir=0
case ":$PATH:" in
  *":$USER_SCRIPTS_DIR:"*) path_has_dir=1 ;;
esac

# Prefer bashrc on Linux/WSL; zshrc on macOS or when default shell is zsh.
if [[ "$OS" == "Linux" ]] || [[ "$IS_WSL" -eq 1 ]]; then
  if [[ "${SHELL:-}" == *zsh* ]]; then
    SHELL_RC="$HOME/.zshrc"
  else
    SHELL_RC="$HOME/.bashrc"
  fi
else
  SHELL_RC="$HOME/.zshrc"
fi
PATH_LINE="export PATH=\"$USER_SCRIPTS_DIR:\$PATH\"  # cowork-to-code-bridge"

if [[ "$path_has_dir" -eq 1 ]]; then
  c_green "  ✓ $USER_SCRIPTS_DIR already on PATH"
else
  c_yellow "  ! $USER_SCRIPTS_DIR is NOT on your PATH."
  echo "    The 'cowork-to-code-bridge-uninstall' and 'cowork-to-code-bridge-daemon'"
  echo "    commands live there. To use them by bare name, add this to $SHELL_RC:"
  echo
  echo "      $PATH_LINE"
  echo

  # Skip the prompt entirely when stdin isn't a TTY (e.g. curl | bash).
  if [[ -t 0 ]]; then
    read -r -p "  Append this line to $SHELL_RC now? [y/N] " ans
    if [[ "$ans" =~ ^[Yy]$ ]]; then
      if [[ -f "$SHELL_RC" ]] && grep -Fq "$USER_SCRIPTS_DIR" "$SHELL_RC"; then
        c_yellow "    (already referenced in $SHELL_RC — not appending duplicate)"
      else
        printf '\n# Added by cowork-to-code-bridge installer\n%s\n' "$PATH_LINE" >> "$SHELL_RC"
        c_green "  ✓ appended to $SHELL_RC — open a new terminal or run: source $SHELL_RC"
      fi
    else
      c_yellow "    skipped — add the export line manually when convenient."
    fi
  else
    c_yellow "  (non-interactive shell — not prompting. Add the line above manually.)"
  fi
fi

# ─── 9. Done ─────────────────────────────────────────────────────────────────
step "DONE. Bridge is installed and running."

if [[ "$SERVICE_MGR" == "launchd" ]]; then
  VERIFY_CMD="launchctl print gui/$(id -u)/$LABEL"
elif [[ "$SERVICE_MGR" == "systemd" ]]; then
  VERIFY_CMD="systemctl --user status cowork-to-code-bridge.service"
else
  VERIFY_CMD="test -f $BRIDGE_ROOT/daemon.pid && kill -0 \$(cat $BRIDGE_ROOT/daemon.pid) && tail -3 $DAEMON_LOG"
fi

cat <<DONE

$(c_green "✓ Your machine side is installed and running.")

ONE more step, in Cowork — paste this line into any Claude Cowork chat to
connect (Cowork needs permission to see the bridge folder; this asks for it):

$(c_green "  Connect to my machine via the cowork-to-code bridge at $BRIDGE_ROOT — mount that folder, read its CLAUDE.md, and confirm the bridge is live.")

Claude will request access to that folder (approve it), read the instructions
inside, and confirm "BRIDGE LIVE". After that, in THAT chat you can just say:
DONE

if [[ "$IS_WSL" -eq 1 ]]; then
  cat <<DONE

$(c_yellow "WSL2 note:") Use the WSL path above ($BRIDGE_ROOT), not a Windows
  path like C:\\... or /mnt/c/... — Cowork must mount the folder where the
  daemon runs (inside WSL). Guide: $WSL_DOC
DONE
fi

cat <<DONE

  • "build me a small web app on my machine"
  • "run my tests and fix what's failing"
  • "check my machine's health"   • "git push my project"

…and Claude hands the work to Claude Code on this machine and brings back the
result. (You only paste the connect line once per chat. If a chat doesn't see
the bridge, paste it again — that's the cue for Claude to request the mount.)

Bridge folder: $BRIDGE_ROOT
Skill folder:  $HOME/.claude/skills/cowork-to-code-bridge

Manual verification (optional):
  $VERIFY_CMD   # service state
  cat $ENV_FILE                                       # token + bridge root
  tail -f $DAEMON_LOG                                 # live daemon output

Python interpreter:  $PY  ($PY_VER)
User scripts dir:    $USER_SCRIPTS_DIR

Uninstall (one command — undoes everything this installer did):
  $USER_SCRIPTS_DIR/cowork-to-code-bridge-uninstall

Or, if $USER_SCRIPTS_DIR is on your PATH:
  cowork-to-code-bridge-uninstall

Non-interactively:
  cowork-to-code-bridge-uninstall --yes

If neither path is available:
  curl -fsSL https://raw.githubusercontent.com/$REPO/main/daemon/uninstall.sh | bash

$(c_yellow "⭐ If this saved you time, a star on GitHub helps others find it:")
  https://github.com/$REPO

DONE
