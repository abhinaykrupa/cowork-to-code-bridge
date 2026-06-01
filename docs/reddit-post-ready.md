# Reddit post — ready to paste (DO THIS WHEN AWAKE, post it yourself)

**Where:** https://www.reddit.com/r/ClaudeAI/submit  (also fits r/selfhosted, r/commandline — post one at a time, days apart, tailor each)

**Why you, not a bot:** Reddit bans auto-posted self-promo (shadow-ban + domain blacklist), and the first 2–3 hours of YOU replying to comments is what makes it land. Post when you can sit with it for a couple hours.

---

## Option A — story-first (recommended for r/ClaudeAI)

**Title:**
`I built an open-source bridge so Claude (browser/Cowork) can run code on my actual machine`

**Body:**
> Claude Cowork can plan and edit, but it runs in a sandbox — it can't run my build, my tests, or push to git. Claude Code can, but only locally. I got tired of copy-pasting commands between a browser tab and my terminal, so I built a small bridge.
>
> One command on my Mac/Linux box installs it. After that, in any Claude chat I can say *"build me an app and run it"* or *"run my tests and fix what fails,"* and a real Claude Code agent does it on my machine and streams the output back. It also does quick stuff directly — *"check my machine's health,"* *"what's on port 3000."*
>
> How it works: no server, no open ports. A tiny daemon watches a local folder; Cowork drops a task file in, the daemon runs only scripts I've approved (token-gated), writes the result back. It's idempotent (a dropped connection never double-runs a git push) and survives reboots.
>
> MIT, pure Python stdlib, macOS + Linux. It's early but tested, and a few people have already started contributing.
>
> Repo: https://github.com/abhinaykrupa/cowork-to-code-bridge
>
> Genuinely want feedback — what would you want it to do that it doesn't yet? And how's the install/connect on your setup?

---

## Option B — shorter / punchier (X, or a tired-of-copy-paste angle)

> Claude in the browser can't run code on your machine. Claude Code can — locally. I open-sourced a tiny bridge that connects them: ask in any Claude chat → a real Claude Code agent builds/tests/ships on your own machine → output streams back. No server, no open ports, idempotent. macOS + Linux, MIT.
> https://github.com/abhinaykrupa/cowork-to-code-bridge

---

## First-comment to drop yourself (the demo that sells it)

> Concrete example from earlier today: I told a chat *"scaffold a Flask app, install deps, run it, confirm the / route returns JSON, then stop the server."* It created the files, made a venv, pip-installed, started the server, curled the endpoint, got `{"status":"ok"}` 200, and cleaned up — all on my machine, in one message. That round trip is the whole point.

## After posting
- Reply to every comment for the first couple hours.
- Run `./scripts/stats.sh` to see if the traffic shows up in referrers.
- Don't cross-post the same text the same day — space it out, retitle per sub.
