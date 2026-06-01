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
DAEMON_LOG="$BRIDGE_ROOT/daemon.log"
DAEMON_ERR="$BRIDGE_ROOT/daemon.err"

c_green()  { printf "\033[0;32m%s\033[0m\n" "$1"; }
c_yellow() { printf "\033[0;33m%s\033[0m\n" "$1"; }
c_red()    { printf "\033[0;31m%s\033[0m\n" "$1"; }
step()     { printf "\n\033[1;36m==> %s\033[0m\n" "$1"; }

# ─── 0. Preflight: detect OS / service manager ───────────────────────────────
# macOS uses launchd; Linux and WSL2 use systemd --user. We branch the
# service-manager steps on $OS; everything else (Python, bridge dir, token,
# scripts, the global skill) is shared.
WSL_DOC="https://github.com/abhinaykrupa/cowork-to-code-bridge/blob/main/docs/WSL.md"

# Canonical copy also lives in scripts/lib/platform.sh (for tests).
is_wsl() {
  [[ -n "${WSL_DISTRO_NAME:-}" ]] || grep -qiE 'microsoft|wsl' /proc/version 2>/dev/null
}
_INSTALL_DIR="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" 2>/dev/null && pwd)" || true
if [[ -n "$_INSTALL_DIR" && -f "$_INSTALL_DIR/scripts/lib/platform.sh" ]]; then
  # shellcheck source=scripts/lib/platform.sh
  source "$_INSTALL_DIR/scripts/lib/platform.sh"
fi

OS="$(uname -s)"
IS_WSL=0
if is_wsl; then IS_WSL=1; fi

case "$OS" in
  Darwin)
    SERVICE_MGR="launchd"
    PLATFORM_NOTE="macOS (launchd)"
    ;;
  Linux)
    if command -v systemctl >/dev/null 2>&1; then
      SERVICE_MGR="systemd"
      if [[ "$IS_WSL" -eq 1 ]]; then
        PLATFORM_NOTE="Linux (WSL2, systemd --user)"
      else
        PLATFORM_NOTE="Linux (systemd --user)"
      fi
    elif [[ "$IS_WSL" -eq 1 ]]; then
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
    else
      c_red "✗ Linux without systemd is not yet supported."
      echo "  This installer manages the daemon via 'systemctl --user', which"
      echo "  wasn't found. (Containers/minimal distros may lack it.)"
      echo "  Open an issue if you need a non-systemd Linux path."
      exit 1
    fi
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
    echo "  Supported: macOS (launchd), Linux (systemd), and WSL2 with systemd."
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

if pip_install_user "$PACKAGE" 2>/dev/null; then
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
exec "$CLAUDE_BIN" "${EXTRA_FLAGS[@]}" -p "$TASK" --output-format text
RUNCLAUDE
chmod +x "$BRIDGE_ROOT/scripts/run_claude.sh"

# ─── System-info scripts: let Cowork check the Mac directly ──────────────────
# These answer "check my Mac's health / RAM / disk / processes / network" with
# real data, fast, without invoking the agent. This is the thing Cowork can't
# do on its own — the bridge makes it possible.
cat > "$BRIDGE_ROOT/scripts/mac_health.sh" <<'MH'
#!/usr/bin/env bash
# mac_health.sh — full health snapshot of this machine (macOS or Linux). Args: none.
set -u
echo "=== HOST ==="; hostname
if [ "$(uname -s)" = "Darwin" ]; then sw_vers 2>/dev/null; else (. /etc/os-release 2>/dev/null; echo "${PRETTY_NAME:-$(uname -sr)}"); fi
echo "=== UPTIME / LOAD ==="; uptime
echo "=== CPU ==="
if [ "$(uname -s)" = "Darwin" ]; then top -l 1 -n 0 2>/dev/null | grep -E "CPU usage" || echo n/a
else grep 'cpu ' /proc/stat >/dev/null 2>&1 && echo "load: $(cut -d' ' -f1-3 /proc/loadavg)" || echo n/a; fi
echo "=== MEMORY ==="
if [ "$(uname -s)" = "Darwin" ]; then vm_stat 2>/dev/null | head -6; else free -h 2>/dev/null || cat /proc/meminfo | head -3; fi
echo "=== DISK ==="; df -h / 2>/dev/null
echo "=== TOP 5 PROCS BY CPU ==="; ps -eo pid,pcpu,pmem,comm 2>/dev/null | sort -k2 -rn | head -6
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
chmod +x "$BRIDGE_ROOT"/scripts/mac_*.sh "$BRIDGE_ROOT/scripts/port_check.sh"
c_green "  ✓ scripts installed: ping, hello, run_claude, mac_health, mac_ram, mac_disk, mac_top, mac_network, port_check"

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
— then retry. (macOS, Linux, or WSL2 with systemd; native Windows not supported.)

## Step 2 — hand a task to Claude Code (main use)

\`\`\`python
r = call_remote("scripts/run_claude.sh",
    args=["Build a Flask app with a /health route, install deps, run it", "/Users/<them>/projects/app"],
    timeout=600, idempotency_key="unique-key-per-task")
print(r["exit_code"]); print(r["stdout"])
\`\`\`
Always pass a unique \`idempotency_key\` — Claude Code tasks have side effects, so a
retry must not run twice.

## Step 3 — quick system checks (no agent)
\`call_remote("scripts/mac_health.sh")\` · \`mac_ram.sh\` · \`mac_disk.sh\` · \`mac_top.sh\` · \`mac_network.sh\` · \`port_check.sh\`

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
use call_remote_streaming(..., on_progress=cb).

## Quick checks (no agent)
scripts/mac_health.sh · mac_ram.sh · mac_disk.sh · mac_top.sh · mac_network.sh · port_check.sh <port>

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

else
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
else
  VERIFY_CMD="systemctl --user status cowork-to-code-bridge.service"
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

DONE
