# Launch kit (internal — not part of the product)

Draft promo copy for cowork-to-code-bridge. Tune to your voice before posting.
**Do not buy stars / fake activity** (Anthropic's OSS program flags it). Real
distribution only.

Repo: https://github.com/abhinaykrupa/cowork-to-code-bridge

---

## Timing
- **Show HN**: Tue–Thu, ~8:00–9:30am ET. One link, short text body. Be around to reply for 2–3h.
- **Product Hunt**: schedule for 12:01am PT; first-comment with the story.
- **Reddit**: post after HN; space out subreddits by a few hours.
- Run `./scripts/stats.sh` daily to see which channel moved traffic; double down there.

---

## Show HN

**Title** (pick the one that feels most you — HN titles are make-or-break; concrete > clever):
> Show HN: Let Claude run code on your real machine, from any Claude chat (macOS/Linux)

Alternatives:
> Show HN: A bridge so Claude in the browser can build and run code on your machine
> Show HN: Cowork-to-code-bridge – give Claude Cowork a real shell on your Mac/Linux, safely
> Show HN: I connected Claude's browser sandbox to Claude Code on my laptop

Tip: lead the first comment (not the title) with the concrete demo story — the
"scaffold a Flask app, run it, curl it, report {status:ok}" round trip. Show, don't claim.

**Body:**
> Claude in the browser (Cowork) is great at planning and editing, but it runs in a
> sandbox — it can't run your build, your tests, or push to git. Claude Code can,
> but only on your machine.
>
> This is a small open-source bridge that connects them: you run one command on
> your Mac/Linux box, and from then on any Claude chat can hand a task to a real
> Claude Code agent on your machine. It builds the app, runs the tests, fixes
> failures, streams the output back — then you're done.
>
> How it works: no network listener and no server. A tiny daemon watches a local
> folder; Cowork drops a task file in, the daemon runs only whitelisted scripts
> (token-protected), writes the result back. It's idempotent (retries never
> double-run) and crash/reboot-safe (journaled). Installs as a global skill so
> every session just works — no per-project setup, no plugin command.
>
> Stdlib-only, MIT. Honest limits: macOS/Linux only (no Windows yet), and
> `run_claude.sh` gives a Cowork session a full local agent — there's a documented
> knob to restrict it. Feedback welcome.
>
> https://github.com/abhinaykrupa/cowork-to-code-bridge

---

## Reddit — r/ClaudeAI

**Title:** I built an open-source bridge so Claude (in the browser) can run code on my actual machine

**Body:**
> If you use Claude Cowork you've hit the wall where it can plan and edit but
> can't *run* anything on your computer. I got tired of copy-pasting commands
> back and forth, so I made a small bridge.
>
> One command on your Mac/Linux box installs it. After that, in any Claude chat I
> can say "build me a web app and run it" or "run my tests and fix what fails,"
> and a real Claude Code agent on my machine does it and streams the output back.
>
> No network listener (security), only runs scripts you approve, idempotent,
> survives reboots. MIT, stdlib-only. Would love feedback / what you'd want it to
> do: [link]

Also good for: **r/selfhosted** (lead with "self-hosted daemon, no cloud, no
ports"), **r/SideProject**, **r/commandline**.

---

## X / Twitter thread

1/ Claude in the browser can't run code on your machine. Claude Code can. I built
a tiny open-source bridge that connects them. One command, then any Claude chat
can build/test/ship on your real Mac or Linux box. 🧵

2/ Say "build me an app and run it" in a Claude chat → a real Claude Code agent on
your machine does it → output streams back to the chat. No copy-paste loop.

3/ How: no server, no open ports. A local daemon watches a folder, runs only
scripts you've approved (token-gated), writes results back. Idempotent +
reboot-safe.

4/ Installs as a global skill — every chat just works, no per-project setup, no
plugin command. macOS + Linux. MIT, pure stdlib.

5/ Repo (stars appreciated if it's useful 🙏): [link]

---

## LinkedIn / blog (short)

**Title:** Closing the gap between Claude-in-the-browser and your dev machine

> Claude Cowork is excellent at thinking through a change, but it's sandboxed — it
> can't run your build or touch your repo. Claude Code can, locally. I open-sourced
> a small bridge that connects the two so a single browser chat can drive a real
> Claude Code agent on your own Mac or Linux machine: build, test, fix, commit —
> end to end, with the output streamed back.
>
> It's deliberately boring and safe: no network listener, token-gated,
> whitelist-only execution, idempotent, crash-resilient. One command to install;
> then it's available in every chat automatically.
>
> If you live in Claude and want it to actually *do* things on your machine, try
> it (MIT): [link]

---

## First-comment / use-case story (for PH/HN follow-up)
> Concrete example: I told a Cowork chat "scaffold a Flask app with a /health
> route, install deps, run it, and confirm it responds." It created the files,
> made a venv, pip-installed, started the server, curled the endpoint, and
> reported back `{"status":"ok"}` — all on my machine, in one message. That round
> trip is the whole point.
