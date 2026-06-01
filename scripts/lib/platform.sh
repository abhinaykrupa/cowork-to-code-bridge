# platform.sh — shared OS/WSL detection for install.sh and tests.
# Source this file; do not execute directly.

is_wsl() {
  [[ -n "${WSL_DISTRO_NAME:-}" ]] || grep -qiE 'microsoft|wsl' /proc/version 2>/dev/null
}
