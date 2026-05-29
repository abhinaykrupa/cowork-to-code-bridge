# SETUP.md — agent playbook for setting up the cowork-to-code bridge

> **You are Claude, running in a Cowork session.** A user just pasted a link to
> this repo and asked you to set up the "Mac bridge" (a.k.a. cowork-to-code
> bridge). This file is **instructions to you, the agent** — not to the human.
> Follow it top to bottom. As you go, you produce the human-facing words and
> commands. The user should never have to read this file themselves.
>
> **Hard rule: do NOT use `/plugin` anywhere.** It does not work in Cowork. The
> entire setup is: (1) a Python client you `pip install` here in the sandbox,
> and (2) a one-line installer the user runs once in their Mac terminal. Nothing
> else.

---

## Step 0 — figure out which world you're in (DO THIS FIRST)

There are two completely different situations, and they need opposite responses.
Run this check before anything else:

```bash
if [ "$(uname)" = "Darwin" ] && ls -d /Applications/Claude.app >/dev/null 2>&1 && launchctl print "gui/$(id -u)" >/dev/null 2>&1; then
  echo "ON_MAC"      # you are running locally on the user's Mac (Claude Desktop / local agent)
else
  echo "SANDBOX"     # you are in a remote/isolated sandbox that cannot reach the user's Mac
fi
```

### If the result is `ON_MAC`

**The user does NOT need this bridge at all, and there is nothing to install.**
You are already running on their Mac with full access to the shell, git, their
files, and their tools. Tell them this plainly, then *prove it* with a harmless
live demo. Say something like:

> Good news — you're using Claude on your Mac directly, so you **don't need to
> install anything**. I can already run things here. Watch:

Then actually run one or two harmless, read-only commands and show the output,
e.g.:

```bash
pwd && echo "---" && (git rev-parse --show-toplevel 2>/dev/null && git status -s 2>/dev/null || echo "(not in a git repo right now)")
```

Then:

> That ran on your actual Mac, no setup. From here just tell me what you want in
> plain English — "run my tests", "push this to GitHub", "what's taking up disk
> space" — and I'll do it. **You can stop reading; you're done.**

**Do not** proceed to the bridge install. The rest of this file is only for the
`SANDBOX` case.

### If the result is `SANDBOX`

You're in an isolated sandbox that cannot see the user's Mac. The bridge is the
only way to reach it, and the user will need to run **one** command on their Mac
once. Continue to Step 1 below.

---

## What you're setting up (so you understand the goal)

This bridge connects **Cowork → Claude Code on the user's Mac**. Cowork (you,
here in the sandbox) hands a task through the bridge to the `claude` CLI running
on the user's Mac; a real Claude Code agent does the work there and the result
comes back. (As a side benefit it can also run other approved scripts — builds,
git, etc.) The bridge is **idempotent**: retries with the same key return a
cached result instead of running the task twice.

It has two halves:

- **Mac daemon** — a tiny background process on the user's Mac. Started once by
  a `curl … | bash` installer. Survives reboots (launchd). You cannot start it
  from the sandbox; only the user can, by running one command on their Mac. It
  ships a `run_claude.sh` script that invokes Claude Code locally.
- **Sandbox client** — the `cowork_to_code_bridge` Python package, importable
  *here*. You install it with `pip`. It talks to the daemon through a shared
  folder, authenticated by a token.

Your job: get the client importable here, confirm the daemon is alive, and if it
isn't, walk the user through the single Mac command with maximum hand-holding.
Once live, hand tasks to Claude Code via `call_remote("scripts/run_claude.sh",
args=[task, workdir], idempotency_key=...)`.

---

## Step 1 — install the sandbox client (silent, ~5s)

First check if it's already importable:

```python
try:
    from cowork_to_code_bridge import daemon_alive  # noqa
    print("client present")
except ImportError:
    print("client missing")
```

If missing, install it (idempotent):

```bash
pip install --quiet "git+https://github.com/abhinaykrupa/cowork-to-code-bridge.git@main"
```

Don't narrate this to the user beyond a short "Setting up the connection…".

## Step 2 — probe for a live daemon

```python
from cowork_to_code_bridge import daemon_alive
print("LIVE" if daemon_alive(ping_timeout=8) else "NOT_REACHABLE")
```

- **LIVE** → the Mac side is already running. **Skip to Step 5.** Do not make the
  user do anything.
- **NOT_REACHABLE** → either the daemon was never installed, or the client can't
  find the bridge folder. Continue to Step 3.

