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

exec "$CLAUDE_BIN" "${EXTRA_FLAGS[@]}" "${BUDGET_FLAGS[@]}" -p "$TASK" --output-format text
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
# mac_ram.sh — RAM usage summary (macOS or Linux). Args: none.
set -u
if [ "$(uname -s)" = "Darwin" ]; then
  TOTAL=$(sysctl -n hw.memsize 2>/dev/null)
  echo "Total RAM: $(( TOTAL / 1024 / 1024 / 1024 )) GB"
  echo "--- vm_stat ---"; vm_stat 2>/dev/null
else
  free -h 2>/dev/null || cat /proc/meminfo 2>/dev/null | head -5
fi
exit 0
MR
cat > "$BRIDGE_ROOT/scripts/mac_disk.sh" <<'MD'
#!/usr/bin/env bash
# mac_disk.sh — disk usage (fast). Args: optional path (default /).
set -u
echo "=== DISK USAGE ==="; df -h "${1:-/}" 2>/dev/null
echo; echo "=== ALL MOUNTED VOLUMES ==="; df -h 2>/dev/null | grep -E "^/dev|Filesystem" | head -10
exit 0
MD
cat > "$BRIDGE_ROOT/scripts/mac_top.sh" <<'MT'
#!/usr/bin/env bash
# mac_top.sh — top processes by CPU and memory (macOS or Linux). Args: count (default 15).
set -u
N="${1:-15}"
echo "=== by CPU ==="; ps -eo pid,pcpu,pmem,comm 2>/dev/null | sort -k2 -rn | head -"$((N+1))"
echo "=== by MEM ==="; ps -eo pid,pcpu,pmem,comm 2>/dev/null | sort -k3 -rn | head -"$((N+1))"
exit 0
MT
cat > "$BRIDGE_ROOT/scripts/mac_network.sh" <<'MN'
#!/usr/bin/env bash
# mac_network.sh — network status (macOS or Linux). Args: none.
set -u
echo "=== interfaces (active) ==="
ip -brief addr 2>/dev/null | grep -v '127.0.0.1' \
  || ifconfig 2>/dev/null | grep -E "^[a-z]|inet " | grep -v "127.0.0.1" | head -20
echo "=== default route ==="
ip route show default 2>/dev/null || route -n get default 2>/dev/null | grep -E "gateway|interface"
echo "=== connectivity ==="
if ping -c 2 -W 3 1.1.1.1 >/dev/null 2>&1 || ping -c 2 -t 3 1.1.1.1 >/dev/null 2>&1; then
  echo "online (1.1.1.1 reachable)"
else
  echo "no connectivity"
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
# Usage from Cowork: call_remote("scripts/git_status.sh", args=["/path/to/repo"])
set -euo pipefail
REPO="${1:-$PWD}"
cd "$REPO"
git status --short --branch
GS
cat > "$BRIDGE_ROOT/scripts/list_scripts.sh" <<'LS'
#!/usr/bin/env bash
# list_scripts.sh — list every script the bridge can run, with its one-line description.
# Lets Cowork discover what's available instead of guessing. Args: none.
# Usage from Cowork: call_remote("scripts/list_scripts.sh")
set -uo pipefail
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
echo "=== AVAILABLE BRIDGE SCRIPTS ==="
echo "(call any of these with call_remote(\"scripts/<name>\"))"
echo
shopt -s nullglob
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
# Never prints secret VALUES (only whether they are set). Args: none.
# Usage from Cowork: call_remote("scripts/env_check.sh")
set -uo pipefail
echo "=== BRIDGE ENVIRONMENT ==="
printf '%-13s: %s\n' "PATH" "${PATH:-}"
root="${BRIDGE_ROOT:-$HOME/.cowork-to-code-bridge}"
if [ -d "$root" ]; then
  printf '%-13s: %s  (exists)\n' "BRIDGE_ROOT" "$root"
