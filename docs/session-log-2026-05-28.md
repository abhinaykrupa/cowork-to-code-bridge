# Session log — 2026-05-28: from "should we open source the bridge?" to v0.1.0 live

This doc captures the full arc of the session that birthed cowork-to-code-bridge as a public OSS project. Written for future-me (or whoever picks this up) so the design rationale, the bugs we found, and the things we punted are all in one place.

---

## Starting context

The bridge already worked inside the AAQuant private repo at `~/Documents/Claude/Projects/AAQuant/bridge/` + `aaquant/bridge.py` + `scripts/bridge_daemon.py`. ~400 lines total. Solo author (Abhi), built to solve "Cowork sandbox can't reach my Mac shell."

The question was whether to extract it as a public OSS library so other Cowork+Code users could benefit. We decided yes, with the constraint: **do not touch the AAQuant project during extraction.**

## Decisions locked in (chronological)

| # | Decision | Rationale |
|---|---|---|
| 1 | Name: `cowork-to-code-bridge` | Descriptive over clever; matches who it serves |
| 2 | License: MIT | Permissive, easy adoption, no patent clauses needed for a 400-line library |
| 3 | Distribution: GitHub + PyPI eventually, plugin as primary install path | Plugin gives Cowork-native one-paste UX; PyPI is fallback when plugin spec doesn't fit |
| 4 | UX model: "one paste in Cowork, Cowork drives the rest conversationally" | Maximum user delight; the setup skill handles all the work |
| 5 | Two-paste install is unavoidable | Mac daemon **must** be installed by the user on their Mac — Cowork sandbox cannot reach across the boundary. That's a security feature, not a bug. |
| 6 | Build as a Claude plugin, not just a Python package | Skills auto-trigger from natural-language requests; package is installed transparently |
| 7 | Single-plugin marketplace pattern | Anthropic's plugin spec requires marketplaces; built `cowork-bridge-marketplace` to host this and future plugins |
| 8 | Build now, not post-Jun-9 | User chose to push through despite AAQuant launch deadline (Jun 9) |

## What got built (v0.1.0)

### Repo 1: `cowork-to-code-bridge`
https://github.com/abhinaykrupa/cowork-to-code-bridge

```
.claude-plugin/plugin.json    ← spec-compliant plugin manifest
cowork_to_code_bridge/        ← Python package
  __init__.py                 ← exports call_remote, daemon_alive, __version__
  client.py                   ← Cowork-side: write JSON to queue, poll results/
  daemon.py                   ← Mac-side: poll queue, run whitelisted scripts
  uninstall.py                ← one-command teardown (console script)
skills/
  setup/SKILL.md              ← walks user through install conversationally
  run-on-mac/SKILL.md         ← teaches Claude when to call call_remote()
daemon/
  daemon.py                   ← duplicate of package daemon (foreground dev use)
  ping.sh, start.sh           ← support scripts
  uninstall.sh                ← shell-fallback uninstaller
install.sh                    ← curl|bash Mac installer
pyproject.toml                ← PyPI-ready
README.md                     ← human-friendly, non-technical
examples/                     ← whitelisted script samples + Cowork usage
docs/                         ← architecture, this session log
LICENSE                       ← MIT
```

### Repo 2: `cowork-bridge-marketplace`
https://github.com/abhinaykrupa/cowork-bridge-marketplace

```
.claude-plugin/marketplace.json    ← lists cowork-to-code-bridge
README.md, LICENSE, .gitignore
```

## The install UX

**Mac (once):**
```bash
curl -fsSL https://raw.githubusercontent.com/abhinaykrupa/cowork-to-code-bridge/main/install.sh | bash
```

**Cowork (any session, natural language):**
> "Set up the cowork-to-code bridge."

Claude figures out everything else: adds the marketplace, installs the plugin, verifies the Mac daemon, declares ready. Setup skill description triggers on phrases like "install cowork bridge", "connect cowork to my mac", etc.

