# Architecture

## What this connects

The bridge connects **Cowork → Claude Code on the user's Mac**. The primary
flow: Cowork writes a command targeting `scripts/run_claude.sh`, the daemon runs
the local `claude` CLI headless (`claude -p "<task>"`), a real Claude Code agent
does the work on the Mac, and the result is written back for Cowork to read.
Running other approved shell/python scripts directly is the same mechanism with
a different (fixed) script — useful for simple, repeatable actions.

Because Claude Code tasks have side effects, the bridge is **idempotent**: a
command may carry an `idempotency_key`, and a repeat with the same key returns
the cached result instead of re-running. See "Crash resilience" below.

## Why a file-based bridge

Cowork sessions run in a sandbox. From inside Cowork you cannot:

- Open sockets to your Mac shell
- Launch processes outside the sandbox
- Read files outside the bind-mounted project directory
- Use your SSH keys, gh auth, Docker daemon, or `~/.claude.json`

What you *can* do: read and write files in the bind-mount.

The bridge exploits this. A small daemon on your Mac watches a directory for command files written by Cowork. It runs the requested script and writes the result back to a sibling directory. Cowork polls for the result file. Done.

## Components

| Component | Where it runs | Process model |
|---|---|---|
| Daemon (`daemon.py`) | Mac, started by launchd | Long-lived, polls every 1s |
| Client (`client.py`) | Cowork sandbox | Per-call: write JSON, poll for result |
| Whitelisted scripts | `~/.cowork-to-code-bridge/scripts/` on Mac | Spawned per command |

## File layout

```
~/.cowork-to-code-bridge/      ← BRIDGE_ROOT on Mac
├── .env                       ← BRIDGE_TOKEN, chmod 600
├── queue/                     ← Cowork writes here
│   └── 1716937200_abc123.json
├── results/                   ← daemon writes here
│   └── 1716937200_abc123.json
├── processed/                 ← daemon archives completed commands
│   └── 1716937200_abc123.json
├── inflight/                  ← marker per command currently executing
│   └── 1716937200_abc123.running
├── journal.log                ← append-only jsonl event log (crash recovery)
├── scripts/                   ← whitelisted executables
│   ├── ping.sh
│   ├── hello.sh
│   └── your_script.sh
├── daemon.log                 ← stdout
└── daemon.err                 ← stderr
```

When `BRIDGE_ROOT` lives at a path visible to both the Mac and the Cowork bind-mount, this just works. The conventional placement is the user's home directory; Cowork's bind-mount can expose it via a symlink in the project root.

## Command lifecycle

1. **Client (Cowork)** generates `cmd_id = "<unix_ts>_<8hexdig>"`, builds the payload, writes to `queue/<cmd_id>.json.tmp`, renames to `.json` (atomic).
2. **Daemon (Mac)** sees the new file on its next poll, validates token + script path + args.
3. **Daemon** spawns the script with `subprocess.run`, captures stdout/stderr/exit, enforces timeout.
4. **Daemon** writes `results/<cmd_id>.json` atomically (`.tmp` rename).
5. **Daemon** moves `queue/<cmd_id>.json` → `processed/<cmd_id>.json` so it isn't re-run.
6. **Client** polling sees the result file appear, deserializes, returns dict to caller.

## Result schema

```json
{
  "id": "1716937200_abc123",
  "exit_code": 0,
  "stdout": "...",
  "stderr": "...",
  "ts_completed": 1716937201.234,
  "error": "(optional, only on daemon-side failure)"
}
```

Exit code conventions:

| Code | Meaning |
|---|---|
| `0`+ | Script's own exit code |
| `-1` | Daemon refused the command (bad token, bad path, missing script) |
| `-2` | Script ran but exceeded timeout |
| `-3` | Internal daemon error (subprocess crash, etc.) |
| `-4` | Daemon crashed mid-execution; command status indeterminate. Set by the recovery routine on the next startup. The script may or may not have run — treat as ambiguous. |

## Atomicity

Both sides use the `write-tmp + rename` pattern. The daemon only acts on `*.json` (not `*.json.tmp`), so it never reads a partial write. Same for results read by the client.

## Concurrency

The daemon processes queue files in lexicographic order (which, with `<unix_ts>_<rand>` IDs, is roughly submission order). Currently single-threaded — one script at a time. For most ops workloads this is fine; the bottleneck is usually the script itself, not the daemon dispatch.

For higher throughput, the daemon could fork per-command. Not in v0.1.0.

## Failure modes

