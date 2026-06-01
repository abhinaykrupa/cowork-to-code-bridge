# Let Claude run code on your real machine — safely — from any Claude chat

*Announcing cowork-to-code-bridge — an open-source bridge from Claude Cowork to Claude Code on your own Mac or Linux box.*

## The gap

If you use Claude in the browser — Cowork — you've felt this wall: Claude can read your repo, plan a change, and write the code… but it can't actually *run* anything on your computer. It can't run your build, execute your tests, install a package, or push to git. That's by design — Cowork runs in a sealed cloud sandbox that can't reach your machine.

Meanwhile, **Claude Code** — running locally — *can* do all of that. It has your shell, your repos, your tools, your credentials. The two halves of the same product can't talk to each other.

So you end up copy-pasting commands back and forth between a browser tab and a terminal. That's the gap this closes.

## What it does

`cowork-to-code-bridge` connects the two. You install it once on your machine; after that, from any Claude chat you can say:

> *"build me a small web app, install the deps, run it, and confirm it responds"*

…and a real **Claude Code agent on your machine** does it — scaffolds the files, creates a venv, installs, starts the server, curls the endpoint, reports back `{"status":"ok"}` — all streamed live into your chat. You never leave the conversation.

It also handles the simple stuff directly: *"check my machine's health"*, *"what's listening on port 3000?"*, *"git push my project"*.

## How it works (and why it's safe)

There's no server and no open ports. The bridge is **file-based**:

1. Cowork writes a task into a shared folder's `queue/`.
2. A tiny daemon on your machine (launchd on macOS, systemd on Linux) sees it, runs **only scripts you've whitelisted**, and writes the result to `results/`.
3. Cowork reads the result. For long builds, output streams live via a `progress/` log.

Security is the default, not an afterthought:

- **No network listener** — nothing from the outside can connect in.
- **Token-gated** — every request carries a secret generated at install.
- **Whitelist-only execution** — Cowork can't run arbitrary commands, only the scripts you've enabled.
- **Constant-time token checks, 0700 perms, command-size caps.**

And it's built to survive the real world:

- **Idempotent** — every task carries a key; a retry after a dropped connection returns the cached result instead of running twice (so a flaky connection never double-commits or double-deploys).
- **Crash/reboot-safe** — tasks are journaled and marked in-flight; a daemon that dies mid-task is detected on restart and never silently re-runs.

## Install — two pastes

1. On your machine (once):
   ```bash
   curl -fsSL https://raw.githubusercontent.com/abhinaykrupa/cowork-to-code-bridge/main/install.sh | bash
   ```
2. Paste the connect line it prints into a Cowork chat, approve the folder access, and you'll see `BRIDGE LIVE`.

That's it. macOS and Linux. MIT-licensed, pure Python standard library, zero dependencies.

## Where it's going

It's early (v0.5.0) but solid — tested, CI on macOS + Linux, and already picking up its first outside contributors. On the roadmap: Windows/WSL, richer permission scoping for agent tasks, and more starter scripts. If that's useful to you, I'd genuinely love feedback — and the `good first issue`s are open.

**→ github.com/abhinaykrupa/cowork-to-code-bridge**

---

*Built because I wanted Claude to actually do things on my machine, not just tell me what to type. If you live in Claude, give it a try.*
