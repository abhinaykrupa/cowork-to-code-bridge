# Windows (WSL2) setup

Use this guide if you run Windows and want to dogfood **cowork-to-code-bridge** on your own machine. The bridge does **not** run in PowerShell, cmd, or Git Bash — it runs inside **WSL2** (Ubuntu or similar) using the same **systemd --user** path as Linux.

Native Windows (Task Scheduler) is not supported yet.

---

## Prerequisites

- Windows 10 (build 19041+) or Windows 11 with **WSL2**
- A Linux distro in WSL (Ubuntu 22.04+ recommended)
- **systemd enabled** in that distro (required)
- Network access for `curl` and `pip`

---

## 1. Enable systemd in WSL

Recent WSL2 distros can run systemd. Without it, `install.sh` cannot register the daemon.

**Inside WSL** (Ubuntu terminal):

```bash
sudo tee /etc/wsl.conf >/dev/null <<'EOF'
[boot]
systemd=true
EOF
```

**In Windows PowerShell** (not WSL):

```powershell
wsl --shutdown
```

Re-open your **Ubuntu** app (or run `wsl`). Verify:

```bash
systemctl --user status
```

You should not see “Failed to connect to bus” errors. If `systemctl` is missing, update WSL (`wsl --update`) and use a current Ubuntu image.

---

## 2. Install the bridge (inside WSL only)

Open the **Ubuntu/WSL** terminal — not PowerShell.

```bash
curl -fsSL https://raw.githubusercontent.com/abhinaykrupa/cowork-to-code-bridge/main/install.sh | bash
```

The installer will:

- Install the Python package under your WSL user
- Create `~/.cowork-to-code-bridge/`
- Register a **systemd --user** service
- Install the global Cowork skill at `~/.claude/skills/cowork-to-code-bridge/`

On success it prints a **connect line** with your real WSL path (e.g. `/home/you/.cowork-to-code-bridge`).

---

## 3. Connect Cowork

Paste the connect line from the installer into a Claude Cowork chat (once per chat). Example:

```text
Connect to my machine via the cowork-to-code bridge at /home/you/.cowork-to-code-bridge — mount that folder, read its CLAUDE.md, and confirm the bridge is live.
```

**Important:** Use the **WSL home path** (`/home/...`), not:

- `C:\Users\...`
- `/mnt/c/Users/...`

Cowork must mount the folder where the **daemon** runs (inside WSL).

Approve the folder mount when prompted. You should see **`BRIDGE LIVE`**.

---

## 4. Verify

```bash
systemctl --user status cowork-to-code-bridge.service
tail -20 ~/.cowork-to-code-bridge/daemon.log
```

Expect `daemon up` in the log.

Optional: run a quick script through the bridge after Cowork is connected, or from another terminal:

```bash
# if ~/.local/bin is on PATH after install
cowork-to-code-bridge-daemon --help 2>/dev/null || true
```

---

## Paths and tools

| What | Typical WSL location |
|------|----------------------|
| Bridge root | `~/.cowork-to-code-bridge` |
| Token / config | `~/.cowork-to-code-bridge/.env` |
| Whitelisted scripts | `~/.cowork-to-code-bridge/scripts/` |
| systemd unit | `~/.config/systemd/user/cowork-to-code-bridge.service` |
| Global Cowork skill | `~/.claude/skills/cowork-to-code-bridge/` |
| pip user scripts | Printed at end of install (often `~/.local/bin`) |
| Claude Code CLI | `~/.local/bin/claude` (after official installer or `run_claude.sh` auto-install) |

### Claude Code CLI on WSL

`run_claude.sh` looks for `claude` on `PATH`, then `~/.local/bin/claude`, and can run:

```bash
curl -fsSL https://claude.ai/install.sh | bash
```

Ensure `~/.local/bin` is on your PATH (the installer may offer to append `~/.bashrc`).

### loginctl lingering

On a normal Linux server, `loginctl enable-linger` keeps the user service running after logout. On WSL2 this often **fails or is limited** — the installer continues anyway. The daemon runs while your WSL session is up; Windows sleep/reboot may require reopening WSL or restarting the service:

```bash
systemctl --user restart cowork-to-code-bridge.service
```

---

## Troubleshooting

### “WSL2 without systemd is not supported”

Follow [section 1](#1-enable-systemd-in-wsl) and run `wsl --shutdown` from PowerShell.

### “Native Windows shell is not supported”

You ran the installer from Git Bash or similar. Use the **Ubuntu/WSL** app instead.

### No Python 3.10+

```bash
sudo apt update && sudo apt install -y python3.12 python3.12-venv
# or: sudo apt install -y python3 python3-venv  # if python3 is already 3.10+
```

Re-run `install.sh`.

### systemd service not active

```bash
systemctl --user status cowork-to-code-bridge.service
journalctl --user -u cowork-to-code-bridge.service -n 30 --no-pager
tail -30 ~/.cowork-to-code-bridge/daemon.err
```

### Cowork says DAEMON NOT REACHABLE but WSL looks fine

- Confirm you mounted the **WSL** path, not a Windows path under `/mnt/c`.
- Confirm the daemon is active (`systemctl --user is-active cowork-to-code-bridge.service`).
- Paste the connect line again in that chat.

### PEP 668 / pip errors

The installer retries with `--break-system-packages` when needed. If it still fails, use a venv or install `python3-venv` and re-run.

---

## Uninstall

```bash
cowork-to-code-bridge-uninstall
# or non-interactive:
cowork-to-code-bridge-uninstall --yes
```

Removes the systemd unit, bridge directory, and global skill.

---

## Manual test checklist (maintainers / issue #3)

Use a **fresh** Ubuntu WSL2 instance with systemd enabled.

- [ ] `grep -qi microsoft /proc/version` (confirms WSL)
- [ ] `systemctl --user` works without bus errors
- [ ] `curl … install.sh | bash` completes with exit 0
- [ ] `systemctl --user is-active cowork-to-code-bridge.service` → `active`
- [ ] `grep -q "daemon up" ~/.cowork-to-code-bridge/daemon.log`
- [ ] Installer prints connect line with `/home/...` path (not `/mnt/c/...`)
- [ ] `cowork-to-code-bridge-uninstall --yes` removes unit and `~/.cowork-to-code-bridge`
- [ ] (Optional) `~/.cowork-to-code-bridge/scripts/run_claude.sh --help` or invoke via bridge; `claude` at `~/.local/bin/claude` after auto-install

Record any extra tweaks needed in this doc or in `install.sh`.