else
  printf '%-13s: %s  (MISSING)\n' "BRIDGE_ROOT" "$root"
fi
if [ -n "${BRIDGE_TOKEN:-}" ]; then
  printf '%-13s: set\n' "BRIDGE_TOKEN"
elif [ -f "$root/.env" ] && grep -q '^BRIDGE_TOKEN=' "$root/.env" 2>/dev/null; then
  printf '%-13s: set (in .env)\n' "BRIDGE_TOKEN"
else
  printf '%-13s: not set\n' "BRIDGE_TOKEN"
fi
printf '%-13s: %s\n' "CLAUDE_FLAGS" "${CLAUDE_FLAGS:-(not set)}"
printf '%-13s: %s\n' "SHELL" "${SHELL:-unknown}"
printf '%-13s: %s\n' "HOME" "${HOME:-unknown}"
if [ "$(uname)" = "Darwin" ]; then
  printf '%-13s: macOS %s\n' "OS" "$(sw_vers -productVersion 2>/dev/null || echo '?')"
elif [ -r /etc/os-release ]; then
  printf '%-13s: %s\n' "OS" "$(. /etc/os-release && echo "$PRETTY_NAME")"
else
  printf '%-13s: %s\n' "OS" "$(uname -s) $(uname -r)"
fi
claude_path="$(command -v claude 2>/dev/null || true)"
printf '%-13s: %s\n' "claude CLI" "${claude_path:-not found on PATH}"
exit 0
EC
cat > "$BRIDGE_ROOT/scripts/disk_hogs.sh" <<'DH'
#!/usr/bin/env bash
# disk_hogs.sh — biggest files and folders in a directory (default: home).
# Args: [path] [count]   e.g. call_remote("scripts/disk_hogs.sh", args=["~/Downloads","15"])
set -uo pipefail
TARGET="${1:-$HOME}"
COUNT="${2:-15}"
# expand a leading ~ since args arrive as literal strings
case "$TARGET" in "~"|"~/"*) TARGET="$HOME${TARGET#\~}";; esac
if ! [[ "$COUNT" =~ ^[0-9]+$ ]]; then
  echo "count must be a number, got: $COUNT" >&2; exit 1
fi
if [ ! -d "$TARGET" ]; then
  echo "not a directory: $TARGET" >&2; exit 1
