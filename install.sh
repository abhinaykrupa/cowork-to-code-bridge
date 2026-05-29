#!/usr/bin/env bash
# install.sh — one-shot Mac installer for cowork-to-code-bridge.
#
# Usage (on Mac terminal):
#   curl -fsSL https://raw.githubusercontent.com/abhinaykrupa/cowork-to-code-bridge/main/install.sh | bash
#
# What this does:
#   1. Locates a usable Python 3.10+ interpreter (probes python3.13 → 3.10).
#   2. pip-installs the cowork-to-code-bridge package (PyPI, fallback GitHub main).
#   3. Creates ~/.cowork-to-code-bridge/ with queue/, results/, processed/, scripts/.
#   4. Generates BRIDGE_TOKEN and writes it to ~/.cowork-to-code-bridge/.env.
#   5. Installs ping.sh + hello.sh starter scripts.
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

# ─── 1. Preflight: locate a Python 3.10+ interpreter ─────────────────────────
step "Locating Python 3.10+ interpreter"

PY=""
PY_VER=""
for candidate in python3.13 python3.12 python3.11 python3.10; do
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
  for candidate in python3.13 python3.12 python3.11 python3.10; do
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
  if [[ "$AUTO_PY" == "1" ]] && autoinstall_python && rescan_python; then
    installed_ok=1
  fi
  if [[ "$installed_ok" -ne 1 ]]; then
    c_red "  ✗ No Python 3.10+ interpreter available."
    echo
    echo "  Apple's stock /usr/bin/python3 is too old (3.8) and is intentionally"
    echo "  ignored here. Install a modern Python, then re-run this installer:"
    echo
    echo "    # if you have Homebrew:"
    echo "    brew install python@3.12"
    echo
    echo "    # if you don't have Homebrew, install it first (one paste):"
    echo '    /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"'
    echo "    # then: brew install python@3.12"
    echo
    echo "  After install, verify: command -v python3.12"
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
run_claude.sh: the Claude Code CLI is not installed on this Mac, and it could
not be installed automatically. Install it once, then retry:
  brew install claude-code
  # or:  curl -fsSL https://claude.ai/install.sh | bash
(Having the Claude Desktop app is NOT enough — the CLI is a separate install.)
MSG
  exit 127
fi
log "using claude at: $CLAUDE_BIN"
cd "$WORKDIR" || { log "cannot cd to $WORKDIR"; exit 1; }
# To restrict Cowork-originated tasks, edit these flags
# (e.g. --permission-mode plan, or --allowedTools "...").
exec "$CLAUDE_BIN" -p "$TASK" --output-format text
RUNCLAUDE
chmod +x "$BRIDGE_ROOT/scripts/run_claude.sh"

# ─── System-info scripts: let Cowork check the Mac directly ──────────────────
# These answer "check my Mac's health / RAM / disk / processes / network" with
# real data, fast, without invoking the agent. This is the thing Cowork can't
# do on its own — the bridge makes it possible.
cat > "$BRIDGE_ROOT/scripts/mac_health.sh" <<'MH'
#!/usr/bin/env bash
# mac_health.sh — full health snapshot of this Mac. Args: none.
set -u
echo "=== HOST ==="; scutil --get ComputerName 2>/dev/null; hostname; sw_vers 2>/dev/null
echo "=== UPTIME / LOAD ==="; uptime
echo "=== CPU ==="; top -l 1 -n 0 2>/dev/null | grep -E "CPU usage" || echo "n/a"
echo "=== MEMORY (pages) ==="; vm_stat 2>/dev/null | head -6
echo "=== DISK ==="; df -h / 2>/dev/null
echo "=== BATTERY ==="; pmset -g batt 2>/dev/null | head -2 || echo "n/a"
echo "=== TOP 5 PROCS BY CPU ==="; ps -arcwwwxo pid,pcpu,pmem,comm 2>/dev/null | head -6
exit 0
MH
cat > "$BRIDGE_ROOT/scripts/mac_ram.sh" <<'MR'
#!/usr/bin/env bash
# mac_ram.sh — RAM usage summary. Args: none.
set -u
TOTAL=$(sysctl -n hw.memsize 2>/dev/null)
echo "Total RAM: $(( TOTAL / 1024 / 1024 / 1024 )) GB"
echo "--- vm_stat ---"; vm_stat 2>/dev/null
echo "--- memory pressure ---"; memory_pressure 2>/dev/null | tail -3 || echo "n/a"
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
# mac_top.sh — top processes. Args: optional count (default 15).
set -u
N="${1:-15}"
echo "=== by CPU ==="; ps -arcwwwxo pid,pcpu,pmem,comm 2>/dev/null | head -"$((N+1))"
echo "=== by MEM ==="; ps -amcwwwxo pid,pcpu,pmem,comm 2>/dev/null | head -"$((N+1))"
exit 0
MT
cat > "$BRIDGE_ROOT/scripts/mac_network.sh" <<'MN'
#!/usr/bin/env bash
# mac_network.sh — network status. Args: none.
set -u
echo "=== interfaces (active) ==="; ifconfig 2>/dev/null | grep -E "^[a-z]|inet " | grep -v "127.0.0.1" | head -20
echo "=== default route ==="; route -n get default 2>/dev/null | grep -E "gateway|interface"
echo "=== connectivity ==="; ping -c 2 -t 3 1.1.1.1 2>/dev/null | tail -2 || echo "no connectivity"
exit 0
MN
chmod +x "$BRIDGE_ROOT"/scripts/mac_*.sh
c_green "  ✓ scripts installed: ping, hello, run_claude, mac_health, mac_ram, mac_disk, mac_top, mac_network"

