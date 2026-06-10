# cowork-to-code-bridge

[![CI](https://github.com/abhinaykrupa/cowork-to-code-bridge/actions/workflows/ci.yml/badge.svg)](https://github.com/abhinaykrupa/cowork-to-code-bridge/actions/workflows/ci.yml)
[![selfcheck](https://github.com/abhinaykrupa/cowork-to-code-bridge/actions/workflows/ci.yml/badge.svg?label=selfcheck)](https://github.com/abhinaykrupa/cowork-to-code-bridge/actions/workflows/ci.yml)
[![Homebrew](https://img.shields.io/badge/brew-abhinaykrupa%2Ftap-orange?logo=homebrew)](https://github.com/abhinaykrupa/homebrew-tap)
[![Python](https://img.shields.io/badge/python-%3E%3D3.10-blue?logo=python&logoColor=white)](https://pypi.org/project/cowork-to-code-bridge/)
[![PyPI](https://img.shields.io/pypi/v/cowork-to-code-bridge)](https://pypi.org/project/cowork-to-code-bridge/)
[![PyPI downloads](https://img.shields.io/pypi/dm/cowork-to-code-bridge)](https://pypi.org/project/cowork-to-code-bridge/)
[![Stars](https://img.shields.io/github/stars/abhinaykrupa/cowork-to-code-bridge?style=social)](https://github.com/abhinaykrupa/cowork-to-code-bridge/stargazers)
[![Release](https://img.shields.io/github/v/release/abhinaykrupa/cowork-to-code-bridge?display_name=tag)](https://github.com/abhinaykrupa/cowork-to-code-bridge/releases)
[![Downloads](https://img.shields.io/github/downloads/abhinaykrupa/cowork-to-code-bridge/total?logo=github)](https://github.com/abhinaykrupa/cowork-to-code-bridge/releases)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://github.com/abhinaykrupa/cowork-to-code-bridge/blob/main/LICENSE)
[![Platform](https://img.shields.io/badge/platform-macOS%20%7C%20Linux%20%7C%20WSL2-lightgrey)](#)

> ⭐ **If this saves you time, [a star helps others find it](https://github.com/abhinaykrupa/cowork-to-code-bridge/stargazers).** It takes one click.

**Let Claude run code on your real machine — safely — from any Claude chat. Integrate with Hermes, cron jobs, CI/CD, or any daemon.**

<p align="center">
  <img src="https://raw.githubusercontent.com/abhinaykrupa/cowork-to-code-bridge/main/docs/demo.svg" alt="Cowork hands a 'build me a Flask app' task to Claude Code on your machine; it scaffolds, installs, runs, and verifies it — then reports back." width="100%">
</p>

> 🖥️ **macOS, Linux, and WSL2.** Works on your Mac (launchd), a Linux box/server (systemd, or a [manual path](https://github.com/abhinaykrupa/cowork-to-code-bridge/blob/main/docs/LINUX-NO-SYSTEMD.md) for containers/minimal distros), or **Windows via WSL2** (systemd in Ubuntu). Native Windows isn't supported yet — see [docs/WSL.md](https://github.com/abhinaykrupa/cowork-to-code-bridge/blob/main/docs/WSL.md).

[Claude Cowork](https://claude.ai/cowork) (and Claude in your browser) is great at planning and editing, but it runs in a sealed cloud sandbox — it can't reach your actual machine. **Claude Code**, running on your computer, *can*: it has your shell, your repos, your tools, and full agent abilities.

This bridge connects the two. Cowork hands a task to **Claude Code on your machine**, a real local agent does the work, and the result streams back to your chat. So you can say things like:

> *"build me a web app on my machine, install deps, and run it"*
> *"run the test suite and fix what's failing"*
> *"review the diff and push if it's clean"*

…and a Claude Code agent on your computer actually does it.

Because Claude Code can run things on your Mac, a useful **side benefit** is that the same bridge lets Cowork run approved shell scripts directly (builds, git, disk checks) without going through the agent — handy for simple, fixed actions.

**It's idempotent.** Tasks have side effects (edits, commits, pushes), so the bridge caches results by an idempotency key: a retry after a dropped connection returns the cached result instead of running the agent — or the script — twice.

---

> **Is it safe to let a cloud chat reach my machine?** Short answer: the bridge
> opens **no network ports**, never uses `sudo`, runs **only scripts you approve**,
> is gated by a secret token, and uninstalls completely with one command. Full
> threat model in **[SECURITY.md](https://github.com/abhinaykrupa/cowork-to-code-bridge/blob/main/SECURITY.md)**.

## Install — two pastes total

**Step 1 — on your machine (once).** Open Terminal (`Cmd + Space` → **Terminal**), paste this, press Enter:

```bash
# Homebrew (macOS recommended)
brew tap abhinaykrupa/tap
brew install cowork-to-code-bridge
brew services start cowork-to-code-bridge

# or: one-liner (macOS + Linux + WSL2)
curl -fsSL https://raw.githubusercontent.com/abhinaykrupa/cowork-to-code-bridge/main/install.sh | bash
```

**macOS (Homebrew)** — once the [maintainer tap](https://github.com/abhinaykrupa/cowork-to-code-bridge/blob/main/docs/HOMEBREW.md) is published: `brew install abhinaykrupa/tap/cowork-to-code-bridge`. See **[docs/HOMEBREW.md](https://github.com/abhinaykrupa/cowork-to-code-bridge/blob/main/docs/HOMEBREW.md)** for details and the demo tap.

Wait ~30 seconds. It installs a small background helper (auto-restarts, reboot-safe) and a Claude skill. When it finishes it prints a **connect line with your real path filled in** — copy that exact line, or use the template below.

Once the package is on PyPI, the installer prefers `pip install` from there (faster than the GitHub fallback).

<details>
<summary>Developers / pip (package only — not the full bridge setup)</summary>

```bash
pip install cowork-to-code-bridge
cowork-to-code-bridge-selfcheck
```

This installs the Python package and console scripts (`cowork-to-code-bridge-daemon`,
`-uninstall`, `-selfcheck`). It does **not** set up launchd/systemd, the Cowork
skill, whitelisted scripts, or a bridge token. For the full bridge, use the
`curl | bash` one-liner above (or Homebrew on macOS).

Maintainers publishing releases: see **[docs/RELEASING.md](docs/RELEASING.md)**.

</details>

**Step 2 — in Cowork (once per chat).** Paste the connect line into any Claude Cowork chat (replace the path with the one the installer printed):

```text
Connect to my machine via the cowork-to-code bridge at ~/.cowork-to-code-bridge — mount that folder, read its CLAUDE.md, and confirm the bridge is live.
```

Claude asks for permission to see that folder (**approve it**), reads the instructions inside, and confirms **`BRIDGE LIVE`**. Now, in that chat, just talk:

> *"build me a small web app on my machine"* · *"run my tests and fix what fails"* · *"check my machine's health"* · *"git push my project"*

Claude hands the work to Claude Code on your machine and brings the result back.

> **Why the second paste?** Cowork's sandbox can't see your machine until you grant it access to the bridge folder — that's a one-time permission per chat, and the connect line is what triggers it. No downloads, no `/plugin`, no popups beyond that single folder-access approval. (Once a chat is connected it stays connected; a brand-new chat needs the line again.)

> **Don't have Python 3.10+?** On **macOS**, the installer can install Python via Homebrew (and Homebrew first if needed). On **Linux/WSL**, use your distro packages (`apt install python3.12`, etc.). Skip auto-install on Mac with `BRIDGE_PYTHON_AUTOINSTALL=0`.

### Windows (WSL2)

On Windows, install **inside WSL2** (Ubuntu), not PowerShell or Git Bash. You need [systemd enabled in WSL](https://github.com/abhinaykrupa/cowork-to-code-bridge/blob/main/docs/WSL.md#1-enable-systemd-in-wsl), then the same one-liner in your Ubuntu terminal. Full walkthrough: **[docs/WSL.md](https://github.com/abhinaykrupa/cowork-to-code-bridge/blob/main/docs/WSL.md)**.

<details>
<summary>What the installer puts where (for the curious / developers)</summary>

- **Daemon** → runs from `~/.cowork-to-code-bridge/`, managed by launchd (macOS), systemd --user (Linux), or a [manual path](https://github.com/abhinaykrupa/cowork-to-code-bridge/blob/main/docs/LINUX-NO-SYSTEMD.md) when systemd is unavailable.
- **Global skill** → `~/.claude/skills/cowork-to-code-bridge/` (SKILL.md + `bridge_client.py` + a `bridge_env.json` pointing at `BRIDGE_ROOT`).
- **Whitelisted scripts** → `~/.cowork-to-code-bridge/scripts/` (`run_claude.sh`, `mac_health.sh`, …).
- **`CLAUDE.md`** → written into `~/.cowork-to-code-bridge/` so the bridge self-documents once a Cowork session mounts the folder.

The Cowork side imports the colocated `bridge_client.py` — pure stdlib, no pip, no network fetch.
</details>

---

## How it works

Cowork can't reach your machine directly (it's sandboxed). So the bridge uses a folder both sides can see: Cowork **writes** a task into it, a small helper on your machine **runs** it (handing real work to Claude Code), and **writes the result back**. No open ports, no servers, no network calls between them.

```
   ☁️  CLAUDE COWORK (cloud sandbox)                 🖥️  YOUR MACHINE (Mac/Linux)
   ───────────────────────────────                  ─────────────────────────────────
   You: "build me an app"                            launchd/systemd keeps the daemon
            │                                         running (auto-starts at login,
            ▼                                          survives reboots)
   cowork-to-code-bridge skill                                    ▲
   (auto-loaded in every session)                                 │
            │                                                      │
            │ 1. write task ─────────►  ┌───────────────────────┐  │
            │                           │   shared bridge folder │  │
            │                           │   queue/   ◄───────────┼──┘ 2. daemon picks
            │                           │   results/ ────────────┼──┐    up the task
            │ 4. read result ◄──────────│   progress/ (live log) │  │
            │    (+ live progress)      └───────────────────────┘  │ 3. runs it:
            ▼                                                       │    run_claude.sh
   Claude shows you the output                                     ▼    → Claude Code
                                                          a REAL Claude Code agent
                                                          builds / tests / commits,
                                                          streaming output as it goes
```

**The four moving parts:**

| Part | Where | What it does |
|---|---|---|
| **Skill** | Every Cowork session (`~/.claude/skills/`) | Auto-loaded; turns your plain-English request into a task and reads back the result. No install inside Cowork. |
| **Shared folder** | `~/.cowork-to-code-bridge/` | The hand-off point: `queue/` (tasks in), `results/` (answers out), `progress/` (live output for long jobs). |
| **Daemon** | Your machine, run by `launchd` (macOS), `systemd --user` (Linux), or manual start (containers) | Watches `queue/`, runs only whitelisted scripts, writes results. Auto-restarts on reboot when the service manager supports it. |
| **`run_claude.sh`** | Your machine | Hands the task to a real **Claude Code** agent — that's what builds the actual product. |

**Why it's safe:** no network listener (nothing can connect in), a secret token gates every request, and the daemon only runs scripts you've approved. **Why it survives crashes:** every task is journaled and marked in-flight; a reboot mid-task is detected and never silently re-run (idempotency keys make retries safe).

---

## Wait — do you even need this?

**Maybe not.** It depends on *where* you talk to Claude:

| If you use… | Can Claude already run things on your Mac? | Do you need this bridge? |
|---|---|---|
| **The Claude Desktop app on your Mac** | ✅ Yes — it runs right on your machine | **No.** Just ask Claude to run things. Nothing to install. |
| **Cowork in your browser / the cloud** | ❌ No — it runs in a sealed cloud sandbox that can't see your Mac | **Yes** — this bridge is the only way to connect it. |

Not sure which you are? Just follow the [two-paste install above](#install--two-pastes-total) — when you paste the connect line into Cowork, Claude checks for you, and if you don't need the bridge it'll tell you so and skip it.

---

## How it compares

There are several ways to get Claude near a machine. Here's where this bridge fits,
honestly — including the cases where you **don't** need it:

| Approach | Runs on | Reaches your real shell / files | Always-on / survives reboot | Best when |
|---|---|---|---|---|
| **Cowork alone** | Local VM (sandboxed) | ❌ Only a granted workspace folder; sandbox is hypervisor-isolated from the host | n/a | You don't need the host machine at all |
| **Claude Code on the web** (`--remote`) | Anthropic cloud | ❌ Only your cloned repo; no host access | ❌ Cloud session | The task is fully inside a GitHub repo |
| **Remote Control** (`--remote-control`) | **Your machine** | ✅ Full local shell/files | ⚠️ Ends when `claude` stops; ~10-min offline timeout; needs paid claude.ai login | You're driving a *live* local session from your phone/web and keep it running |
| **MCP (local server)** | Your machine | ✅ Within the server you build | ⚠️ You run/maintain the server | You want structured tool calls, not a full agent task — **but Cowork's sandbox can't reach a localhost MCP server** |
| **SSH / self-hosted runner** | Your machine | ✅ Full | ✅ If you set it up | You're comfortable running and securing your own listener |
| **this bridge** | **Your machine** | ✅ Full (a real Claude Code agent) | ✅ Daemon auto-restarts, reboot-safe, no session to keep alive | You want to drive your machine **from a Cowork chat**, hands-off, no open port, idempotent |

**The honest takeaway:** the closest first-party option is **Remote Control** — same
security shape (local execution, outbound-only, no inbound port). The bridge differs
in that it's driven *from a Cowork chat*, needs no live session kept running (a
background daemon survives reboots), is idempotent across dropped connections, and
runs approved scripts directly when you don't need a full agent. If you live in a
live Claude Code terminal session, Remote Control may suit you better — use the right
tool for where you actually talk to Claude.

> Feature facts above reflect Anthropic's published docs as of mid-2026
> (`code.claude.com/docs`). They evolve — corrections welcome via issue or PR.

---

## Is this safe?

Mostly — and the parts that need your attention are spelled out honestly below.

- **Only approved scripts run.** The bridge will only run scripts you've saved in a specific folder on your Mac. Cowork can't run arbitrary commands — it can only trigger the scripts you've enabled.
- **No internet listener.** The bridge doesn't open any ports. Nothing from the outside world can talk to it.
- **Token-protected.** A secret token is generated during install. Only Cowork sessions that know the token can use the bridge.
- **Runs as you.** The bridge runs with your normal user permissions — nothing more, nothing less.
- **Idempotent.** A retry won't double-run a task or script — repeated requests with the same key return the cached result.

**The one thing to understand:** the headline script, `run_claude.sh`, hands a *free-form task* to a Claude Code agent on your Mac. That agent is as capable as Claude Code normally is — it can edit files, run commands, commit, push. That's the power you want, but it means a task from Cowork is acted on by a real agent with your machine's access. If you want to limit that, `run_claude.sh` has a clearly-marked spot to add restrictions (e.g. plan-only mode, or a tool allowlist) — see [the script](https://github.com/abhinaykrupa/cowork-to-code-bridge/blob/main/examples/allowed_scripts/run_claude.sh) and [architecture docs](https://github.com/abhinaykrupa/cowork-to-code-bridge/blob/main/docs/architecture.md). For fixed, predictable actions, prefer a specific script over `run_claude.sh`.

**Optional: plan approval gate.** If you want a programmatic last line of defense before any task runs, copy [`examples/allowed_scripts/approve_plan.sh`](https://github.com/abhinaykrupa/cowork-to-code-bridge/blob/main/examples/allowed_scripts/approve_plan.sh) to `~/.cowork-to-code-bridge/scripts/approve_plan.sh` and make it executable. When Cowork submits a task with a `plan` field, the bridge runs your hook first — exit 0 to proceed, exit 2 to reject (the hook's message is returned to Cowork). The hook can block schema migrations, send you a phone notification, or require an interactive keystroke. If the file doesn't exist, the plan field is silently ignored and nothing changes.

**Requirement for the Claude Code path:** `run_claude.sh` needs the Claude Code **CLI** (`claude`) installed on your Mac. **The Claude Desktop app alone is not enough** — it bundles its own copy but doesn't expose a `claude` command. If the CLI is missing, `run_claude.sh` tries to install it on the fly (`brew install claude-code`, or the official installer) and then proceeds; if that fails it returns the exact one-line install command. To turn off auto-install (and just get the install instructions instead), set `BRIDGE_CLAUDE_AUTOINSTALL=0`. The system-info scripts (`mac_health.sh`, etc.) don't need the CLI at all.

You can [uninstall it completely with one command](#uninstall) at any time.

---

## What can I ask for?

**The main thing: hand a task to Claude Code on your Mac.** The install ships a script called `run_claude.sh` that does exactly this. From Cowork you say something like *"have Claude Code on my Mac run the tests and fix what breaks"* and a real Claude Code agent on your machine carries it out, then reports back. That's the headline feature — Cowork delegating to a full local agent.

For copy-paste examples that map Cowork requests to the bundled scripts, see
**[Cowork Recipes](https://github.com/abhinaykrupa/cowork-to-code-bridge/blob/main/docs/RECIPES.md)**.

The install gives you these to start:

- `run_claude.sh` — **hands a task to Claude Code on your Mac** (the main event)
- `mac_health.sh` — full health snapshot (CPU, memory, disk, battery, top processes)
- `mac_ram.sh` — RAM usage (add `--json` for structured `{total,free,used}_bytes` output)
- `mac_disk.sh` — disk space
- `mac_top.sh` — top processes by CPU and memory
- `mac_network.sh` — network status and connectivity
- `port_check.sh` — shows what is listening on a TCP port
- `docker_ps.sh` — lists running Docker containers
- `docker_logs.sh` — tail a container's logs (optional line count, default 50)
- `git_status.sh` — `git status --short --branch` in any repo directory (pass the path as an argument)
- `pkg_outdated.sh` — lists outdated packages (brew on macOS; apt/dnf/yum/pacman on Linux)
- `list_scripts.sh` — lists every script the bridge can run, with descriptions (so Cowork can discover what's available); pass `--json` for a machine-parseable catalog
- `env_check.sh` — shows key environment values (PATH, `BRIDGE_ROOT`, `CLAUDE_FLAGS`, `claude` CLI) without leaking your token
- `disk_hogs.sh` — biggest files/folders in a path (pass a directory and an optional count)
- `open_browser.sh` — opens an `http(s)`/localhost URL in your default browser (handy after a local dev server starts)
- `request_cowork.sh` — hand a request the *other* way: from Claude Code on your machine to a Cowork session (async inbox)
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

## Verify your install

Run this any time to confirm the bridge is healthy:

```bash
cowork-to-code-bridge-selfcheck
```

It checks six things and prints a clear PASS/FAIL for each:

```
cowork-to-code-bridge selfcheck
  bridge root : /Users/you/.cowork-to-code-bridge
  platform    : Darwin arm64

  Bridge root        [PASS]  /Users/you/.cowork-to-code-bridge
  Bridge token       [PASS]  set in /Users/you/.cowork-to-code-bridge/.env
  Daemon registered  [PASS]  launchd: running (pid 1234)
  Skill installed    [PASS]  /Users/you/.claude/skills/cowork-to-code-bridge
  Ping round-trip    [PASS]  ping round-trip OK
  claude CLI         [PASS]  /opt/homebrew/bin/claude

  All checks passed. Bridge is healthy.
```

Exits 0 if all pass, 1 if any fail — safe to use in scripts or bug reports.

---

## Uninstall

One command, undoes everything the installer did:

```bash
cowork-to-code-bridge-uninstall
```

It undoes everything the installer set up: stops and removes the background daemon, removes the global Cowork skill (so it stops loading into your Cowork sessions), deletes the bridge folder (token, scripts, history), and uninstalls the Python package. It asks before each destructive step — say yes to all to fully reset.

> **No network needed, no Cowork step.** Uninstall is entirely on your Mac. Once the skill is removed, your Cowork chats simply won't have the bridge anymore — nothing to clean up there.

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

## Ecosystem Integration Capabilities

cowork-to-code-bridge is designed as a universal **MCP-based local code execution backend**, seamlessly integrating with major agent frameworks and development platforms across the broader ecosystem:

**Agent Frameworks & Orchestration**
- **LangGraph** — Graph-based workflow integration enabling local code execution nodes
- **LangChain** — MCP client integration for agent-based code generation and validation
- **AutoGen** — Code execution configuration with multi-language support via MCP
- **CrewAI** — Production crew workflows with safe local code execution patterns
- **Pydantic AI** — Structured code execution with validation via agent tools
- **n8n** — Secure local code execution steps for workflow automation
- **Dify** — Local code execution patterns for autonomous agent workflows
- **Langflow** — Visual workflow builder integration with code execution components
- **Mastra, Upsonic, AutoGPT, OpenAI Swarm** — General-purpose agent infrastructure

**Model Context Protocol (MCP) Ecosystem**
- **Official MCP Registry** — Canonical server listing for all MCP clients
- **MCP Quickstart Resources** — Reference implementation for stateful MCP server patterns
- **MCP Specification** — Documentation of async escalation patterns for long-running operations
- **GitHub's MCP Server** — Companion pattern enabling GitHub data discovery + local code execution

**Developer-First Platforms**
- **Cursor, VS Code, and IDE Extensions** — MCP provider for Claude Code within editor environments
- **OpenAI Assistants** — Code execution backend for assistant-based workflows

**Infrastructure & CI/CD**
- **GitHub Actions & Agentic Workflows** — Self-hosted runner integration for local execution
- **DevOps Agent Frameworks** — Infrastructure automation with local code execution context
- **Kubernetes & Container-Native Workflows** — MCP server deployment patterns

**Community & Visibility**
- **Curated Registries** — awesome-mcp-servers, awesome-ai-agents, awesome-mcp-clients, 500-AI-Agents-Projects
- **Agent Ecosystem Directories** — Listed in major community indexes for agent infrastructure and execution backends

**Integration Approach**

Each integration leverages the bridge's core capabilities:
- Zero external API key management (uses local Claude Code subscription)
- Full repository and environment context access
- JSONRPC 2.0 MCP standard protocol
- File-based queue with token authentication
- Async escalation patterns for non-blocking task delegation
- Idempotent request handling with unique operation tracking

The bridge is framework-agnostic and protocol-standard, enabling any MCP-aware tool to escalate code execution tasks while maintaining local context, security, and cost predictability. For integration guidance specific to your framework, see **[docs/EXTERNAL_AGENT_INTEGRATION.md](https://github.com/abhinaykrupa/cowork-to-code-bridge/blob/main/docs/EXTERNAL_AGENT_INTEGRATION.md)** and **[docs/MCP_SERVER_IMPLEMENTATION.md](https://github.com/abhinaykrupa/cowork-to-code-bridge/blob/main/docs/MCP_SERVER_IMPLEMENTATION.md)**.

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
**macOS** (launchd), **Linux** (`systemd --user` or the [no-systemd installer path](https://github.com/abhinaykrupa/cowork-to-code-bridge/blob/main/docs/LINUX-NO-SYSTEMD.md)), and **WSL2 on Windows** (systemd in your Ubuntu distro) are supported. **Native Windows** (PowerShell, Task Scheduler) is not — use WSL2; see [docs/WSL.md](https://github.com/abhinaykrupa/cowork-to-code-bridge/blob/main/docs/WSL.md).

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

**Q: How do I restrict what Claude Code can do on a task?**
Set `CLAUDE_FLAGS` in your environment before the bridge invokes Claude Code. Three recipes, from cautious to locked-down:

```bash
# 1. Plan-only: Claude can read and suggest, but never edit or run anything
CLAUDE_FLAGS="--permission-mode plan"

# 2. Edit-only: allow file edits, block shell commands
CLAUDE_FLAGS="--permission-mode plan --allowedTools Edit,Write,Read,Glob,Grep"

# 3. Full agent, scoped to one repo (block network & system commands)
CLAUDE_FLAGS="--allowedTools Edit,Write,Read,Glob,Grep,Bash --disallowedTools WebFetch,WebSearch"
```

Export the variable in your shell profile or set it in the bridge's launchd/systemd unit file. See `run_claude.sh` for where `CLAUDE_FLAGS` is consumed.

**Q: What happens if my Mac crashes or reboots while something is running?**
You're covered. The bridge restarts itself automatically, and it's careful not to repeat anything dangerous:
- An action that was *mid-run* when the crash hit is reported as "didn't finish — status unknown" rather than quietly run again. So a half-finished `git push` won't accidentally fire twice.
- An action that had already *finished* keeps its result.

Developers: the full crash-recovery model (the journal, in-flight markers, and the `idempotency_key` option for safe retries) is documented in [`docs/architecture.md`](https://github.com/abhinaykrupa/cowork-to-code-bridge/blob/main/docs/architecture.md).

---

## Community & Discussions

Active in these framework communities:

| Community | Topic |
|-----------|-------|
| [AutoGen Discussions](https://github.com/microsoft/autogen/discussions/7868) | Async local execution for AutoGen agents |
| [CrewAI Discussions](https://github.com/crewAIInc/crewAI/discussions) | Production-safe local code execution for crews |
| [LiteLLM Discussions](https://github.com/BerriAI/litellm/discussions/30841) | LiteLLM → Claude Code bridge pattern |
| [LlamaIndex Discussions](https://github.com/run-llama/llama_index/discussions/22045) | LlamaIndex local executor tool |
| [Agno Discussions](https://github.com/agno-agi/agno/discussions/8486) | Multi-agent local execution pattern |
| [Anthropic SDK Discussions](https://github.com/anthropics/anthropic-sdk-python/discussions/1688) | Remote agent → local Claude Code delegation |
| [MCP Spec Issue #2925](https://github.com/modelcontextprotocol/modelcontextprotocol/issues/2925) | Stateful async operation pattern |
| [Hermes Agent #47199](https://github.com/NousResearch/hermes-agent/issues/47199) | Subprocess MCP bridge for Hermes |

---

## Status & contributing

**v0.5.0** — early, but solid. The core works, survives crashes and reboots without repeating risky actions, installs as a global skill (one command), streams live progress for long tasks, and runs on macOS, Linux, and WSL2. Built for myself, open-sourced because it's useful to others. See the [CHANGELOG](https://github.com/abhinaykrupa/cowork-to-code-bridge/blob/main/CHANGELOG.md) for the full history.

PRs welcome — see [CONTRIBUTING.md](https://github.com/abhinaykrupa/cowork-to-code-bridge/blob/main/CONTRIBUTING.md). Browse [open issues](https://github.com/abhinaykrupa/cowork-to-code-bridge/issues) to find something to work on. Issues triaged best-effort. Not "production-grade" until tagged `v1.0.0`. macOS, Linux, and WSL2; native Windows not yet supported.

### Contributors

Huge thanks to everyone who has shipped code, docs, or tests here 🙏

[@EagleEye-0101](https://github.com/EagleEye-0101) ·
[@sureshpegadapelli84](https://github.com/sureshpegadapelli84) ·
[@ded-furby](https://github.com/ded-furby) ·
[@terminalchai](https://github.com/terminalchai) ·
[@YuuGR1337](https://github.com/YuuGR1337) ·
[@Shaan-alpha](https://github.com/Shaan-alpha) ·
[@osfv](https://github.com/osfv)

New here? A [good first issue](https://github.com/abhinaykrupa/cowork-to-code-bridge/issues?q=is%3Aissue+is%3Aopen+label%3A%22good+first+issue%22) is the easiest way in — and if it lands, your handle goes here too. ⭐ A star also genuinely helps others find the project.

## License

MIT — see [LICENSE](https://github.com/abhinaykrupa/cowork-to-code-bridge/blob/main/LICENSE). Use it, fork it, ship it.
