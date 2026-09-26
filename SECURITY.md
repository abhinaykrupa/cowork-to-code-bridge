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

**New install, hardened:**

```bash
curl -fsSL https://raw.githubusercontent.com/abhinaykrupa/cowork-to-code-bridge/main/install.sh | BRIDGE_HARDENED=1 bash
```

Scripts go to `~/.bridge-scripts/` (override with `BRIDGE_SCRIPTS_DIR=...`), the
service definition records it as `BRIDGE_SCRIPTS`, and on non-systemd Linux the
`@reboot` starter and the library it sources move to
`~/.local/share/cowork-to-code-bridge/` — both are executed by the host, so they
must not sit in the sandbox-writable mount either. Re-running the installer with
`BRIDGE_HARDENED=1` converts an existing install; it keeps your token and warns
about any scripts left in the old `scripts/` folder, which the daemon then ignores.

The uninstaller removes the hardened scripts directory **only if it carries the
marker file the installer wrote**, so pointing `BRIDGE_SCRIPTS_DIR` at a
directory of your own never gets it deleted.

Verified in CI by `.github/workflows/install-e2e.yml`, which does a real
hardened install on a clean runner, plants a script inside the mount, confirms
it is refused, and checks the uninstaller leaves nothing behind.

**Converting by hand** (equivalent): move the scripts out, then set `BRIDGE_SCRIPTS`
in the **service definition** — not in `.env`, which the sandbox can write and
which the daemon ignores for `BRIDGE_*` settings:

```bash
mkdir -p ~/.bridge-scripts && chmod 700 ~/.bridge-scripts
mv ~/.cowork-to-code-bridge/scripts/* ~/.bridge-scripts/
```

macOS — add to `EnvironmentVariables` in
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

## Known limits

Things the bridge does **not** currently guarantee, stated so nobody has to find
them the hard way:

- **A process that leaves its process group survives cancellation and timeout.**
  The daemon starts each task in a new session and signals that whole group —
  SIGTERM, then SIGKILL after `BRIDGE_CANCEL_GRACE_SEC`. A descendant that calls
  `setsid()` (or double-forks into a new session) is no longer in the group and
  keeps running. On Linux, cgroups v2 `cgroup.kill` would close this; macOS has
  no equivalent, so it is documented rather than papered over.
- **The shared folder must be a local bind mount, not a sync tool.** Atomicity
  relies on `rename()` within one filesystem. Syncthing, Dropbox, iCloud Drive
  and similar can surface a file before its contents have arrived, or deliver
  the rename and the payload out of order.
- **No kernel-level confinement of tasks.** Scripts run with your full user
  permissions; nothing masks `~/.ssh` or `~/.aws` from them. Landlock and user
  namespaces would be the Linux answer; macOS has neither (`sandbox-exec` is
  deprecated). Output redaction is best-effort and is not a substitute.
- **One daemon per bridge root.** In-flight claims are resolved at daemon
  startup, which is only correct when a single daemon owns the queue. Running
  two against the same root is unsupported.

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
