# Security Policy

`cowork-to-code-bridge` lets Claude Cowork (a cloud sandbox) trigger work on your
own machine. That is a powerful capability, so the security model is deliberate
and worth understanding before you install. This document is the short version;
the [architecture doc](docs/architecture.md) has the full detail.

## What it can and cannot do to your machine

| | |
|---|---|
| ✅ Runs **only scripts you've approved** | The daemon executes only files in `~/.cowork-to-code-bridge/scripts/`, matched against a strict name pattern. No arbitrary commands, no path traversal (`../`, symlinks out are rejected). |
| ✅ Runs **as you, never `sudo`** | The daemon uses your normal user permissions — it can't escalate, can't read other users' files, can't touch anything you couldn't touch yourself. |
| ✅ **No inbound network listener** | The bridge opens **no ports**. Nothing on the network — local or remote — can connect to it. It only watches a folder on disk. |
| ✅ **Token-gated** | A random 32-char token is generated at install (`chmod 600`, only you can read it) and compared with `hmac.compare_digest`. Requests without the right token are rejected. |
| ✅ **Bounded** | Per-task timeout (default 60s, cap 10min), max queue age (`BRIDGE_MAX_TASK_AGE_SEC`, default 1h), 64 KB stdout/stderr truncation, 1 MB command-size cap. Runaway tasks are killed; huge outputs can't fill your disk; a task that sat in the queue too long is skipped with `exit_code=-6` rather than executing hours late when the daemon wakes up. |
| ✅ **Secrets redacted from output** | Task stdout/stderr is scrubbed on the way to disk — in the result file, the live progress log, and the status line. The daemon's own `BRIDGE_TOKEN` is redacted with certainty; vendor key shapes (`sk-ant-`, `ghp_`, `github_pat_`, `xox*-`, `AKIA…`, `AIza…`), `Authorization:` headers, inline URL passwords, private-key blocks, and long values assigned to key-ish names (`API_KEY=…`) are matched heuristically. Set `BRIDGE_REDACT=0` to disable while debugging your own scripts. **Best-effort — see below.** |
| ✅ **One-command, complete uninstall** | `cowork-to-code-bridge-uninstall` removes the daemon, service registration, scripts folder, and skill. Nothing is left behind. |
| ⚠️ **`run_claude.sh` hands a full agent your machine's access** | The headline script runs a real Claude Code agent that *can* edit, commit, and push. That's the power you want — but scope it with `CLAUDE_FLAGS` (e.g. plan-only, tool allowlist) or the optional [`approve_plan.sh`](examples/allowed_scripts/approve_plan.sh) gate if you want a hard limit. |

## Threats this model does **not** defend against

Stated honestly:

- **A malicious script you wrote yourself.** You authored it, you own its behavior.
- **An attacker who already has write access to your filesystem.** They could write
  directly to the bridge folder or `.env`. The bridge assumes your user account
  is not already compromised.
- **A bug in the daemon itself.** It's open source — read the code, and please
  report anything you find (see below).
- **Every possible secret in task output.** Redaction is *defence in depth, not a
  guarantee.* The daemon's own `BRIDGE_TOKEN` is matched exactly; everything else
  is matched by shape, so an unrecognised credential format, a secret split
  across two output lines, or one that is encoded/re-encoded before printing will
  pass through. Treat `BRIDGE_ROOT` as a directory that may contain sensitive
  output, and don't rely on redaction as a reason to print secrets.

## Reporting a vulnerability

If you find a security issue, **please do not open a public issue.**

- Use GitHub's **[private vulnerability reporting](https://github.com/abhinaykrupa/cowork-to-code-bridge/security/advisories/new)**
  (Security tab → "Report a vulnerability"), **or**
- email the maintainer at **abhinaykrupa@gmail.com** with `SECURITY` in the subject.

Please include: what you found, how to reproduce it, and the impact you see. I aim
to acknowledge within **72 hours** and to ship a fix or a documented mitigation as
fast as a solo maintainer reasonably can. Coordinated disclosure is appreciated —
I'll credit you in the advisory unless you'd prefer to stay anonymous.

## Supported versions

This is a young, single-author project. Security fixes land on `main` and the
latest release. Please run the latest version before reporting.
