#!/usr/bin/env bash
# install.sh — one-shot Mac installer for cowork-to-code-bridge.
#
# Usage (on Mac terminal):
#   curl -fsSL https://raw.githubusercontent.com/abhinaykrupa/cowork-to-code-bridge/main/install.sh | bash
#
# What this does:
#   1. Verifies Python 3.10+ and pip are available.
#   2. pip-installs the cowork-to-code-bridge package (from PyPI if published,
#      else from GitHub main).
#   3. Creates ~/.cowork-to-code-bridge/ with queue/, results/, processed/, scripts/.
#   4. Generates BRIDGE_TOKEN and writes it to ~/.cowork-to-code-bridge/.env.
#   5. Installs the ping.sh and (optionally) hello.sh starter scripts.
#   6. Installs a launchd plist so the daemon auto-starts on login.
#   7. Starts the daemon now.
#   8. Prints the snippet to paste into Cowork.
#
# Re-runnable: skips already-completed steps. Will NOT overwrite an existing token.

set -euo pipefail

REPO="abhinaykrupa/cowork-to-code-bridge"
BRIDGE_ROOT="$HOME/.cowork-to-code-bridge"
PLIST="$HOME/Library/LaunchAgents/dev.cowork-to-code-bridge.daemon.plist"
PACKAGE="cowork-to-code-bridge"
DAEMON_LOG="$BRIDGE_ROOT/daemon.log"
DAEMON_ERR="$BRIDGE_ROOT/daemon.err"

c_green() { printf "\033[0;32m%s\033[0m\n" "$1"; }
c_yellow() { printf "\033[0;33m%s\033[0m\n" "$1"; }
c_red() { printf "\033[0;31m%s\033[0m\n" "$1"; }
step() { printf "\n\033[1;36m==> %s\033[0m\n" "$1"; }

# ─── 1. Preflight ────────────────────────────────────────────────────────────
step "Checking prerequisites"

if ! command -v python3 >/dev/null 2>&1; then
  c_red "  ✗ python3 not found. Install Python 3.10+ first:"
  echo "    brew install python@3.12"
  exit 1
fi