| Failure | Symptom | Recovery |
|---|---|---|
| Daemon crashed | `call_remote` raises `TimeoutError` | launchd auto-restarts; check `daemon.err` |
| Bind-mount path changed | Client can't find `queue/` | Set `BRIDGE_ROOT` env var explicitly |
| Token mismatch | Result has `exit_code: -1, error: "bridge token mismatch"` | Re-read token from `.env`; restart Cowork session |
| Script missing | Result has `exit_code: -1, error: "script does not exist"` | Add script to `~/.cowork-to-code-bridge/scripts/` and `chmod +x` |
| Disk full | Daemon stops writing results | Free space; processed/ can be cleared safely |

## Crash resilience

The daemon survives both unexpected exits (segfault, OOM kill, user `kill -9`) and full system reboots. Recovery is automatic on the next startup, driven by launchd (`KeepAlive=true`, `RunAtLoad=true`).

### State that must be durable

| Artefact | Purpose | Survives crash? |
|---|---|---|
| `queue/<id>.json` | Pending work | Yes — written by client with atomic `.tmp + rename` |
| `results/<id>.json` | Completed work | Yes — written by daemon with atomic `.tmp + rename` |
| `inflight/<id>.running` | "Daemon is currently running this command" marker | Yes — written with `O_CREAT | fsync` before `subprocess.run`, deleted only after completion |
| `journal.log` | Append-only event log: `received`, `started`, `completed`, `crashed_inflight`, `idempotency_hit` | Yes — each event is `fsync`'d on append |
| `processed/<id>.json` | Audit trail of finished commands | Yes |

### Per-command lifecycle (daemon side)

```
1. read queue/<id>.json
2. journal: received
3. if idempotency_key in cache:
       write results/<id>.json (cached) + journal: idempotency_hit
       → done, NO subprocess executed
4. write inflight/<id>.running  ← crash boundary: anything after this is "in flight"
5. journal: started
6. subprocess.run(...)
7. write results/<id>.json  ← success boundary: the result is durable
8. journal: completed  ← terminal: idempotency cache can now return this
9. delete inflight/<id>.running
10. mv queue/<id>.json → processed/<id>.json
```

### Recovery routine (runs once on daemon startup)

1. Replay `journal.log` to build `{id → terminal_status}` and `{idempotency_key → cached_result}`. Tolerates a truncated last line (power-loss artifact).
2. For each `inflight/*.running` marker:
   - If the id is `completed` in the journal → we crashed between steps 8 and 9; preserve the existing result, just delete the stale marker and move the queue file.
   - Otherwise → we crashed between steps 5 and 7; write `exit_code=-4`, journal `crashed_inflight`, archive the queue file, delete the marker. **Never re-run.** This is the contract that makes non-idempotent ops safe.
3. For each `queue/*.json` whose id is already terminal in the journal, archive it (stale leftover).

### Idempotency

Clients may attach an `idempotency_key` to any command:

```python
call_remote("scripts/deploy.sh", args=["v2.3.1"],
            idempotency_key="deploy-v2.3.1")
```

The daemon executes the script only on the first call. Subsequent calls with the same key return the cached result with `"idempotent_replay": True` and never invoke the script. The cache is rebuilt from `journal.log` on every startup, so it survives reboots and daemon crashes.

This is what makes safe retry possible. If `call_remote` raises `TimeoutError` (network blip, sandbox restart), the client can re-issue the call with the same key and get either the original result (if it finished) or a fresh execution (if it never started) — but never a double execution.

### What is NOT crash-safe

| Concern | Status |
|---|---|
| **Resumable scripts** ("resume execution from where it left off" for partially-run multi-step scripts) | Not in v0.1.0. Scripts that crash partway through are reported as `exit_code=-4` ("indeterminate") and not retried. Building this requires per-script checkpoint logic, which is opt-in work for script authors. |
| **Journal rotation** | Not implemented. Daemon emits a warning when `journal.log` exceeds 10 MB. At current event sizes (~150 bytes/event), 10 MB ≈ 70k commands. Manual archive is safe: stop the daemon, `mv journal.log journal.log.archive`. |
| **Disk full** | Atomic renames fail; the daemon logs the error and the queue file is left in place. Next poll will retry. The system stalls but does not corrupt state. |

## Comparison to alternatives

| Approach | Pros | Cons |
|---|---|---|
| **This bridge** | No network, no listener, survives Cowork sandbox limits | Polling latency (~1s), only works when bind-mount is shared |
| SSH from Cowork | Familiar | Cowork can't open sockets; no key material in sandbox |
| MCP server on Mac | Structured tool definitions | Cowork can't easily reach localhost services |
| Native Anthropic IPC | Would be ideal | Doesn't exist yet (as of v0.1.0) |
| Webhook + ngrok | Works | Heavy setup; exposes Mac to internet |