# ─── 6. launchd plist ────────────────────────────────────────────────────────
step "Installing launchd agent (auto-start on login)"

# Resolve the daemon entry point to an ABSOLUTE path. Prefer the installed
# console script under the per-user scripts dir (independent of PATH).
DAEMON_ARGS=()
CONSOLE_SCRIPT="$USER_SCRIPTS_DIR/cowork-to-code-bridge-daemon"

if [[ -x "$CONSOLE_SCRIPT" ]]; then
  DAEMON_ARGS=("$CONSOLE_SCRIPT")
elif command -v cowork-to-code-bridge-daemon >/dev/null 2>&1; then
  # On PATH but not under user scripts dir (e.g. system-wide install).
  DAEMON_ARGS=("$(command -v cowork-to-code-bridge-daemon)")
elif "$PY" -c "import cowork_to_code_bridge.daemon" 2>/dev/null; then
  # Fallback: invoke as a module via the resolved Python interpreter.
  DAEMON_ARGS=("$PY" "-m" "cowork_to_code_bridge.daemon")
else
  c_red "  ✗ cowork-to-code-bridge daemon module not found after install"
  exit 1
fi
c_green "  ✓ daemon entry: ${DAEMON_ARGS[*]}"

mkdir -p "$(dirname "$PLIST")"
{
  echo '<?xml version="1.0" encoding="UTF-8"?>'
  echo '<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">'
  echo '<plist version="1.0">'
  echo '<dict>'
  echo '  <key>Label</key><string>dev.cowork-to-code-bridge.daemon</string>'
  echo '  <key>ProgramArguments</key>'
  echo '  <array>'
  for arg in "${DAEMON_ARGS[@]}"; do
    # Escape XML special chars in arg (just in case a path has & < >).
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

# Tear down any prior registration before re-loading.
UID_NUM="$(id -u)"
DOMAIN="gui/$UID_NUM"
LABEL="dev.cowork-to-code-bridge.daemon"

if launchctl print "$DOMAIN/$LABEL" >/dev/null 2>&1; then
  c_yellow "  → bootout existing agent"
  launchctl bootout "$DOMAIN/$LABEL" 2>/dev/null || true
fi
# Legacy load -w cleanup for older installs.
launchctl unload "$PLIST" 2>/dev/null || true

if launchctl bootstrap "$DOMAIN" "$PLIST" 2>/dev/null; then
  c_green "  ✓ launchctl bootstrap $DOMAIN succeeded"
else
  c_yellow "  ! launchctl bootstrap failed — falling back to legacy load -w"
  launchctl load -w "$PLIST"
fi
launchctl enable "$DOMAIN/$LABEL" 2>/dev/null || true
sleep 2

# ─── 7. Verify daemon is running ─────────────────────────────────────────────
step "Verifying daemon"
if launchctl print "$DOMAIN/$LABEL" >/dev/null 2>&1 || \
   launchctl list 2>/dev/null | grep -q "$LABEL"; then
  c_green "  ✓ daemon registered with launchd"
else
  c_red "  ✗ daemon failed to register"
  echo "  Check: $DAEMON_ERR"
  tail -20 "$DAEMON_ERR" 2>/dev/null || true
  exit 1
fi

# Wait up to 20s for the daemon to log its first heartbeat (cold caches are slow).
daemon_up=0
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

ZSHRC="$HOME/.zshrc"
PATH_LINE="export PATH=\"$USER_SCRIPTS_DIR:\$PATH\"  # cowork-to-code-bridge"

if [[ "$path_has_dir" -eq 1 ]]; then
  c_green "  ✓ $USER_SCRIPTS_DIR already on PATH"
else
  c_yellow "  ! $USER_SCRIPTS_DIR is NOT on your PATH."
  echo "    The 'cowork-to-code-bridge-uninstall' and 'cowork-to-code-bridge-daemon'"
  echo "    commands live there. To use them by bare name, add this to ~/.zshrc:"
  echo
  echo "      $PATH_LINE"
  echo

  # Skip the prompt entirely when stdin isn't a TTY (e.g. curl | bash).
  if [[ -t 0 ]]; then
    read -r -p "  Append this line to $ZSHRC now? [y/N] " ans
    if [[ "$ans" =~ ^[Yy]$ ]]; then
      if [[ -f "$ZSHRC" ]] && grep -Fq "$USER_SCRIPTS_DIR" "$ZSHRC"; then
        c_yellow "    (already referenced in $ZSHRC — not appending duplicate)"
      else
        printf '\n# Added by cowork-to-code-bridge installer\n%s\n' "$PATH_LINE" >> "$ZSHRC"
        c_green "  ✓ appended to $ZSHRC — open a new terminal or run: source $ZSHRC"
      fi
    else
      c_yellow "    skipped — add the export line manually when convenient."
    fi
  else
    c_yellow "  (non-interactive shell — not prompting. Add the line above manually.)"
  fi
fi

# ─── 9. Print Cowork paste snippet ───────────────────────────────────────────
step "DONE. Bridge is installed and running."

cat <<DONE

$(c_green "✓ Your Mac side is ready. Now go back to your Cowork chat and say:")

  done

Cowork will detect that this daemon is running and confirm the
connection. After that you can ask it to run things on your Mac in
plain English — no further setup.

(If you came here on your own without starting in Cowork: open any
Cowork chat and paste this one line, then follow what it says —
  Set up my Mac bridge using https://github.com/$REPO — follow its SETUP.md
)

Bridge folder (Cowork may ask for this): $BRIDGE_ROOT

Manual verification (optional):
  launchctl print gui/$UID_NUM/$LABEL   # full agent state
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
