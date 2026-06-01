#!/usr/bin/env bash
# Run inside WSL on CI (pwsh -> wsl.exe -d Ubuntu-22.04) or locally:
#   wsl -d Ubuntu -- bash -c 'export GITHUB_WORKSPACE="D:/path/to/repo"; bash scripts/ci-wsl-smoke.sh'
set -euo pipefail
REPO="$(wslpath -a "${GITHUB_WORKSPACE:?GITHUB_WORKSPACE not set}")"
echo "WSL repo path: $REPO"
cd "$REPO"
sed -i 's/\r$//' install.sh scripts/lib/platform.sh
bash -n install.sh
bash -n scripts/lib/platform.sh
grep -qiE 'microsoft|wsl' /proc/version
echo "WSL detected"
