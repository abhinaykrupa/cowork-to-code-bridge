# cowork-to-code-bridge

**Connect Claude Cowork to Claude Code on your Mac.**

[Claude Cowork](https://claude.ai/cowork) is great at planning and editing, but it runs in a sealed cloud sandbox — it can't reach your actual machine. **Claude Code**, running on your Mac, *can*: it has your shell, your repos, your tools, and full agent abilities.

This bridge connects the two. Cowork hands a task to **Claude Code on your Mac**, a real local agent does the work, and the result comes back to your Cowork chat. So you can say things in Cowork like:

> *"have Claude Code on my Mac run the test suite and fix what's failing"*
> *"tell my Mac's Claude Code to review the diff and push if it's clean"*

…and a Claude Code agent on your machine actually does it.

Because Claude Code can run things on your Mac, a useful **side benefit** is that the same bridge lets Cowork run approved shell scripts directly (builds, git, disk checks) without going through the agent — handy for simple, fixed actions.

**It's idempotent.** Tasks have side effects (edits, commits, pushes), so the bridge caches results by an idempotency key: a retry after a dropped connection returns the cached result instead of running the agent — or the script — twice.

---

## Wait — do you even need this?

**Maybe not.** It depends on *where* you talk to Claude:

| If you use… | Can Claude already run things on your Mac? | Do you need this bridge? |
|---|---|---|
| **The Claude Desktop app on your Mac** | ✅ Yes — it runs right on your machine | **No.** Just ask Claude to run things. Nothing to install. |
| **Cowork in your browser / the cloud** | ❌ No — it runs in a sealed cloud sandbox that can't see your Mac | **Yes** — this bridge is the only way to connect it. |

Not sure which you are? Just paste the [one setup line below](#install-about-2-minutes) into your Claude chat — Claude checks for you and, if you don't need the bridge, it'll tell you so and skip the whole thing.

---

## Is this safe?

Mostly — and the parts that need your attention are spelled out honestly below.

- **Only approved scripts run.** The bridge will only run scripts you've saved in a specific folder on your Mac. Cowork can't run arbitrary commands — it can only trigger the scripts you've enabled.
- **No internet listener.** The bridge doesn't open any ports. Nothing from the outside world can talk to it.
- **Token-protected.** A secret token is generated during install. Only Cowork sessions that know the token can use the bridge.
- **Runs as you.** The bridge runs with your normal user permissions — nothing more, nothing less.
- **Idempotent.** A retry won't double-run a task or script — repeated requests with the same key return the cached result.

**The one thing to understand:** the headline script, `run_claude.sh`, hands a *free-form task* to a Claude Code agent on your Mac. That agent is as capable as Claude Code normally is — it can edit files, run commands, commit, push. That's the power you want, but it means a task from Cowork is acted on by a real agent with your machine's access. If you want to limit that, `run_claude.sh` has a clearly-marked spot to add restrictions (e.g. plan-only mode, or a tool allowlist) — see [the script](./examples/allowed_scripts/run_claude.sh) and [architecture docs](./docs/architecture.md). For fixed, predictable actions, prefer a specific script over `run_claude.sh`.

You can [uninstall it completely with one command](#uninstall) at any time.

---

## Install (about 2 minutes)

**You only paste one thing to start.** Copy the line below and paste it into any Claude Cowork chat:

```
Set up my Mac bridge using https://github.com/abhinaykrupa/cowork-to-code-bridge — follow its SETUP.md
```

That's the whole start. Claude reads the setup guide, installs what it needs inside Cowork, and then **walks you through the one remaining step on your Mac** (it'll tell you exactly where to click and what to paste — about 30 seconds, one time). When it's done, Claude confirms your Mac is connected and you can start asking it to run things.

> **No plugins, no `/plugin` command, no second setup.** `/plugin` doesn't work inside Cowork, so this doesn't use it. Just the one paste above; Claude drives the rest.

### What Claude will have you do (so there are no surprises)

1. **In Cowork** — Claude installs a small helper and checks if your Mac is already connected. If it is, you're instantly done.
2. **On your Mac (one time only)** — if it's not connected yet, Claude will say: *open the Terminal app, paste this one line, press Enter, wait ~30 seconds.* The line is:
   ```bash
   curl -fsSL https://raw.githubusercontent.com/abhinaykrupa/cowork-to-code-bridge/main/install.sh | bash
   ```
   You don't need to understand it — Claude tells you exactly what to do and confirms when it worked.
3. **Back in Cowork** — say "done." Claude verifies the connection and tells you what you can ask for.

After this, **every future Cowork session connects automatically** — no terminal, no re-setup.

> **Don't have Python 3.10+ on your Mac?** Claude will catch this and tell you to run `brew install python@3.12` first. (No Homebrew? Get it at [brew.sh](https://brew.sh) — one paste.)

<details>
<summary>Doing it manually (for developers)</summary>

The Cowork paste-line just tells Claude to follow [`SETUP.md`](./SETUP.md). You can do the same steps by hand:

1. **On your Mac**, run the installer (starts the daemon, survives reboots):
   ```bash
   curl -fsSL https://raw.githubusercontent.com/abhinaykrupa/cowork-to-code-bridge/main/install.sh | bash
   ```
2. **In the Cowork sandbox**, install the client and probe:
   ```bash
   pip install --quiet "git+https://github.com/abhinaykrupa/cowork-to-code-bridge.git@main" && python -c "from cowork_to_code_bridge import daemon_alive; print('BRIDGE LIVE' if daemon_alive(ping_timeout=10) else 'DAEMON NOT REACHABLE')"
   ```
   - `BRIDGE LIVE` → done.
   - `DAEMON NOT REACHABLE` → the client can't find the bridge folder. Set `BRIDGE_ROOT` to the path printed in your Mac's `~/.cowork-to-code-bridge/.env`, then re-probe:
     ```python
     import os
     os.environ["BRIDGE_ROOT"] = "/Users/you/.cowork-to-code-bridge"  # from your Mac's .env
     from cowork_to_code_bridge import daemon_alive
     print(daemon_alive(ping_timeout=10))
     ```
</details>

---

## What can I ask for?

**The main thing: hand a task to Claude Code on your Mac.** The install ships a script called `run_claude.sh` that does exactly this. From Cowork you say something like *"have Claude Code on my Mac run the tests and fix what breaks"* and a real Claude Code agent on your machine carries it out, then reports back. That's the headline feature — Cowork delegating to a full local agent.

The install gives you these to start:

- `run_claude.sh` — **hands a task to Claude Code on your Mac** (the main event)
- `mac_health.sh` — full health snapshot (CPU, memory, disk, battery, top processes)
- `mac_ram.sh` — RAM usage
- `mac_disk.sh` — disk space
- `mac_top.sh` — top processes by CPU and memory
- `mac_network.sh` — network status and connectivity
- `ping.sh` — confirms the bridge works
- `hello.sh` — echoes back a greeting

So from Cowork you can just say **"check my Mac's health"** or **"how much RAM am I using?"** and get real numbers back from your actual machine — the thing Cowork can't do on its own. For anything open-ended ("why is my Mac slow?"), it routes to Claude Code via `run_claude.sh` and the agent figures it out.

**Side benefit — run fixed actions directly.** For simple, repeatable things you don't need a whole agent for (a specific build command, a git push), you can save a small "script" and call it directly. Just ask Claude: *"I want to push my project to GitHub from here."* It writes the script, tells you where to save it, and from then on *"push my project"* just works. You never write code yourself — you're only copying its output into a file.

<details>
<summary>What a script actually looks like (optional — Claude makes these for you)</summary>

A script is just a short text file. A "push to GitHub" one might be saved as `~/.cowork-to-code-bridge/scripts/git_push.sh`:

```bash
#!/usr/bin/env bash
cd "$1"           # first argument = your project folder
git push origin main
```

Make it runnable once with `chmod +x ~/.cowork-to-code-bridge/scripts/git_push.sh`, and you're done.
</details>

### Why scripts, and not just "run any command"?

For your safety. If Claude could run *any* command, a stray instruction could do real damage. By only allowing the actions you've saved as scripts, **you decide what's possible** — Claude can never run anything you haven't explicitly enabled.

---

## Daily use

After setup, just talk to Cowork normally. When something needs your Mac, Claude will use the bridge automatically:

> **You:** "Run my test suite."
> **Claude:** *Runs `~/.cowork-to-code-bridge/scripts/run_tests.sh` on your Mac and shows you the output.*

If you ask for something that doesn't have a script yet:

> **You:** "Deploy to staging."
> **Claude:** "I don't see a `deploy.sh` in your bridge scripts folder. Want me to help you write one?"

---

## Uninstall

One command, undoes everything the installer did:

```bash
cowork-to-code-bridge-uninstall
```

It will ask you to confirm before each step (stopping the daemon, deleting the bridge folder, removing the Python package). Say yes to all to fully reset.

For a no-questions-asked uninstall:

```bash
cowork-to-code-bridge-uninstall --yes
```

### Uninstall options

| Flag | What it does |
|---|---|
| `--yes` / `-y` | Skip every prompt |
| `--keep-data` | Leave your bridge folder (token, scripts, history) but remove the daemon |
| `--keep-package` | Stop the daemon, delete bridge folder, but leave the pip package installed |
| `--bridge-root PATH` | Use a non-default bridge folder location |

### "Command not found"?

If `cowork-to-code-bridge-uninstall` says "command not found", your Mac's PATH doesn't include the pip install location. Use the full path instead:

```bash
~/Library/Python/3.10/bin/cowork-to-code-bridge-uninstall
```

(Adjust `3.10` to whichever Python version you used — `3.11`, `3.12`, etc.)

Or use the remote uninstall:

```bash
curl -fsSL https://raw.githubusercontent.com/abhinaykrupa/cowork-to-code-bridge/main/daemon/uninstall.sh | bash
```

---

## Troubleshooting

### "Cowork says it can't find the bridge."

This usually means the bridge folder location doesn't match between your Mac and the Cowork sandbox. Tell Claude:

> "Show me my bridge folder path."

Claude will check both sides and tell you what to fix (usually setting an environment variable or restarting the daemon).

### "The daemon isn't running."

Check on your Mac:

```bash
launchctl list | grep cowork-to-code-bridge
```

If it shows nothing, the daemon stopped. Restart it:

```bash
launchctl load ~/Library/LaunchAgents/dev.cowork-to-code-bridge.daemon.plist
```

If that fails, re-run the installer — it's safe to re-run and will skip parts that are still set up correctly.

### "I ran the installer but it said Python is too old."

Stock macOS ships an old Python (3.8). You need 3.10+. Easiest fix:

```bash
brew install python@3.12
```

Then re-run the installer.

### "Where do I find the daemon logs?"

```bash
tail -50 ~/.cowork-to-code-bridge/daemon.log
tail -50 ~/.cowork-to-code-bridge/daemon.err   # if there are errors
```

### "How do I know if my Mac is at clean uninstalled state?"

After running uninstall, all of these should return empty or "not found":

```bash
launchctl list | grep cowork-to-code-bridge
ls ~/Library/LaunchAgents/dev.cowork-to-code-bridge.daemon.plist
ls ~/.cowork-to-code-bridge
python3 -c "import cowork_to_code_bridge"
```

---

## What you can build with it

Once the bridge is in place, a single Cowork chat can run a whole project — not just edit files, but actually run, test, and ship them. Paired with Claude Code's built-in skills (like `frontend-design`, `code-review`, `security-review`), one conversation covers the full cycle:

| Step | How the bridge helps |
|---|---|
| **Build & design** | Claude Code writes the code and the UI |
| **Run** | The bridge starts your app and dev servers on your Mac |
| **Test** | The bridge runs your tests and shows you the results |
| **Ship** | The bridge runs `git push`, opens PRs, kicks off deploys |
| **Operate** | The bridge checks logs, disk space, restarts services |

Before the bridge, anything that needed your actual machine meant leaving Cowork for a terminal. Now it all happens in one chat.

---

## How it actually works (for the curious)

```
  Claude Cowork (sandbox)                     Your Mac
  ───────────────────────                     ────────
  writes JSON →   bridge/queue/cmd_*.json  ← polled by daemon (~1s)
                                                ↓ runs script in your whitelist
                                            ~/.cowork-to-code-bridge/scripts/
                                                ↓
  reads JSON ←   bridge/results/cmd_*.json ← daemon writes result
```

Cowork drops a tiny JSON file into a folder. A small program on your Mac (the "daemon") sees the file, runs the requested script, writes the output back. Cowork reads the result. No network connection between the two.

The folder is shared because Cowork mounts your project directory into its sandbox. The bridge piggybacks on that mount.

### Why this and not MCP?

[MCP](https://modelcontextprotocol.io) is great for structured tool calling between Claude and external services. It expects a server process that Claude can connect to. Cowork's sandbox can't reach localhost services on your Mac, so MCP-style tools don't work there.

This bridge takes a different approach: instead of a network connection, it uses **files on a shared folder**. Slower (about 1 second per call vs milliseconds for MCP), but it works from Cowork.

---

## Security details

- **Authentication:** A random 32-character token (`BRIDGE_TOKEN`) is generated during install and stored in `~/.cowork-to-code-bridge/.env` with `chmod 600` (only you can read it). Every command from Cowork includes this token. Wrong token = command rejected.
- **Authorization:** The daemon will *only* run scripts from `~/.cowork-to-code-bridge/scripts/`. The script name has to match a strict pattern (alphanumerics, dots, dashes, underscores). No path tricks (`../`, symlinks out) are allowed.
- **Timeouts:** Every script has a maximum runtime (default 60 seconds, cap 10 minutes). Runaway scripts get killed.
- **Output limits:** Stdout and stderr are truncated to 64 KB each. Massive outputs won't fill your disk.
- **No privilege escalation:** The daemon runs as your normal user. It can't `sudo`, can't read other users' files, can't touch anything you couldn't touch.

The realistic threats this *can't* defend against:

- A malicious script you write yourself. (You wrote it, you own it.)
- Someone who already has write access to your Mac filesystem. (They could write directly to the bridge folder.)
- A bug in the daemon itself. (It's open source — read the code, file issues.)

---

## FAQ

**Q: Does this work on Linux or Windows?**
Right now it's Mac-only because the installer uses `launchd` (macOS's service manager). The core code is cross-platform — adding Linux (systemd) and Windows (Task Scheduler) support is on the roadmap.

**Q: Does it cost anything?**
No. It's free and open source (MIT).

**Q: Do I need to be a developer to use this?**
You need to be comfortable pasting one terminal command. Beyond that, no — Claude does the rest. Adding custom scripts is "knows what a script is" level, not "writes code daily" level.

**Q: Can my Cowork agents from different projects share one bridge?**
Yes — one daemon serves any number of Cowork sessions. The token is shared across sessions on the same Mac.

**Q: Can I have multiple Macs?**
Yes — install the bridge on each Mac separately. Each generates its own token. Cowork sessions automatically use whichever Mac they're connected to.

**Q: Is this an official Anthropic project?**
No. This is a third-party tool that fills a gap Anthropic's Cowork doesn't (yet) cover. If they ship native Cowork ↔ Mac IPC someday, you can uninstall this and switch.

**Q: I'm worried about something running on my Mac without me knowing.**
Three protections:
1. Every command writes to `~/.cowork-to-code-bridge/processed/` so you can audit history.
2. The daemon log shows every command in real time — `tail -f ~/.cowork-to-code-bridge/daemon.log`.
3. You control the script whitelist — Claude can't run anything you haven't put there.

If you want even more conservative: review every Claude suggestion before agreeing to run it.

**Q: What happens if my Mac crashes or reboots while something is running?**
You're covered. The bridge restarts itself automatically, and it's careful not to repeat anything dangerous:
- An action that was *mid-run* when the crash hit is reported as "didn't finish — status unknown" rather than quietly run again. So a half-finished `git push` won't accidentally fire twice.
- An action that had already *finished* keeps its result.

Developers: the full crash-recovery model (the journal, in-flight markers, and the `idempotency_key` option for safe retries) is documented in [`docs/architecture.md`](docs/architecture.md).

---

## Status & contributing

**v0.2.0** — early, but solid. The core works and now survives crashes and reboots without repeating risky actions. A few rough edges remain (mainly the Mac installer's Python detection). Built for myself, open-sourced because it's useful to others.

PRs welcome at [github.com/abhinaykrupa/cowork-to-code-bridge](https://github.com/abhinaykrupa/cowork-to-code-bridge). Issues triaged best-effort. Not "production-grade" until tagged `v1.0.0`.

## License

MIT — see [LICENSE](LICENSE). Use it, fork it, ship it.