> If you happen to already know the user's `BRIDGE_ROOT` (e.g. they pasted a line
> like `... BRIDGE_ROOT=/Users/x/.cowork-to-code-bridge`), set it before probing:
> `import os; os.environ["BRIDGE_ROOT"] = "<that path>"`. Then re-probe.

## Step 3 — walk the user through the ONE Mac command (maximum hand-holding)

The user is non-technical. Assume they have never opened a terminal. Say
something like this, verbatim in spirit:

> Almost done — there's **one** thing I need you to do on your Mac. It takes
> about 30 seconds and you'll only ever do it once.
>
> **1. Open the Terminal app.**
> Press `Cmd + Space` to open Spotlight search, type **Terminal**, and press
> Enter. A small window with a text prompt will open. (Don't worry — you won't
> need to understand it; you'll just paste one line.)
>
> **2. Copy this exact line and paste it into that Terminal window, then press
> Enter:**
>
> ```bash
> curl -fsSL https://raw.githubusercontent.com/abhinaykrupa/cowork-to-code-bridge/main/install.sh | bash
> ```
>
> (To paste in Terminal: `Cmd + V`, then hit Enter.)
>
> **3. Wait for it to finish.** You'll see green lines scroll by. When it stops
> and shows a line that says **`DONE. Bridge is installed and running.`**, it
> worked.
>
> **4. Come back here and tell me "done"** (or paste anything it printed if you
> hit a snag). I'll take it from there.

Then wait for the user.

## Step 4 — after the user says done, verify (don't trust their word)

Re-install the client if needed (Step 1) and re-probe (Step 2). If the installer
printed a `BRIDGE_ROOT=…` path, set it first:

```python
import os
os.environ["BRIDGE_ROOT"] = "/Users/<them>/.cowork-to-code-bridge"  # use the path from their paste, else default
from cowork_to_code_bridge import daemon_alive
print("LIVE" if daemon_alive(ping_timeout=12) else "STILL_DOWN")
```

If **STILL_DOWN**, diagnose in this order (ask the user to paste the relevant
output from their Mac terminal):

| What to check | Ask the user to run on their Mac | If… |
|---|---|---|
| Daemon registered? | `launchctl list \| grep cowork-to-code-bridge` | empty → `launchctl load ~/Library/LaunchAgents/dev.cowork-to-code-bridge.daemon.plist`, then re-probe |
| Right folder? | `cat ~/.cowork-to-code-bridge/.env` | take the `BRIDGE_ROOT=` value, set it here with `os.environ`, re-probe |
| Daemon erroring? | `tail -20 ~/.cowork-to-code-bridge/daemon.err` | surface the error to the user |
| "No Python 3.10+ found" | (installer message) | The installer auto-installs Python (via Homebrew) by default — this can take a few minutes and may prompt for the Mac password. If the user saw it FAIL or declined: tell them to run `brew install python@3.12` (or install Homebrew first: the one-paste command from brew.sh), then re-run the curl line. They can also re-run with `BRIDGE_PYTHON_AUTOINSTALL=0` to skip auto-install. |

Don't loop silently. After two failed attempts, surface the exact error and the
diagnostic output to the user.

## Step 5 — declare ready

Once a probe returns **LIVE**:

> ✅ Your Mac is connected to Claude Code. You can now hand tasks to a Claude
> Code agent running on your machine — just say what you want in plain English.
> For example:
>
> - "have Claude Code on my Mac run the tests and fix what's failing"
> - "ask my Mac's Claude Code to review the diff and push if it's clean"
> - "run `pytest` on my project" (simple actions can run as a fixed script too)
>
> I'll route it to your Mac and bring back the result. (For repeatable, fixed
> actions I can also use small approved scripts — if I need a new one, I'll write
> it and tell you where to save it.)

From here, hand tasks to Claude Code with
`call_remote("scripts/run_claude.sh", args=[task, workdir], timeout=600,
idempotency_key=...)`. Always pass an `idempotency_key` for Claude Code tasks —
they have side effects, and the key makes a retry safe. For simple fixed
actions, call the specific script directly (`scripts/git_status.sh`, etc.).

## Future sessions

In any later Cowork session, the user can just say "connect to my Mac" or ask
for a Mac action directly. Redo Step 1 (the client install is per-sandbox and
cheap) and Step 2. The daemon is almost always already alive, so you jump
straight to Step 5. No re-onboarding, no terminal, no `/plugin`.

## What NOT to do

- **Never** mention or run `/plugin` — it fails in Cowork and confuses the user.
- **Never** try to install or start anything on the Mac yourself — you can't
  reach it. Only the user's one terminal command can.
- **Never** declare success on the user's word alone — always verify with
  `daemon_alive()`.
- **Don't** make the user read this file or the README. You are the interface.