PY_VER=$(python3 -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')
PY_MAJOR=$(echo "$PY_VER" | cut -d. -f1)
PY_MINOR=$(echo "$PY_VER" | cut -d. -f2)
if [[ "$PY_MAJOR" -lt 3 ]] || { [[ "$PY_MAJOR" -eq 3 ]] && [[ "$PY_MINOR" -lt 10 ]]; }; then
  c_red "  ✗ Python $PY_VER is too old. Need 3.10+."
  exit 1
fi
c_green "  ✓ python3 $PY_VER"

if ! command -v pip3 >/dev/null 2>&1 && ! python3 -m pip --version >/dev/null 2>&1; then
  c_red "  ✗ pip not available. Run: python3 -m ensurepip --upgrade"
  exit 1
fi
c_green "  ✓ pip"

# ─── 2. Install package ──────────────────────────────────────────────────────
step "Installing $PACKAGE"

# Try PyPI first; fall back to GitHub main if not yet published.
if python3 -m pip install --user --upgrade "$PACKAGE" 2>/dev/null; then
  c_green "  ✓ installed from PyPI"
else
  c_yellow "  PyPI install failed (package may not be published yet) — falling back to GitHub"
  python3 -m pip install --user --upgrade "git+https://github.com/$REPO.git@main"
  c_green "  ✓ installed from GitHub main"
fi

# ─── 3. Bridge directory layout ──────────────────────────────────────────────
step "Setting up $BRIDGE_ROOT"
mkdir -p "$BRIDGE_ROOT"/{queue,results,processed,scripts}
c_green "  ✓ directories created"

# ─── 4. Token ────────────────────────────────────────────────────────────────
step "Generating bridge token"
ENV_FILE="$BRIDGE_ROOT/.env"
if [[ -f "$ENV_FILE" ]] && grep -q "^BRIDGE_TOKEN=" "$ENV_FILE"; then
  c_yellow "  → BRIDGE_TOKEN already exists in $ENV_FILE — keeping existing token"
  BRIDGE_TOKEN=$(grep "^BRIDGE_TOKEN=" "$ENV_FILE" | head -1 | cut -d= -f2- | tr -d '"' | tr -d "'")
else
  BRIDGE_TOKEN=$(openssl rand -hex 16)
  {
    echo "BRIDGE_TOKEN=$BRIDGE_TOKEN"
    echo "BRIDGE_ROOT=$BRIDGE_ROOT"
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
c_green "  ✓ ping.sh + hello.sh installed in $BRIDGE_ROOT/scripts/"

# ─── 6. launchd plist ────────────────────────────────────────────────────────
step "Installing launchd agent (auto-start on login)"

# Find the daemon entry point. Prefer the installed console script.
DAEMON_CMD=""
if command -v cowork-to-code-bridge-daemon >/dev/null 2>&1; then
  DAEMON_CMD="$(command -v cowork-to-code-bridge-daemon)"
elif python3 -c "import cowork_to_code_bridge.daemon" 2>/dev/null; then
  DAEMON_CMD="$(command -v python3) -m cowork_to_code_bridge.daemon"
else
  c_red "  ✗ cowork-to-code-bridge daemon module not found after install"
  exit 1
fi
c_green "  ✓ daemon entry: $DAEMON_CMD"

mkdir -p "$(dirname "$PLIST")"
cat > "$PLIST" <<PLISTXML
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>dev.cowork-to-code-bridge.daemon</string>
  <key>ProgramArguments</key>
  <array>
PLISTXML
for word in $DAEMON_CMD; do
  echo "    <string>$word</string>" >> "$PLIST"
done
cat >> "$PLIST" <<PLISTXML
  </array>
  <key>EnvironmentVariables</key>
  <dict>
    <key>BRIDGE_ROOT</key><string>$BRIDGE_ROOT</string>
    <key>PATH</key><string>/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin</string>
  </dict>
  <key>RunAtLoad</key><true/>
  <key>KeepAlive</key><true/>
  <key>StandardOutPath</key><string>$DAEMON_LOG</string>
  <key>StandardErrorPath</key><string>$DAEMON_ERR</string>
  <key>WorkingDirectory</key><string>$BRIDGE_ROOT</string>
</dict>
</plist>
PLISTXML

# Reload if already loaded
if launchctl list 2>/dev/null | grep -q "dev.cowork-to-code-bridge.daemon"; then
  c_yellow "  → unloading existing agent"
  launchctl unload "$PLIST" 2>/dev/null || true
fi
launchctl load -w "$PLIST"
sleep 2

# ─── 7. Verify daemon is running ─────────────────────────────────────────────
step "Verifying daemon"
if launchctl list | grep -q "dev.cowork-to-code-bridge.daemon"; then
  c_green "  ✓ daemon registered with launchd"
else
  c_red "  ✗ daemon failed to register"
  echo "  Check: $DAEMON_ERR"
  tail -20 "$DAEMON_ERR" 2>/dev/null || true
  exit 1
fi

# Wait for the daemon to log its first heartbeat
for i in 1 2 3 4 5; do
  if [[ -f "$DAEMON_LOG" ]] && grep -q "daemon up" "$DAEMON_LOG" 2>/dev/null; then
    c_green "  ✓ daemon log shows 'daemon up'"
    break
  fi
  sleep 1
done

if ! grep -q "daemon up" "$DAEMON_LOG" 2>/dev/null; then
  c_yellow "  ! daemon hasn't logged startup yet — checking error log"
  tail -10 "$DAEMON_ERR" 2>/dev/null || true
fi

# ─── 8. Print Cowork paste snippet ───────────────────────────────────────────
step "DONE. Bridge is installed and running."

cat <<DONE

$(c_green "Now go to your Cowork session and paste this single line:")

  Install the cowork-to-code-bridge plugin from https://github.com/$REPO

Cowork will detect the bridge is ready, install the plugin side, and
walk you through the rest.

Manual verification (optional):
  launchctl list | grep cowork-to-code-bridge   # should show the daemon
  cat $ENV_FILE                                 # token + bridge root
  tail -f $DAEMON_LOG                           # live daemon output

Uninstall (one command — undoes everything this installer did):
  cowork-to-code-bridge-uninstall

Or non-interactively:
  cowork-to-code-bridge-uninstall --yes

If 'cowork-to-code-bridge-uninstall' isn't on your PATH:
  curl -fsSL https://raw.githubusercontent.com/$REPO/main/daemon/uninstall.sh | bash

DONE
