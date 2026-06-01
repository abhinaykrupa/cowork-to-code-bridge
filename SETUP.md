# SETUP.md

> **Setup is one command on your machine — then one connect line in Cowork per chat.**

As of v0.4.0 the bridge installs a **global Claude skill**, so it loads into
every Cowork session automatically. Cowork still needs permission to mount the
bridge folder once per chat (see the installer's connect line).

## Install (the machine step)

On your Mac, Linux server, or **WSL2 Ubuntu** terminal (not PowerShell):

```bash
curl -fsSL https://raw.githubusercontent.com/abhinaykrupa/cowork-to-code-bridge/main/install.sh | bash
```

That installs the daemon (auto-starts, reboot-safe) **and** the global skill at
`~/.claude/skills/cowork-to-code-bridge/`. Paste the **connect line** it prints
into Cowork once per chat.

**Windows users:** use WSL2 — see [docs/WSL.md](docs/WSL.md).

## Then just talk to Cowork

In any Cowork chat: *"build me an app on my machine"*, *"run my tests"*,
*"check my machine's health"*. The skill triggers, connects, and routes the work to
Claude Code on your computer.

## How it works (for maintainers)

- The skill (`SKILL.md` + `bridge_client.py` + `bridge_env.json`) lives in
  `~/.claude/skills/cowork-to-code-bridge/` and auto-loads in every session.
- `bridge_client.py` is pure stdlib; `bridge_env.json` carries `BRIDGE_ROOT`, so
  the sandbox connects with **no env var, no fetch, no paste, no popups**.
- The canonical skill source is in this repo at
  [`skill/cowork-to-code-bridge/`](./skill/cowork-to-code-bridge/); the installer
  writes it to `~/.claude/skills/`.
- macOS (launchd), Linux (systemd), and WSL2 (systemd in Ubuntu) supported; native Windows not yet.
