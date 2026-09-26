# Changelog

All notable changes to this project. Format loosely follows
[Keep a Changelog](https://keepachangelog.com/); versions are the `pyproject.toml`
/ `plugin.json` version.

## [Unreleased]

## [0.6.2] - 2026-09-25

Packaging release: makes a Homebrew tap possible and stops every release from
shipping with red workflow runs.

### Fixed
- **Tagged installs no longer silently install `main`.** When PyPI had nothing
  (always, so far), `install.sh` fell back to `git+https://…@main` even when it
  was running from a release tarball or a Homebrew formula, so a "v0.6.1"
  install got whatever `main` held that day. It now installs the source tree it
  ships in when it has one; `curl | bash` keeps the remote path. The selection
  is a function tested against the real text of `install.sh`.
- **Releases no longer fail two workflows.** `publish.yml` failed on every tag
  (no PyPI Trusted Publisher configured) and `bump-formula.yml` waited for a PyPI
  release that never existed, then needed a cross-repo token that was never
  created. Six red runs across three releases.

### Changed
- **Release assets.** Each tagged release now carries the built wheel and sdist,
  so `pip install <wheel URL>` works for a pinned version without PyPI. The PyPI
  upload is a separate job gated on the `PYPI_PUBLISH` repository variable —
  skipped, not failed, until it is set up.
- **Homebrew formula no longer runs the installer during `brew install`.**
  Homebrew 7 replaces script-running `post_install` with a declarative DSL, and
  registering a launchd agent from inside `brew install` was never appropriate.
  The formula installs the files plus a `cowork-to-code-bridge-setup` command,
  and its `test` block checks the bundled package reports the formula's version.
- `bump-formula.yml` removed; the tap tracks releases itself using its own token.

## [0.6.1] - 2026-09-25

Security hardening of the sandbox → host boundary, from verifying two outside
reviews. Severity is stated precisely: in the **default** layout the sandbox can
already write its own script into `scripts/`, so most of this is defence in
depth there. It is **load-bearing** in the hardened layout (scripts outside the
mount), which is now documented in SECURITY.md.

### Security
- **Link-safe I/O in the shared folder.** Every daemon read and write under
  `BRIDGE_ROOT` now goes through `safefs`: anchored on a directory fd opened
  `O_NOFOLLOW`, temp names unpredictable and `O_EXCL`, non-regular and
  multiply-linked files refused. Previously a planted symlink could redirect a
  daemon write to any host file — including on the token-mismatch path — and a
  whole state directory could be swapped for a link. Reported as a TOCTOU concern
  in openinterpreter/openinterpreter#1864. 9 attack tests, each asserting the
  victim file's bytes, not a response payload.
- **Caller environment filtered.** A task's `env` could replace any owner
  variable outside a 7-name list and add anything — `BASH_ENV` or `PATH` alone
  gave arbitrary code under the most restrictive ceiling while running only a
  harmless allowlisted script (PoC in the tests). Caller vars may now only *add*
  conventional upper-case names; code-loading, config, and network-routing names
  are dropped and reported in a new `env_rejected` result field.
  `BRIDGE_CALLER_ENV=0` (service definition only) disables caller env entirely.
  The old code also contradicted its own comment, which said callers could only
  set vars the daemon didn't already have.
- **`.env` is untrusted input.** It is sandbox-writable, so it now gets the same
  filter; only `BRIDGE_TOKEN` is taken from it unconditionally.
- **SECURITY.md corrected.** It claimed the daemon "runs only scripts you've
  approved". In the default layout the sandbox can add scripts, and it now says
  so, with a default-vs-hardened table and setup steps.

### Fixed
- **Children inherit `/dev/null` as stdin.** Several headless agent CLIs block or
  exit silently with an open stdin; foreground and manual runs inherited the
  daemon's terminal. Raised in aaif-goose/goose#10788.
- **A FIFO in `queue/`, `cancel/` or at `.env` hung the daemon** — `read_text()`
  blocks on a FIFO with no writer. Reads are now non-blocking and non-regular
  files are rejected.
- **Scripts get the root the daemon actually serves** as `$BRIDGE_ROOT`, instead
  of whatever the process env or `.env` said. Several `mcp_*.sh` scripts use it
  bare.
- **Task ids are validated** before becoming filenames in four directories.

## [0.6.0] - 2026-09-05

Security, durability, and honesty-of-docs release. Two of these fix failures
that were silently live on real installs.

### Added
- **Secret redaction on the write path (#76).** Task output is scrubbed before it
  reaches the result file, progress log, or status line. The daemon's own
  `BRIDGE_TOKEN` is redacted with certainty; vendor key prefixes, `Authorization:`
  headers, inline URL passwords, private-key blocks, and long values assigned to
  key-ish names are matched heuristically. `BRIDGE_REDACT=0` disables it.
  Best-effort by design — see SECURITY.md.
- **Queue-age expiry (#77).** `max_age_sec` bounds how long a task may *wait*, not
  just run. A daemon that was asleep no longer executes an hours-stale backlog on
  restart; expired tasks get a normal result with `exit_code=-6`.
- **Real task cancellation.** `cancel_task` signals the whole process group
  (SIGTERM, then SIGKILL after a grace period) instead of setting a flag that
  nothing read.
- **Bounded task output.** stdout/stderr are capped while streaming, keeping the
  tail, with `stdout_truncated` / `stdout_total_bytes` on the result.
- **[docs/WITHOUT_CLAUDE.md](docs/WITHOUT_CLAUDE.md).** The bridge driven with no
  Claude in the loop — the directory protocol, plain-Python and pure-shell
  clients, and how to add your own script. 23 of the 25 bundled scripts have
  nothing to do with Claude; nothing demonstrated that until now.

### Fixed
- **TCC-protected `BRIDGE_ROOT` bricked launchd (#83).** A root under
  `~/Documents`, `~/Desktop` or `~/Downloads` is unstartable by launchd on macOS
  13+: the shell has TCC consent, launchd does not, so it dies with EX_CONFIG (78)
  *before* Python starts — no log output at all, while `KeepAlive` respawns it
  forever. Selfcheck now reads the root the daemon actually serves, names the TCC
  cause, and `install.sh` refuses such a root up front.
- **Client resolved a stale `$PWD/bridge` (#84).** Tasks were written into a
  leftover directory no daemon watches, producing a 30s timeout whose error
  blamed the daemon. All three client copies now prefer the installed service's
  root. An explicit `BRIDGE_ROOT` still wins.
- **Documented `pip install` 404'd, and two README badges rendered
  "package or version not found"** — the package has never been published (#41).
  The badges are gone and the developer install is the `git+https` form, verified
  end-to-end in a clean venv.
- **Package client was missing two documented functions (#79)**, so a documented
  import raised `ImportError`.

### Changed
- **README leads with earned coverage.** The eight framework discussions
  (9 upvotes and 0 comments between them) are demoted to a prose line; a
  **Featured in** section names the two listings that actually merged —
  [Awesome Agentic Patterns](https://www.agentic-patterns.com/patterns/filesystem-mediated-host-delegation/)
  (which catalogued this architecture as a named pattern) and
  agentic-awesome-skills.

### Internal
- Parity guards against silent cross-surface drift: routing tables (#80),
  `install.sh` heredoc *content* (#81), exit-code docs (#82), and the version
  string itself, which lives in seven files.


### Added
- **Permission-scope ceiling enforcement (#47).** The owner can now set
  `BRIDGE_PERMISSION_CEILING` (`plan` < `readonly` < `edit` < `full`); a caller's
  per-task `permission_scope` is clamped down to the ceiling before the script runs,
  so the bridge token can never be used to widen trust beyond the owner's cap. An
  invalid ceiling value is warned and enforces no ceiling (fail-open on the value,
  the scope allowlist still bounds trust). `permission_scope` is now also exposed on
  the MCP `escalate_to_claude` tool. Fixes the gap where the SKILL docs described a
  ceiling that the daemon did not actually enforce.
- **Community discussions posted** to 8 major AI framework communities: AutoGen, CrewAI, LiteLLM, LlamaIndex, Agno, DSPy, Haystack, Semantic Kernel, and Anthropic SDK Python — all with framework-specific integration patterns.
- **GitHub topics expanded** to 20 (added: mcp, mcp-server, local-llm, llm-agents, crewai, langchain, autogen, code-execution, bridge, async) for better discoverability.
- **README: Community & Discussions section** linking all active framework threads.
- **Per-operation metrics and loop detection** in MCP server — `get_operation_status` now returns tool_calls, api_spend_estimate, memory_mb, cpu_percent, repeated_calls per operation.
- **Comprehensive cancellation test suite** (6/6 scenarios: pre-execution, during-execution, post-execution, idempotent, unknown, loop detection).
- **PyPI install path (#36).** README PyPI version + downloads badges, developer
  `pip install` docs, `install.sh` version floor `>=0.5.1`, and PyPI URL in
  `pyproject.toml`. Maintainer: follow [docs/RELEASING.md](docs/RELEASING.md) to
  publish the first release.
- **Cowork Recipes doc (#38).** Rewrote [docs/RECIPES.md](docs/RECIPES.md) with
  10 plain-English, copy-paste tasks (FastAPI health check, test-fix-commit,
  disk cleanup with confirmation, release tagging, dev-server screenshot, and more).
- **Homebrew formula (#37).** macOS install via `brew install abhinaykrupa/tap/cowork-to-code-bridge`
  once the maintainer tap is live; canonical formula in `packaging/homebrew/`,
  `homebrew-audit` CI job, and [docs/HOMEBREW.md](docs/HOMEBREW.md).

## [0.5.1] - 2026-06-08

First PyPI release. Ships everything below.

### Added
- **Homebrew formula (#37).** macOS install via `brew install abhinaykrupa/tap/cowork-to-code-bridge`
  once the maintainer tap repo exists; canonical formula in `packaging/homebrew/`,
  demo tap at `EagleEye-0101/tap`, and [docs/HOMEBREW.md](docs/HOMEBREW.md).
- **`docker_logs.sh` starter script (#21).** Tail a container's logs (`CONTAINER`
  required, optional line count default 50). Clear errors when Docker is
  unavailable or the container does not exist. Wired into install, README, and
  skill table.
- **Plan approval gate (#48).** Optional `approve_plan.sh` hook: if present, the
  daemon runs it with the task's `plan` text on stdin before executing. Exit 0
  proceeds; non-zero rejects and returns the hook's message to Cowork. Hook
  absent = silent no-op. Ships as a no-op template with pattern-blocking,
  notification, and interactive-approval sections to uncomment.
- **Four new starter scripts (#29, #55, #11, #57).**
  `list_scripts.sh` (discover every runnable script with descriptions),
  `env_check.sh` (PATH / BRIDGE_ROOT / CLAUDE_FLAGS / claude-CLI snapshot that
  never prints the token value), `disk_hogs.sh` (biggest files/dirs in a path,
  with arg validation), and `open_browser.sh` (open an http(s)/localhost URL;
  rejects `file://` and bare paths).
- **SECURITY.md.** Coordinated-disclosure policy + a "what it can / cannot do to
  your machine" table and honest threat model. Lights up the GitHub Security tab.
- **"How it compares" README section (#39).** Honest table vs Cowork alone,
  Claude Code on the web, Remote Control, MCP, SSH/self-hosted, and this bridge —
  including the cases where you don't need the bridge.
- **Custom social-preview card.** `docs/social-card.png` (1280×640) so shared
  GitHub links render a real card instead of a gray box.
- **Linux without systemd (#18).** Containers and minimal distros without a
  working `systemctl --user` bus install via a manual daemon path: `setsid` or
  `nohup`, PID file, optional `@reboot` cron, and `start-daemon.sh`. See
  [docs/LINUX-NO-SYSTEMD.md](docs/LINUX-NO-SYSTEMD.md). WSL without systemd
  still requires enabling systemd.
- **Reverse direction (Claude Code → Cowork), v1 async inbox (#34).**
  `request_cowork.sh` lets Claude Code on the machine drop a request into
  `BRIDGE_ROOT/to_cowork/`; a Cowork session picks it up next time one is open
  and checks its inbox (skill Step 4), optionally writing a reply to
  `cowork_results/`. Optional `--wait SECONDS` polls for the reply. Honest
  limitation documented: this is an async hand-off, not a live channel —
  Cowork can't be woken from the machine (no inbound address to the sandbox).
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
