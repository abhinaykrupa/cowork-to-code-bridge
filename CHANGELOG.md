# Changelog

All notable changes to this project. Format loosely follows
[Keep a Changelog](https://keepachangelog.com/); versions are the `pyproject.toml`
/ `plugin.json` version.

## [Unreleased]

### Added
- **WSL2 (Windows) install path.** Same Linux/systemd installer inside WSL2;
  `install.sh` detects WSL, prints systemd setup hints when needed, redirects
  Git Bash/PowerShell users to WSL, and documents paths/lingering. See
  [docs/WSL.md](docs/WSL.md).
- `.gitattributes` enforces LF on `*.sh` so Windows checkouts work in WSL/bash.

### Changed
- Python discovery probes `python3.14` and generic `python3` (fixes Ubuntu WSL
  distros that only ship `python3` → 3.14).

### Fixed
- **Streamlined the Cowork connection (the real first-run gap).** A live session
  on a fresh machine couldn't auto-connect: Cowork's sandbox doesn't mount the
  bridge folder by default, and the agent had to be walked through it manually.
  Now: (1) the installer writes a `CLAUDE.md` into `BRIDGE_ROOT` so the bridge is
  self-documenting once mounted; (2) the installer's DONE message prints a single
  copy-paste **connect line** for Cowork (asks Claude to mount the folder, read
  the note, confirm `BRIDGE LIVE`) instead of falsely promising "automatic, no
  second step"; (3) the skill now tells the agent to *request the folder mount*
  when it can't see the bridge. Net: install = 1 paste on the machine + 1 paste
  in Cowork (once per chat).

### Added
- `port_check.sh` starter script for checking which process is listening on a
  TCP port, plus installer and skill documentation wiring.

## [0.5.0]

### Added
- **Linux support.** The bridge now runs on Linux via a `systemd --user`
  service (with `loginctl enable-linger` so it survives logout/reboot), in
  addition to macOS launchd. One installer auto-detects the OS and branches the
  service-manager steps; everything else (Python, bridge dir, token, global
  skill, scripts) is shared. The daemon and client were already pure-Python and
  portable. System-info scripts (`mac_health`, `mac_ram`, `mac_top`,
  `mac_network`) are now cross-platform (Linux branches use `free`, `/proc`,
  `ip`, `ps -eo`).
- Uninstall (both shell and Python) tears down the systemd unit on Linux.
- CI now runs the suite on `ubuntu-latest` as well as `macos-latest`.

### Changed
- Pitch broadened from "on your Mac" to "on your own computer (macOS or Linux)".
- `run_claude.sh` CLI install hint leads with the cross-platform official
  installer.

## [0.4.0]

The big simplification: **install as a global skill, one Mac command, nothing in Cowork.**

### Security & hardening
- **Constant-time token comparison** (`hmac.compare_digest`) instead of `!=`,
  removing a token timing side-channel.
- **Command-size guard:** command files larger than 1 MB are rejected before
  being read into memory (DoS/OOM guard).
- **Directory permission hardening:** on startup the daemon tightens
  `BRIDGE_ROOT`, `queue/`, and `scripts/` to `0700` (and warns) if they're
  group/other-accessible — so no other local user can read the token, inject a
  command, or drop a script.
- **Journal auto-rotation:** the append-only journal now rotates to
  `journal.log.old` at 50 MB (warns at 10 MB) instead of growing unbounded.
- Confirmed-not-vulnerable (kept as defense-in-depth): symlink escape from
  `scripts/` (resolve()+relative_to already rejects it); shell injection via
  args (list-form argv, never a shell string).

### Fixed
- Installer now **fetches the canonical `bridge_client.py`** from the repo at
  install time instead of embedding a hand-maintained copy, so the installed
  skill can't ship a stale client (the embedded copy had drifted and lacked
  streaming). Falls back to the installed package's client if offline.
- **Uninstall now removes the global skill.** The Python uninstaller
  (`cowork-to-code-bridge-uninstall`) previously left
  `~/.claude/skills/cowork-to-code-bridge/` behind, so the skill kept loading
  into Cowork sessions after a "complete" uninstall. Both the Python and shell
  uninstallers now remove it.

### Changed
- **Architecture pivot to a global Claude skill.** The Cowork client now installs
  once on the Mac into `~/.claude/skills/cowork-to-code-bridge/` and auto-loads
  into *every* Cowork session — any project, after reboot — with **no fetch, no
  paste, no popups, no `/plugin`.** This replaces the earlier URL-fetch /
  base64-paste flows that tripped Cowork's network-egress permission popups.
- Install is now a single Mac command (`curl … install.sh | bash`); it sets up
  the daemon **and** drops the global skill.

### Added
- **Live progress streaming.** `call_remote_streaming(..., on_progress=cb)` tees a
  running script's output to `progress/<id>.log` and emits it live, so long
  builds/test runs aren't blind. The daemon streams via `Popen`.
- **`run_claude.sh`** — hands a free-form task to a real Claude Code agent on the
  Mac (the headline capability). Resolves the `claude` CLI robustly and
  auto-installs it if missing (`BRIDGE_CLAUDE_AUTOINSTALL=0` to opt out).
- **Mac system-info scripts** — `mac_health`, `mac_ram`, `mac_disk`, `mac_top`,
  `mac_network` for instant "check my Mac" answers.
- **Python auto-install** — if only Apple's stock Python 3.8 is present, the
  installer brings up a modern Python (via Homebrew; `BRIDGE_PYTHON_AUTOINSTALL=0`
  to opt out).
- macOS-only guard in `install.sh` + prominent README banner.
- README "How it works" diagram.

### Removed
- The `/plugin` + marketplace distribution path (didn't work inside Cowork).
- URL-fetch / single-file-fetch / base64-paste onboarding (popup-prone).
- Old `skills/setup` and `skills/run-on-mac` playbooks (superseded by the
  global skill).

## [0.2.0]

### Added
- **Crash resilience (Tier 1 + 2):** append-only journal, in-flight markers, and
  recovery-on-startup so a daemon crash/reboot never silently re-runs a task
  (exit code `-4` marks indeterminate).
- **Idempotency keys:** retries with the same key return the cached result
  instead of re-executing (safe for git push, deploys, etc.).
- Crash-resilience + e2e idempotency test suites.

## [0.1.0]

- Initial file-based bridge: Cowork writes a JSON command to a shared queue, a
  launchd daemon on the Mac runs whitelisted scripts and writes results back.
  Token-authenticated, no network listener.
