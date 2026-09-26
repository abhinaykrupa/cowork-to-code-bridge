# Security Policy

`cowork-to-code-bridge` lets Claude Cowork (a cloud sandbox) trigger work on your
own machine. That is a powerful capability, so the security model is deliberate
and worth understanding before you install. This document is the short version;
the [architecture doc](docs/architecture.md) has the full detail.

## What it can and cannot do to your machine

| | |
|---|---|
| ✅ Runs **only scripts in the allowlist directory** | The daemon executes only files in its scripts directory, matched against a strict name pattern. No arbitrary commands, no path traversal (`../`, symlinks out are rejected). **⚠️ In the default layout that directory is inside the folder Cowork mounts read-write, so the sandbox itself can add scripts to it** — see [Default vs hardened layout](#default-vs-hardened-layout). |
| ✅ Runs **as you, never `sudo`** | The daemon uses your normal user permissions — it can't escalate, can't read other users' files, can't touch anything you couldn't touch yourself. |
| ✅ **No inbound network listener** | The bridge opens **no ports**. Nothing on the network — local or remote — can connect to it. It only watches a folder on disk. |
| ✅ **Token-gated** | A random 32-char token is generated at install (`chmod 600`, only you can read it) and compared with `hmac.compare_digest`. Requests without the right token are rejected. |
| ✅ **Bounded** | Per-task timeout (default 60s, cap 10min), max queue age (`BRIDGE_MAX_TASK_AGE_SEC`, default 1h), 64 KB stdout/stderr truncation, 1 MB command-size cap. Runaway tasks are killed; huge outputs can't fill your disk; a task that sat in the queue too long is skipped with `exit_code=-6` rather than executing hours late when the daemon wakes up. |
| ✅ **Secrets redacted from output** | Task stdout/stderr is scrubbed on the way to disk — in the result file, the live progress log, and the status line. The daemon's own `BRIDGE_TOKEN` is redacted with certainty; vendor key shapes (`sk-ant-`, `ghp_`, `github_pat_`, `xox*-`, `AKIA…`, `AIza…`), `Authorization:` headers, inline URL passwords, private-key blocks, and long values assigned to key-ish names (`API_KEY=…`) are matched heuristically. Set `BRIDGE_REDACT=0` to disable while debugging your own scripts. **Best-effort — see below.** |
| ✅ **Doesn't follow planted links** | The sandbox can create symlinks, FIFOs and hard links anywhere in the shared folder. Every daemon read and write there is anchored on a directory fd opened `O_NOFOLLOW`, temp files get unpredictable names created `O_EXCL`, and non-regular or multiply-linked files are refused — so a planted link can't redirect a daemon write to a file outside the bridge, and a FIFO can't hang it. |
| ✅ **Caller environment is filtered** | A task's `env` and the shared `.env` can only *add* conventional upper-case variables. They can never replace a variable the daemon's own process has, and names that change which code runs, which config loads, or where traffic goes (`PATH`, `BASH_ENV`, `LD_*`, `DYLD_*`, `PYTHON*`, `NODE_OPTIONS`, `GIT_*`, `AWS_*`, proxies, …) are dropped and reported in `env_rejected`. Set `BRIDGE_CALLER_ENV=0` in the service definition to ignore caller env entirely. Children get `stdin` from `/dev/null`. |
| ✅ **One-command, complete uninstall** | `cowork-to-code-bridge-uninstall` removes the daemon, service registration, scripts folder, and skill. Nothing is left behind. |
| ⚠️ **`run_claude.sh` hands a full agent your machine's access** | The headline script runs a real Claude Code agent that *can* edit, commit, and push. That's the power you want — but scope it with `CLAUDE_FLAGS` (e.g. plan-only, tool allowlist) or the optional [`approve_plan.sh`](examples/allowed_scripts/approve_plan.sh) gate if you want a hard limit. |

## Threats this model does **not** defend against

Stated honestly:

- **A malicious script you wrote yourself.** You authored it, you own its behavior.
- **An attacker who already has write access to your filesystem.** They could write
  directly to the bridge folder or `.env`. The bridge assumes your user account
  is not already compromised.
- **A compromised sandbox, in the default layout.** The Cowork session mounts the
  whole bridge folder read-write — it has to, to queue tasks — and it reads the
  token from `.env` to authenticate. In the default layout the scripts directory
  is inside that folder, so a sandbox that is compromised (for example by prompt
  injection) can add its own script and run it. The allowlist in the default
  layout stops the *model* from running an unapproved command through the
  API; it does not stop a sandbox with filesystem access. Use the hardened layout
  below if that distinction matters to you.
- **A bug in the daemon itself.** It's open source — read the code, and please
  report anything you find (see below).
- **Every possible secret in task output.** Redaction is *defence in depth, not a
  guarantee.* The daemon's own `BRIDGE_TOKEN` is matched exactly; everything else
  is matched by shape, so an unrecognised credential format, a secret split
  across two output lines, or one that is encoded/re-encoded before printing will
  pass through. Treat `BRIDGE_ROOT` as a directory that may contain sensitive
  output, and don't rely on redaction as a reason to print secrets.

## Default vs hardened layout

| | Default | Hardened |
|---|---|---|
| Scripts directory | `~/.cowork-to-code-bridge/scripts/` — **inside** the mounted folder | Any directory **outside** it, e.g. `~/.bridge-scripts/` |
| Can the sandbox add a script? | Yes, by writing a file | No |
| What bounds a compromised sandbox | Nothing beyond your user account | The allowlist, `BRIDGE_PERMISSION_CEILING`, the caller-env filter, and link-safe I/O |

To harden an existing install, move the scripts and point the daemon at them from
its **service definition** — not from `.env`, which the sandbox can write (and
which the daemon ignores for `BRIDGE_*` settings for that reason):

```bash
mkdir -p ~/.bridge-scripts && chmod 700 ~/.bridge-scripts
mv ~/.cowork-to-code-bridge/scripts/* ~/.bridge-scripts/
```

macOS — add to the `EnvironmentVariables` dict in
`~/Library/LaunchAgents/dev.cowork-to-code-bridge.daemon.plist`, then reload:

```xml
<key>BRIDGE_SCRIPTS</key><string>/Users/you/.bridge-scripts</string>
<key>BRIDGE_PERMISSION_CEILING</key><string>edit</string>
```

Linux — add to the `[Service]` section of the systemd user unit:

```ini
Environment=BRIDGE_SCRIPTS=%h/.bridge-scripts
Environment=BRIDGE_PERMISSION_CEILING=edit
```

The layout is verified by `tests/test_env_injection.py::test_hardened_layout_ignores_scripts_planted_in_the_mount`.
Installer support for choosing it at install time is not built yet.

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
