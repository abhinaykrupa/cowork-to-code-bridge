# cowork-to-code-bridge

**Let Claude in your browser run things on your Mac.**

If you use [Claude Cowork](https://claude.ai/cowork), you've probably noticed it can write and edit files in your project, but it can't actually *do* things on your computer — it can't run your build, push to GitHub, install a package, or run a script. That's because Cowork runs in a secure sandbox that can't reach out to your Mac.

This bridge fixes that, safely. Once installed, you can say things in Cowork like:

> *"run `pytest` on my project"*
> *"git push my latest commit"*
> *"check disk space on my Mac"*

…and Claude will actually do them, on your machine, and show you the output.

---

## Is this safe?

Yes — by design.

- **Nothing runs without your approval.** You decide which scripts the bridge is allowed to run by saving them in a specific folder on your Mac. Anything else is rejected.
- **No internet listener.** The bridge doesn't open any ports. Nothing from the outside world can talk to it.
- **Token-protected.** A secret token is generated during install. Only Cowork sessions that know the token can use the bridge.
- **Runs as you.** The bridge runs with your normal user permissions — nothing more, nothing less.

You can [uninstall it completely with one command](#uninstall) at any time.

---

## Install (2 minutes, one paste per side)

### On your Mac (one time)

Open your Terminal app (Spotlight → "Terminal") and paste this single line:

```bash
curl -fsSL https://raw.githubusercontent.com/abhinaykrupa/cowork-to-code-bridge/main/install.sh | bash
```

Press Enter. You'll see status lines scroll by. When it ends with `DONE`, the Mac side is set up. Takes about 30 seconds.

> **Don't have Python 3.10+?** Run `brew install python@3.12` first. If you don't have Homebrew, install it from [brew.sh](https://brew.sh) (one paste, ~5 minutes).

### In Cowork (every time you start a new session — but Claude remembers!)

Open any Cowork session and just say:

> **"Set up the cowork-to-code bridge."**

That's it. Claude will:
1. Add the plugin marketplace if it's not already added (one-time `/plugin marketplace add abhinaykrupa/cowork-bridge-marketplace` — Claude runs this for you)
2. Install the plugin if it's not already installed (one-time `/plugin install cowork-to-code-bridge@cowork-bridge-marketplace` — also driven by Claude)
3. Check if the bridge daemon is running on your Mac
4. If yes → confirm it's working and you're done
5. If no → tell you exactly what to paste in your Mac terminal (which is the install line above)
6. Verify everything works
7. Tell you what you can ask it to do

You only need to set up the Mac side **once per Mac**. After that, every new Cowork session just confirms the bridge is alive and you're good to go.

### Prefer to install manually?

If you'd rather paste the plugin commands yourself in Claude Code:

```
/plugin marketplace add abhinaykrupa/cowork-bridge-marketplace
/plugin install cowork-to-code-bridge@cowork-bridge-marketplace
```

Then run the Mac installer (the curl line above) if you haven't already.

---

## What can I ask Claude to do?

Anything that's a script in your `~/.cowork-to-code-bridge/scripts/` folder.

The install gives you a couple of starter scripts:

- `ping.sh` — just confirms the bridge works
- `hello.sh` — echoes back a greeting

You can add your own. For example, save this on your Mac as `~/.cowork-to-code-bridge/scripts/git_push.sh`:

```bash
#!/usr/bin/env bash
cd "$1"           # first argument = repo path
git push origin main
```

Then make it runnable:

```bash
chmod +x ~/.cowork-to-code-bridge/scripts/git_push.sh
```

Now in Cowork you can say:

> *"push my AAQuant repo to GitHub"*

And Claude will run that script with your repo path.

### Why scripts and not arbitrary commands?

For your safety. If Claude could run any command, an unexpected prompt could do real damage. Forcing every action through a script you wrote yourself means **you decide what's possible** — Claude can only do things you've explicitly enabled.

> **Tip:** Ask Claude to help you write the script. It can draft it; you save it to your Mac yourself.

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

## How it actually works (for the curious)

```
  Cowork sandbox (browser)                    Your Mac
  ────────────────────────                    ────────
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

---

## Status & contributing

**v0.1.0** — early. Functional but rough edges (especially the Mac installer's Python discovery). Built for myself, open-sourced because it's useful to others.

PRs welcome at [github.com/abhinaykrupa/cowork-to-code-bridge](https://github.com/abhinaykrupa/cowork-to-code-bridge). Issues triaged best-effort. Not "production-grade" until tagged `v1.0.0`.

## License

MIT — see [LICENSE](LICENSE). Use it, fork it, ship it.
