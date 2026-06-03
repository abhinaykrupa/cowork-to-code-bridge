# platform.sh — shared OS/WSL/service-manager detection for install.sh and tests.
# Source this file; do not execute directly.

is_wsl() {
  [[ -n "${WSL_DISTRO_NAME:-}" ]] || grep -qiE 'microsoft|wsl' /proc/version 2>/dev/null
}

has_systemctl() {
  command -v systemctl >/dev/null 2>&1
}

# True when the per-user systemd bus is reachable (not just the systemctl binary).
has_systemd_user_bus() {
  has_systemctl || return 1
  systemctl --user ping >/dev/null 2>&1
}

# Echoes systemd | manual | wsl_need_systemd (when is_wsl and bus unavailable).
# Honors BRIDGE_FORCE_SERVICE_MGR for tests.
linux_service_mgr() {
  local forced="${BRIDGE_FORCE_SERVICE_MGR:-}"
  if [[ -n "$forced" ]]; then
    echo "$forced"
    return 0
  fi
  if has_systemd_user_bus; then
    echo "systemd"
    return 0
  fi
  if is_wsl; then
    echo "wsl_need_systemd"
    return 0
  fi
  echo "manual"
}