**Manual fallback (if user prefers explicit commands):**
```
/plugin marketplace add abhinaykrupa/cowork-bridge-marketplace
/plugin install cowork-to-code-bridge@cowork-bridge-marketplace
```

## How we got there — agent-driven build

Used parallel sub-agents twice. Both times: ~2-3 agents in parallel, synthesized results into commits.

### Phase B — verification (3 agents in parallel)
1. **install-tester** — actually ran install.sh on this Mac, reported runtime + static issues
2. **plugin-spec-auditor** — checked plugin.json shape against Anthropic's real plugin spec docs
3. **test-plan-writer** — drafted a manual test plan for fresh-Cowork-session UX verification

Findings: plugin manifest was in wrong location, wrong shape, contained made-up fields; install.sh had multiple blockers; "paste URL into Cowork" UX was aspirational (real install needs marketplace).

### Phase A — fixes to v1.0 (4 agents in parallel)
1. **install.sh-fixer** — Python discovery, plist absolute path, PEP 668, launchctl bootstrap, ERR trap, PATH detection
2. **manifest-fixer** — restructured to `.claude-plugin/plugin.json`, moved skills/ to root, dropped made-up fields
3. **marketplace-builder** — built `cowork-bridge-marketplace` as a separate repo, published live
4. **skill-updater** — patched setup SKILL.md for natural-language trigger + marketplace install + recovery branches

All 4 committed cleanly without conflicts. Synced + pushed.

## Bugs found during testing (and fixes)