fi
echo "=== TOP $COUNT LARGEST ITEMS IN $TARGET ==="
# du over immediate children; sort by size desc; human-readable.
du -sh "$TARGET"/* "$TARGET"/.[!.]* 2>/dev/null \
  | sort -rh \
  | head -n "$COUNT"
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
python3 - "$ID" "$REQUEST" "$TOKEN" >"$TMP" <<'PY'
import json,sys,time
_id,req,tok=sys.argv[1],sys.argv[2],sys.argv[3]
o={"id":_id,"request":req,"ts":time.time(),"from":"claude-code"}
if tok:o["token"]=tok
print(json.dumps(o))
PY
mv "$TMP" "$OUT"; echo "queued request for Cowork: $OUT"
if [[ "$WAIT" -gt 0 ]]; then
  RF="$REPLIES/$ID.json"; dl=$(( $(date +%s)+WAIT ))
  while [[ "$(date +%s)" -lt "$dl" ]]; do [[ -f "$RF" ]] && { echo "=== reply ==="; cat "$RF"; exit 0; }; sleep 2; done
  echo "no reply within ${WAIT}s (Cowork may not be open); request stays queued." >&2
fi
REQCW
chmod +x "$BRIDGE_ROOT/scripts/request_cowork.sh"
mkdir -p "$BRIDGE_ROOT/to_cowork" "$BRIDGE_ROOT/cowork_results"
chmod 700 "$BRIDGE_ROOT/to_cowork" "$BRIDGE_ROOT/cowork_results" 2>/dev/null || true

chmod +x "$BRIDGE_ROOT"/scripts/mac_*.sh "$BRIDGE_ROOT/scripts/port_check.sh" "$BRIDGE_ROOT/scripts/docker_ps.sh" "$BRIDGE_ROOT/scripts/docker_logs.sh" "$BRIDGE_ROOT/scripts/pkg_outdated.sh" "$BRIDGE_ROOT/scripts/git_status.sh" "$BRIDGE_ROOT/scripts/list_scripts.sh" "$BRIDGE_ROOT/scripts/env_check.sh" "$BRIDGE_ROOT/scripts/disk_hogs.sh" "$BRIDGE_ROOT/scripts/open_browser.sh"

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

# ── mcp_proxy.sh ──────────────────────────────────────────────────────────────
cat > "$BRIDGE_ROOT/scripts/mcp_proxy.sh" <<'MCPPROXY'
#!/usr/bin/env bash
# mcp_proxy.sh — relay a single MCP JSON-RPC call to a local stdio MCP server
# and return the response through the bridge queue.
#
# This lets Claude Cowork reach any local stdio MCP server — a database client,
# filesystem tool, or custom CLI — without a public HTTPS tunnel.
# Addresses: anthropics/claude-code#53476, anthropics/claude-code#48909
#
# Usage
# -----
#   mcp_proxy.sh --server <name> --method <method> [--params <json>]
#   mcp_proxy.sh --server <name> --request <full_jsonrpc_json>
#
# Server registry: $BRIDGE_ROOT/mcp_servers.json
# Register servers with: mcp_register.sh
#
# Output (stdout): JSON-RPC response object, always valid JSON.
# Exit code: always 0 — MCP-level errors are reported inside the JSON.
#
# Testability hooks
#   BRIDGE_MCP_REGISTRY  override registry file path
set -uo pipefail

BRIDGE_ROOT="${BRIDGE_ROOT:-$HOME/.cowork-to-code-bridge}"
REGISTRY="${BRIDGE_MCP_REGISTRY:-$BRIDGE_ROOT/mcp_servers.json}"

usage() {
  cat >&2 <<'EOF'
Usage:
  mcp_proxy.sh --server <name> --method <method> [--params <json>]
  mcp_proxy.sh --server <name> --request <full_jsonrpc_json>

Examples:
  mcp_proxy.sh --server filesystem --method tools/list --params '{}'
  mcp_proxy.sh --server postgres   --method tools/call \
    --params '{"name":"query","arguments":{"sql":"SELECT 1"}}'
EOF
  exit 1
}

SERVER_NAME=""
METHOD=""
PARAMS="null"
REQUEST_JSON=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --server)  SERVER_NAME="$2"; shift 2 ;;
    --method)  METHOD="$2";      shift 2 ;;
    --params)  PARAMS="$2";      shift 2 ;;
    --request) REQUEST_JSON="$2";shift 2 ;;
    -h|--help) usage ;;
    *) echo "Unknown argument: $1" >&2; usage ;;
  esac
done

[[ -z "$SERVER_NAME" ]] && { echo "ERROR: --server is required" >&2; usage; }
[[ -z "$METHOD" && -z "$REQUEST_JSON" ]] && { echo "ERROR: --method or --request is required" >&2; usage; }

# ── Python handles the MCP stdio protocol ─────────────────────────────────────
python3 - \
  "$SERVER_NAME" \
  "$METHOD" \
  "$PARAMS" \
  "$REQUEST_JSON" \
  "$REGISTRY" \
<<'PYEOF'
import sys, json, subprocess, time, os

server_name  = sys.argv[1]
method       = sys.argv[2]
params_raw   = sys.argv[3]
request_raw  = sys.argv[4]
registry_path = sys.argv[5]

def die(msg):
    print(json.dumps({"jsonrpc": "2.0", "id": None, "error": {"code": -32000, "message": msg}}))
    sys.exit(0)

if not os.path.exists(registry_path):
    die(f"No server registry at {registry_path}. Run mcp_register.sh first.")

try:
    registry = json.load(open(registry_path))
except Exception as e:
    die(f"Cannot read registry: {e}")

if server_name not in registry:
    known = list(registry.keys())
    die(f"Server '{server_name}' not registered. Known servers: {known}")

cfg = registry[server_name]
cmd = [cfg["command"]] + cfg.get("args", [])
env = {**os.environ, **cfg.get("env", {})}

if request_raw:
    try:
        user_req = json.loads(request_raw)
    except Exception as e:
        die(f"Invalid --request JSON: {e}")
else:
    try:
        params = json.loads(params_raw)
    except Exception as e:
        die(f"Invalid --params JSON: {e}")
    user_req = {
        "jsonrpc": "2.0",
        "id": 2,
        "method": method,
        "params": params if params is not None else {},
    }

req_id = user_req.get("id", 2)

INIT_REQ = json.dumps({
    "jsonrpc": "2.0", "id": 1, "method": "initialize",
    "params": {
        "protocolVersion": "2024-11-05",
        "capabilities": {},
        "clientInfo": {"name": "cowork-bridge-proxy", "version": "1.0"},
    }
})
INIT_NOTIF = json.dumps({"jsonrpc": "2.0", "method": "notifications/initialized"})

try:
    proc = subprocess.Popen(
        cmd, env=env,
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        text=True, bufsize=1,
    )
except FileNotFoundError:
    die(f"Command not found: {cmd[0]}")
except Exception as e:
    die(f"Failed to start server '{server_name}': {e}")

def readline_timeout(stream, timeout=10.0):
    import select
    deadline = time.time() + timeout
    buf = ""
    while time.time() < deadline:
        ready, _, _ = select.select([stream], [], [], 0.05)
        if ready:
            ch = stream.read(1)
            if not ch:
                return None
            if ch == "\n":
                return buf
            buf += ch
    return None

result = None
try:
    proc.stdin.write(INIT_REQ + "\n")
    proc.stdin.flush()

    deadline = time.time() + 10
    while time.time() < deadline:
        line = readline_timeout(proc.stdout, timeout=2.0)
        if line is None:
            break
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
            if msg.get("id") == 1:
                if "error" in msg:
                    result = msg
                break
        except Exception:
            continue
    else:
        result = {"jsonrpc": "2.0", "id": req_id,
                  "error": {"code": -32001, "message": "Initialize timeout"}}

    if result is None:
        proc.stdin.write(INIT_NOTIF + "\n")
        proc.stdin.flush()
        proc.stdin.write(json.dumps(user_req) + "\n")
        proc.stdin.flush()

        deadline = time.time() + 30
        while time.time() < deadline:
            line = readline_timeout(proc.stdout, timeout=2.0)
            if line is None:
                result = {"jsonrpc": "2.0", "id": req_id,
                          "error": {"code": -32002, "message": "Response timeout after 30s"}}
                break
            line = line.strip()
            if not line:
                continue
            try:
                msg = json.loads(line)
                if "id" in msg and msg["id"] == req_id:
                    result = msg
                    break
            except Exception:
                continue
        else:
            result = {"jsonrpc": "2.0", "id": req_id,
                      "error": {"code": -32002, "message": "Response timeout after 30s"}}

except Exception as e:
    result = {"jsonrpc": "2.0", "id": req_id,
              "error": {"code": -32603, "message": f"Protocol error: {e}"}}
finally:
    try:
        proc.stdin.close()
        proc.terminate()
        proc.wait(timeout=3)
    except Exception:
        try:
            proc.kill()
        except Exception:
            pass

if result is None:
    result = {"jsonrpc": "2.0", "id": req_id,
              "error": {"code": -32603, "message": "No response received"}}

print(json.dumps(result))
PYEOF
MCPPROXY
chmod +x "$BRIDGE_ROOT/scripts/mcp_proxy.sh"

# ── mcp_register.sh ───────────────────────────────────────────────────────────
cat > "$BRIDGE_ROOT/scripts/mcp_register.sh" <<'MCPREG'
#!/usr/bin/env bash
# mcp_register.sh — register a local stdio MCP server in the bridge registry.
#
# Usage
# -----
#   mcp_register.sh --name <name> --command <cmd> [--args <json_array>] [--env <json_object>]
#   mcp_register.sh --remove <name>
#   mcp_register.sh --list
#
# Examples
# --------
#   mcp_register.sh --name filesystem \
#     --command npx \
#     --args '["-y","@modelcontextprotocol/server-filesystem","/Users/me/projects"]'
#
#   mcp_register.sh --name postgres \
#     --command uvx \
#     --args '["mcp-server-postgres","postgresql://localhost/mydb"]'
#
# Testability hooks
#   BRIDGE_MCP_REGISTRY  override registry file path
set -uo pipefail

BRIDGE_ROOT="${BRIDGE_ROOT:-$HOME/.cowork-to-code-bridge}"
REGISTRY="${BRIDGE_MCP_REGISTRY:-$BRIDGE_ROOT/mcp_servers.json}"

usage() {
  cat >&2 <<'EOF'
Usage:
  mcp_register.sh --name <name> --command <cmd> [--args <json_array>] [--env <json_object>]
  mcp_register.sh --remove <name>
  mcp_register.sh --list
EOF
  exit 1
}

MODE="register"
NAME=""
COMMAND=""
ARGS_JSON="[]"
ENV_JSON="{}"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --name)    NAME="$2";      shift 2 ;;
    --command) COMMAND="$2";   shift 2 ;;
    --args)    ARGS_JSON="$2"; shift 2 ;;
    --env)     ENV_JSON="$2";  shift 2 ;;
    --remove)  MODE="remove"; NAME="$2"; shift 2 ;;
    --list)    MODE="list";   shift ;;
    -h|--help) usage ;;
    *) echo "Unknown argument: $1" >&2; usage ;;
  esac
done

python3 - "$MODE" "$NAME" "$COMMAND" "$ARGS_JSON" "$ENV_JSON" "$REGISTRY" <<'PYEOF'
import sys, json, os

mode          = sys.argv[1]
name          = sys.argv[2]
command       = sys.argv[3]
args_raw      = sys.argv[4]
env_raw       = sys.argv[5]
registry_path = sys.argv[6]

registry = {}
if os.path.exists(registry_path):
    try:
        registry = json.load(open(registry_path))
    except Exception as e:
        print(f"WARNING: could not parse existing registry, starting fresh: {e}", file=sys.stderr)

if mode == "list":
    if not registry:
        print("No MCP servers registered.")
        print(f"Registry: {registry_path}")
    else:
        print(f"Registered MCP servers ({len(registry)}):")
        for n, cfg in registry.items():
            args_str = " ".join(cfg.get("args", []))
            print(f"  {n:20s}  {cfg['command']} {args_str}")
        print(f"\nRegistry: {registry_path}")
    sys.exit(0)

if mode == "remove":
    if not name:
        print("ERROR: --remove requires a server name", file=sys.stderr); sys.exit(1)
    if name not in registry:
        print(f"ERROR: '{name}' is not registered", file=sys.stderr); sys.exit(1)
    del registry[name]
    os.makedirs(os.path.dirname(registry_path), exist_ok=True)
    with open(registry_path, "w") as f:
        json.dump(registry, f, indent=2)
    print(f"✓ Removed '{name}' from registry")
    sys.exit(0)

if not name:
    print("ERROR: --name is required", file=sys.stderr); sys.exit(1)
if not command:
    print("ERROR: --command is required", file=sys.stderr); sys.exit(1)

try:
    args = json.loads(args_raw)
    if not isinstance(args, list): raise ValueError("--args must be a JSON array")
except Exception as e:
    print(f"ERROR: invalid --args JSON: {e}", file=sys.stderr); sys.exit(1)

try:
    env = json.loads(env_raw)
    if not isinstance(env, dict): raise ValueError("--env must be a JSON object")
except Exception as e:
    print(f"ERROR: invalid --env JSON: {e}", file=sys.stderr); sys.exit(1)

registry[name] = {"command": command, "args": args, "env": env}
os.makedirs(os.path.dirname(registry_path), exist_ok=True)
tmp = registry_path + ".tmp"
with open(tmp, "w") as f:
    json.dump(registry, f, indent=2)
os.replace(tmp, registry_path)

print(f"✓ Registered '{name}'  →  {command} {' '.join(str(a) for a in args)}")
print(f"  Registry: {registry_path}  ({len(registry)} server(s))")
PYEOF
MCPREG
chmod +x "$BRIDGE_ROOT/scripts/mcp_register.sh"

# ── mcp_list_servers.sh ───────────────────────────────────────────────────────
cat > "$BRIDGE_ROOT/scripts/mcp_list_servers.sh" <<'MCPLIST'
#!/usr/bin/env bash
# mcp_list_servers.sh — list all MCP servers registered in the bridge registry.
#
# Usage: mcp_list_servers.sh [--json]
#
# Testability hooks
#   BRIDGE_MCP_REGISTRY  override registry file path
set -uo pipefail

BRIDGE_ROOT="${BRIDGE_ROOT:-$HOME/.cowork-to-code-bridge}"
REGISTRY="${BRIDGE_MCP_REGISTRY:-$BRIDGE_ROOT/mcp_servers.json}"
JSON_OUT=0

while [[ $# -gt 0 ]]; do
  case "$1" in
    --json) JSON_OUT=1; shift ;;
    -h|--help) echo "Usage: mcp_list_servers.sh [--json]" >&2; exit 0 ;;
    *) echo "Unknown argument: $1" >&2; exit 1 ;;
  esac
done

if [[ ! -f "$REGISTRY" ]]; then
  if [[ "$JSON_OUT" -eq 1 ]]; then
    echo '{"servers":{},"count":0,"registry":null}'
  else
    echo "No MCP servers registered."
    echo "Register one with: mcp_register.sh --name <name> --command <cmd>"
  fi
  exit 0
fi

python3 - "$REGISTRY" "$JSON_OUT" <<'PYEOF'
import sys, json

registry_path = sys.argv[1]
json_out      = sys.argv[2] == "1"

try:
    registry = json.load(open(registry_path))
except Exception as e:
    if json_out:
        print(json.dumps({"error": str(e), "servers": {}, "count": 0}))
    else:
        print(f"ERROR reading registry: {e}")
    sys.exit(0)

if json_out:
    print(json.dumps({"servers": registry, "count": len(registry),
                      "registry": registry_path}, indent=2))
    sys.exit(0)

if not registry:
    print("No MCP servers registered.")
    print(f"Registry: {registry_path}")
    sys.exit(0)

print(f"Registered MCP servers ({len(registry)}):\n")
print(f"  {'NAME':<20}  {'COMMAND':<12}  ARGS")
print(f"  {'-'*20}  {'-'*12}  {'-'*30}")
for name, cfg in sorted(registry.items()):
    args_str = " ".join(str(a) for a in cfg.get("args", []))
    if len(args_str) > 40:
        args_str = args_str[:37] + "..."
    print(f"  {name:<20}  {cfg['command']:<12}  {args_str}")
print(f"\nRegistry: {registry_path}")
PYEOF
MCPLIST
chmod +x "$BRIDGE_ROOT/scripts/mcp_list_servers.sh"


c_green "  ✓ scripts installed: ping, hello, run_claude, mac_health, mac_ram, mac_disk, mac_top, mac_network, port_check, docker_ps, docker_logs, pkg_outdated, git_status, list_scripts, env_check, disk_hogs, open_browser, request_cowork, process_kill, mcp_proxy, mcp_register, mcp_list_servers"

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

## Step 3 — quick system checks (no agent)
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
