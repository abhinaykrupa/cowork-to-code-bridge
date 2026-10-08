#!/usr/bin/env bash
# Install e2e, run INSIDE a clean Linux container by `make e2e` (see Makefile).
# Port of the former .github/workflows/install-e2e.yml: real install.sh + real
# uninstaller, one layout per invocation:  e2e-install.sh default|hardened
#
# A container has no systemd user bus, so this exercises the manual
# (setsid + @reboot cron) path — the one whose starter script the hardened
# layout moves out of the Cowork mount.
set -euo pipefail

LAYOUT="${1:?usage: e2e-install.sh default|hardened}"
REPO="${REPO:-/src}"

export BRIDGE_CLAUDE_AUTOINSTALL=0
export BRIDGE_PYTHON_AUTOINSTALL=0
if [ "$LAYOUT" = hardened ]; then export BRIDGE_HARDENED=1; else export BRIDGE_HARDENED=0; fi

cd "$REPO"
echo "== [$LAYOUT] install"
bash install.sh < /dev/null

echo "== [$LAYOUT] layout is what was asked for"
R="$HOME/.cowork-to-code-bridge"
if [ "$BRIDGE_HARDENED" = 1 ]; then
  S="$HOME/.bridge-scripts"
  test -f "$S/ping.sh" && test -f "$S/.cowork-to-code-bridge-scripts"
  test ! -e "$R/scripts" || { echo "scripts/ created inside the mount"; exit 1; }
  test -f "$HOME/.local/share/cowork-to-code-bridge/start-daemon.sh"
  test -f "$HOME/.local/share/cowork-to-code-bridge/lib/daemon_service.sh"
  test ! -e "$R/start-daemon.sh" && test ! -e "$R/lib"
else
  test -f "$R/scripts/ping.sh" && test -f "$R/start-daemon.sh"
fi

echo "== [$LAYOUT] round-trip through the live daemon"
PATH="$(python3 -c 'import sysconfig;print(sysconfig.get_path("scripts","posix_user"))'):$PATH"
export PATH
cowork-to-code-bridge-selfcheck

if [ "$BRIDGE_HARDENED" = 1 ]; then
  echo "== [$LAYOUT] a script planted in the mount does not run"
  mkdir -p "$R/scripts"
  printf '#!/bin/sh\ntouch %s/PWNED\n' "$HOME" > "$R/scripts/evil.sh"
  chmod +x "$R/scripts/evil.sh"
  BRIDGE_ROOT="$R" python3 - <<'PY'
import os
from cowork_to_code_bridge.client import call_remote
r = call_remote("scripts/evil.sh", [], timeout=20)
print(r)
assert r["exit_code"] == -1, r
assert not os.path.exists(os.path.expanduser("~/PWNED")), "planted script ran"
PY
fi

echo "== [$LAYOUT] uninstall leaves nothing behind"
bash daemon/uninstall.sh --yes
test ! -e "$HOME/.cowork-to-code-bridge"
test ! -e "$HOME/.bridge-scripts"
test ! -e "$HOME/.local/share/cowork-to-code-bridge"
! (crontab -l 2>/dev/null | grep -q start-daemon.sh)

echo "== [$LAYOUT] OK"