| # | Bug | Where | Fix |
|---|---|---|---|
| 1 | `python3` resolves to Apple's `/usr/bin/python3` (3.8) even with brew python@3.10 installed | install.sh preflight | Probe `python3.13 → 3.10` explicitly, never fall through to bare `python3` |
| 2 | Plist hardcodes whatever `command -v python3` returned, sometimes `/tmp/` shim that vanishes on reboot | install.sh launchd setup | Resolve to absolute path of installed console script via `sysconfig` |
| 3 | `sysconfig.get_default_scheme()` returns `osx_framework_library` on framework Python builds; `_user` variant doesn't exist | install.sh user-scripts-dir resolution | Use `sysconfig.get_preferred_scheme('user')` (Python 3.10+); fall back to manual `_user` scheme probe; final fallback `site.getuserbase()` |
| 4 | `pip install --user` errors silently on PEP 668 externally-managed Python (brew 3.12+) | install.sh pip step | Detect "externally-managed-environment" in pip output; retry with `--user --break-system-packages` + warning |
| 5 | `launchctl load -w` is deprecated on modern macOS | install.sh launchd setup | Use `launchctl bootstrap gui/$(id -u)` with `load -w` fallback |
| 6 | `~/Library/Python/X.Y/bin` not on PATH → bare `cowork-to-code-bridge-uninstall` fails | install.sh + README | Installer detects PATH gap, prints exact `~/.zshrc` line, optionally prompts to append. README documents full-path workaround. |
| 7 | Empty `BRIDGE_TOKEN=` line in `.env` matched as "already set" | install.sh token step | Detect empty value and regenerate |
| 8 | Daemon-up poll was 5s — too short on cold caches | install.sh verify step | Bumped to 20×1s |
| 9 | Stale "Install plugin from <github url>" text in DONE message and plugin.json description | install.sh + .claude-plugin/plugin.json | Updated to natural-language UX + marketplace install |
| 10 | Plugin manifest at `plugin/plugin.json` (wrong location) | manifest restructure | Moved to `.claude-plugin/plugin.json` at repo root |
| 11 | `skills: [{id, path}]` objects (wrong shape) | manifest restructure | Changed to `skills: ["./skills/"]` (auto-discovery) |
| 12 | `lib.python_package`, `requires.python`, `post_install` fields (don't exist in spec) | manifest restructure | Removed entirely |
| 13 | "Plugin install from raw GitHub URL" doesn't exist | UX model | Built a marketplace repo; Claude runs `/plugin marketplace add` + `/plugin install` on user's behalf when triggered by natural language |

## Test results — end of session

| Test | Result |
|---|---|
| Uninstall #1 (full clean) | ✅ All 4 dimensions verified clean (launchctl, plist, bridge folder, package) |
| Reinstall #1 (curl\|bash) — pre-fixes | ❌ Failed: Python 3.8 stub blocked preflight |
| Reinstall #2 (curl\|bash) — after Phase A fixes | ❌ Failed: sysconfig scheme bug (bug #3 above) |
| Reinstall #3 (curl\|bash) — after sysconfig fix | ✅ **PASS** — daemon bootstrapped, ping returns exit_code=0, plist absolute path, survives reboot |
| Uninstall #2 (one-command) | ✅ All 4 dimensions clean again |

Final state: **bridge installed live on this Mac**, will survive reboot, can be removed with one command at any time.

## Released

| Release | URL |
|---|---|
| `cowork-to-code-bridge v0.1.0` | https://github.com/abhinaykrupa/cowork-to-code-bridge/releases/tag/v0.1.0 |
| `cowork-bridge-marketplace v0.1.0` | https://github.com/abhinaykrupa/cowork-bridge-marketplace/releases/tag/v0.1.0 |

---

## Lessons learned

### About the bridge itself

1. **The "two paths, one Cowork command" UX works.** Mac side is `curl | bash`, Cowork side is a natural-language request. Setup skill handles everything in between. We can't get rid of the Mac install because of sandbox boundaries, but we can make it feel like one step.

2. **Don't fight the plugin spec.** The original "paste a GitHub URL in Cowork" was aspirational; real install is `/plugin marketplace add` + `/plugin install`. Wrapping that in a setup skill that triggers on natural language gets the same UX without fighting the platform.

3. **Marketplaces are cheap.** A single-plugin marketplace is ~30 lines of JSON in a separate repo. Worth it for spec compliance and future expansion.

4. **The file-based bridge model is simpler than MCP for this use case.** No long-lived server in the sandbox, no transport choice, no schema. Just files on a bind-mount. The 1-second polling latency doesn't matter for shell ops.

### About building with agents

5. **Parallel agents for verification beats parallel agents for implementation.** The 3 verification agents (Phase B) found real bugs independently. The 4 implementation agents (Phase A) sometimes overlapped or made redundant decisions.

6. **Live testing catches things static analysis doesn't.** The agent that actually ran install.sh found runtime bugs (PEP 668, framework Python sysconfig quirk) the static auditor missed.

7. **CDN cache lag is real.** GitHub `raw.githubusercontent.com` served stale content for ~3 minutes after my push. SHA-pinned URLs bypass this; useful for tight test loops.

8. **Test plans should be written before the implementation, not after.** The test-plan agent's plan would have caught the BRIDGE_ROOT bind-mount issue before we wrote a single line of new code.

### About macOS-specific install quirks

9. **Apple's stock `python3` is a trap.** It's 3.8, lives at `/usr/bin/python3`, and brew's keg-only python@X.Y kegs don't shadow it. Every installer that does `python3 --version` to detect Python is broken by default.

10. **Framework Python has its own sysconfig schemes.** `osx_framework_library` doesn't have a `_user` variant. Use `get_preferred_scheme('user')` (3.10+) instead of constructing scheme names by hand.

11. **`launchctl load -w` is deprecated.** New code should use `bootstrap gui/<uid>`, but the legacy fallback matters because some macOS configurations still need it.

12. **PEP 668 silently breaks `pip --user`.** Detect the marker in pip's stderr and retry with `--break-system-packages`. Don't just fall through silently.

13. **`~/Library/Python/X.Y/bin` is not on PATH by default.** Every installer that puts console scripts there has to either add to PATH or document the absolute-path fallback. Mine does both.

### Process lessons

14. **Don't conflate "shipped" with "tested in production."** The plugin install flow in an actual Cowork session is still untested. Marketplace validation passing locally is not the same as a user successfully running `/plugin install` and seeing it work.

15. **Document while building, not after.** This session log was written immediately after v0.1.0 shipped. The decisions and rationale are still fresh. Anything written next week would lose half of them.

16. **The "by the way, here's another bug" pattern compounds.** Every new test surfaced bugs in code touched by previous tests. Writing once and verifying once isn't enough.

---

## Next steps — what's untested or unfinished

### Critical (do before declaring "production-ready")

1. **Real Cowork session test.** Open Cowork, paste "Set up the cowork-to-code bridge", verify:
   - Setup skill triggers on natural language
   - `/plugin marketplace add` actually runs
   - `/plugin install` succeeds
   - Setup skill detects existing Mac daemon via probe
   - End-to-end `call_remote("scripts/ping.sh")` returns expected output
2. **BRIDGE_ROOT bind-mount alignment.** Setup skill says it'll handle the case where Cowork sandbox's view of `~/.cowork-to-code-bridge` doesn't match the Mac path. Untested in the wild — needs real-Cowork-session verification.
3. **Custom-script flow.** Test plan case #5 — user adds `~/.cowork-to-code-bridge/scripts/my_test.sh`, asks Cowork to run it. Untested live.
4. **Timeout handling.** Test plan case #7 — `sleep 90` script with timeout=10, verify graceful timeout response. Untested live.

### Important (do before v0.2.0)

5. **Publish to PyPI.** install.sh currently always falls through to GitHub source install. PyPI would speed installs and let users use plain `pip install cowork-to-code-bridge` for development.
6. **GitHub Actions CI.** No tests, no lint, no release-on-tag workflow. Should add at least `pytest` + `ruff` runs on PR.
7. **Write actual tests.** No `tests/` directory exists. At minimum: roundtrip test (write to queue, read from results), token-mismatch test, timeout test, path-traversal-rejection test.
8. **Consolidate `daemon/daemon.py` and `cowork_to_code_bridge/daemon.py`.** They're identical now but will drift. Make the `daemon/` version a thin shim or remove it.

### Nice-to-have (post-v0.2.0)

9. **Linux + Windows daemon support.** Currently macOS-only because of launchd. systemd for Linux, Task Scheduler for Windows. Core daemon code is cross-platform; only the install/launch path is OS-specific.
10. **A real plugin registry submission.** When/if Anthropic ships a central plugin registry, list cowork-to-code-bridge there.
11. **A demo GIF or video.** Worth 10× the README for adoption.
12. **`bridge_root` autodetection for Cowork sandbox.** Could probe known mount points instead of requiring `BRIDGE_ROOT` env var.
13. **Multi-tenant token support.** Right now one Mac = one daemon = one token. Could support per-project tokens for isolation between Cowork projects on the same Mac.

### Known sharp edges to document better

14. The PATH issue (`~/Library/Python/X.Y/bin`) — README has it but a more prominent troubleshooting callout would help.
15. The fact that re-running `install.sh` is idempotent — useful but underexplained.
16. The behavioral rule: bridge can't escape the script whitelist. Users sometimes ask "can you run this command for me" expecting arbitrary shell; document the "no, but I can help you write a script for it" pattern.

---

## What this session did NOT touch

Per the constraint set early: **AAQuant private repo is untouched.** All bridge work happened in new directories outside AAQuant. AAQuant's own bridge implementation (the original ~400 lines in `aaquant/bridge.py` + `scripts/bridge_daemon.py`) is unchanged.

The AAQuant launch deadline (Jun 9 — 12 days from session end) is unaffected. Time spent on bridge extraction: ~4 hours of focused work, mostly parallelized via sub-agents.

---

## Files of record (for future-me)

- Session start: this repo didn't exist
- Session end: two repos live, v0.1.0 released on both, daemon running on author's Mac
- All commits: `git log` in this repo and the marketplace repo
- Decisions: this doc
- Test plan: agent #3 from Phase B drafted one — never saved as a file (returned in chat); should be captured to `docs/test-plan.md` next session
- Architecture details: `docs/architecture.md`

If you're reading this in 6 months and the plugin spec has changed or the bridge UX has evolved, that's expected. v0.1.0 was deliberately shipped early, knowing rough edges exist. Iterate from here.
