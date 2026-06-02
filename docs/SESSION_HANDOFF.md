# Session handoff — cowork-to-code-bridge

_Last updated: 2026-06-02. Repo clean, synced to origin/main @ `317ad45`, CI green (all 6 jobs: macOS+Linux × py3.10/11/12)._

## State
v0.5.0 shipped. 5 contributors, ~3 stars / 6 forks. Live Reddit post in r/ClaudeCowork. Bridge is mission-ready and verified on a fresh install (8/8 scenarios).

## In flight (parked on others, NOT on us)

| Item | Status | Next action |
|---|---|---|
| PR #31 (WSL2 install, EagleEye-0101) | **Held** — good work but ~4 commits behind main; lacks today's security fixes | Asked contributor to rebase; on rebase → re-verify + merge (closes #3) |
| PR #32 (skill table, YuuGR1337) | **Sent back** — broke README markdown, wrong location | Wait for contributor fix; belongs in SKILL.md Step 3 table, not README install |

## Top-priority open issues (user's two new ideas)
- **#33 Router** — auto-pick `--model`/`--effort`/`--permission-mode` per task. BUILDABLE NOW (verified `claude` CLI has all flags; `CLAUDE_FLAGS` plumbing exists from #14). Design: Cowork suggests, bridge enforces caps. **Start here if building.**
- **#34 Reverse direction** (Claude Code → Cowork) — design/research only. Hard constraint: Cowork sandbox has no inbound address; best achievable is a poll-while-open mirror queue. Nail the use case before coding.
- **#15 Demo GIF** — launch priority; only the human can record it (shot list in `docs/demo-recording-script.md`).

## Key facts that aren't obvious from git
- **Security model (audited this session):** no network listener, constant-time token, whitelist-only (`re.fullmatch`), 0700 dirs, command-size cap, and **daemon env wins over caller `cmd.env` for CLAUDE_FLAGS/BRIDGE_* vars** (prevents a token-holder from undoing owner restrictions).
- **3 client copies must stay in sync** (`cowork_to_code_bridge/client.py`, root `bridge_client.py`, `skill/.../bridge_client.py`) + daemon mirror `daemon/daemon.py`. Guard tests enforce it.
- **Linux CI catches what local macOS can't** — the mac_ram test was macOS-only and broke Linux CI; always check the ubuntu jobs.
- **Promotion rule (hard):** never auto-post to Reddit/forums or cold-ping — it's spam AND disqualifies the Anthropic OSS-program goal. Human posts; copy staged in `docs/reddit-post-ready.md`.

## First action next session
Either: start router #33 v1, or check if #31/#32 contributors pushed updates (`gh pr list`).
