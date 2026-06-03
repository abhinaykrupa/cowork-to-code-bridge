# Linux without systemd

Use this guide when the bridge installer detects **no working systemd user bus**
(common in Docker containers, Alpine, and minimal distros). The installer uses a
**manual daemon** instead of `systemctl --user`.

## What the installer does

1. Writes `~/.cowork-to-code-bridge/start-daemon.sh` and
   `~/.cowork-to-code-bridge/lib/daemon_service.sh`
2. Starts the daemon with `setsid` (or `nohup` if `setsid` is missing)
3. Records the PID in `~/.cowork-to-code-bridge/daemon.pid`
4. Adds an **`@reboot` cron** entry when `crontab` is available (skip with
   `BRIDGE_SKIP_CRON=1`)

Logs: `~/.cowork-to-code-bridge/daemon.log` and `daemon.err`.

## Start / stop / status

```bash
# Start (or restart)
bash ~/.cowork-to-code-bridge/start-daemon.sh

# Check process
test -f ~/.cowork-to-code-bridge/daemon.pid && kill -0 "$(cat ~/.cowork-to-code-bridge/daemon.pid)" && echo running

# Logs
tail -f ~/.cowork-to-code-bridge/daemon.log
```

Uninstall removes the cron line, stops the process, and deletes `start-daemon.sh`.

## Docker / one-shot containers

Cron `@reboot` does not help inside ephemeral containers. Start the daemon in your
image `ENTRYPOINT` or wrapper script:

```dockerfile
RUN curl -fsSL https://raw.githubusercontent.com/abhinaykrupa/cowork-to-code-bridge/main/install.sh | bash
# Or after install:
CMD ["bash", "-lc", "$HOME/.cowork-to-code-bridge/start-daemon.sh && exec your-app"]
```

Set `BRIDGE_SKIP_CRON=1` when installing in Docker if you manage startup yourself.

## Compared to systemd

| Feature | systemd --user | Manual path |
|--------|----------------|-------------|
| Auto-restart on crash | Yes | No (re-run `start-daemon.sh`) |
| Survive reboot | Yes (+ linger on servers) | `@reboot` cron when available |
| Survive logout | With linger | Depends on session |

## WSL2

WSL without systemd is **not** covered here — enable systemd in WSL instead. See
[WSL.md](WSL.md) when that doc exists on your branch; otherwise use Microsoft's
WSL systemd instructions.

## Uninstall

Same as other platforms:

```bash
cowork-to-code-bridge-uninstall --yes
```
