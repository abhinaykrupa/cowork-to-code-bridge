# daemon_service.sh — manual (non-systemd) daemon start/stop + @reboot cron.
# Source after setting BRIDGE_ROOT, DAEMON_LOG, DAEMON_ERR, USER_SCRIPTS_DIR, DAEMON_ARGS[].

BRIDGE_CRON_MARKER="# cowork-to-code-bridge @reboot"
BRIDGE_PID_FILE="${BRIDGE_PID_FILE:-${BRIDGE_ROOT:-}/daemon.pid}"

bridge_stop_daemon_manual() {
  local pidfile="$BRIDGE_PID_FILE"
  [[ -n "${BRIDGE_ROOT:-}" ]] || return 0
  if [[ ! -f "$pidfile" ]]; then
    return 0
  fi
  local pid
  pid="$(cat "$pidfile" 2>/dev/null || true)"
  if [[ -n "$pid" ]] && kill -0 "$pid" 2>/dev/null; then
    kill "$pid" 2>/dev/null || true
    local i
    for i in 1 2 3 4 5; do
      kill -0 "$pid" 2>/dev/null || break
      sleep 1
    done
    kill -9 "$pid" 2>/dev/null || true
  fi
  rm -f "$pidfile"
}

bridge_start_daemon_manual() {
  local pidfile="$BRIDGE_PID_FILE"
  [[ -n "${BRIDGE_ROOT:-}" ]] || return 1
  [[ ${#DAEMON_ARGS[@]} -gt 0 ]] || return 1

  bridge_stop_daemon_manual
  mkdir -p "$BRIDGE_ROOT"
  export BRIDGE_ROOT
  export PATH="${USER_SCRIPTS_DIR:-}:$PATH:/usr/local/bin:/usr/bin:/bin"

  local log_out="${DAEMON_LOG:-$BRIDGE_ROOT/daemon.log}"
  local log_err="${DAEMON_ERR:-$BRIDGE_ROOT/daemon.err}"
  touch "$log_out" "$log_err" 2>/dev/null || true

  (
    cd "$BRIDGE_ROOT" || exit 1
    if command -v setsid >/dev/null 2>&1; then
      setsid "${DAEMON_ARGS[@]}" >>"$log_out" 2>>"$log_err" &
    else
      nohup "${DAEMON_ARGS[@]}" >>"$log_out" 2>>"$log_err" &
    fi
    echo $! >"$pidfile"
  )
  sleep 1
  local pid
  pid="$(cat "$pidfile" 2>/dev/null || true)"
  [[ -n "$pid" ]] && kill -0 "$pid" 2>/dev/null
}

bridge_install_cron_reboot() {
  local starter="${1:-$BRIDGE_ROOT/start-daemon.sh}"
  [[ -f "$starter" ]] || return 1
  command -v crontab >/dev/null 2>&1 || return 1
  [[ "${BRIDGE_SKIP_CRON:-0}" == "1" ]] && return 1

  local line="@reboot $starter >>${DAEMON_LOG:-$BRIDGE_ROOT/daemon.log} 2>&1"
  local existing
  existing="$(crontab -l 2>/dev/null || true)"
  if echo "$existing" | grep -Fq "$BRIDGE_CRON_MARKER"; then
    return 0
  fi
  {
    echo "$existing" | grep -v "$BRIDGE_CRON_MARKER" | grep -vF "$starter" || true
    echo "$BRIDGE_CRON_MARKER"
    echo "$line"
  } | crontab -
}

bridge_remove_cron_reboot() {
  command -v crontab >/dev/null 2>&1 || return 0
  local starter="${BRIDGE_ROOT:-}/start-daemon.sh"
  local existing
  existing="$(crontab -l 2>/dev/null || true)"
  [[ -n "$existing" ]] || return 0
  if ! echo "$existing" | grep -Fq "$BRIDGE_CRON_MARKER"; then
    return 0
  fi
  echo "$existing" | grep -v "$BRIDGE_CRON_MARKER" | grep -vF "$starter" | crontab - 2>/dev/null || true
}

bridge_manual_daemon_running() {
  local pidfile="$BRIDGE_PID_FILE"
  [[ -f "$pidfile" ]] || return 1
  local pid
  pid="$(cat "$pidfile" 2>/dev/null || true)"
  [[ -n "$pid" ]] && kill -0 "$pid" 2>/dev/null
}
