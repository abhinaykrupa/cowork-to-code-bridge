# CLAUDE.md — cowork-to-code-bridge

Async file-based RPC between a Cowork sandbox and the user's own machine. A Cowork
session queues work; a local daemon runs it on the Mac/Linux box and returns
results through a shared bind-mounted directory (`BRIDGE_ROOT`).

## First connection — read this

When the bridge client loads, **check whether this is a first connection and, if
so, read the initialization knowledge base** before doing anything else:

```python
from cowork_to_code_bridge.bridge_init import (
    is_first_connection, get_bridge_context,
    get_initialization_message, mark_bridge_initialized,
)

if is_first_connection():
    print(get_initialization_message())  # friendly intro for the user
    print(get_bridge_context())          # load capabilities into context
    mark_bridge_initialized()            # shown once per machine
```

The full reference is in [`docs/BRIDGE_INIT.md`](docs/BRIDGE_INIT.md) — and the
identical content is available programmatically via `get_bridge_context()` so it
works even when `docs/` isn't mounted into the sandbox.

Initialization functions live in
[`cowork_to_code_bridge/bridge_init.py`](cowork_to_code_bridge/bridge_init.py):
`get_bridge_context()`, `is_first_connection()`, `mark_bridge_initialized()`,
`get_initialization_message()`. They are agnostic, idempotent, and non-blocking.

## Core functions (in `cowork_to_code_bridge/client.py`)

| Function | Blocking? | Use |
|----------|-----------|-----|
| `call_remote` | yes | run and wait for result |
| `queue_task` | no | fire-and-forget; returns `task_id` |
| `poll_task_result` | no (idempotent) | check a queued task |
| `cancel_task` | no (idempotent) | stop a queued/running task |
| `post_message_to_cowork` | no | machine → Cowork update |
| `detect_messages_from_claude_code` | no (idempotent) | read those updates |

**Rule of thumb:** if work might take longer than ~30s, `queue_task` it rather
than blocking with `call_remote`. Pass an `idempotency_key` for state-changing
work so retries don't double-fire.

**Cancelling.** `cancel_task(task_id)` writes `cancel/<id>.json`. A task cancelled
while still queued never executes; a running one gets SIGTERM to its whole process
group, then SIGKILL after `BRIDGE_CANCEL_GRACE_SEC` (5s). Either way the daemon
writes a normal result with `exit_code=-5` and `cancelled: True`, so
`poll_task_result` reports it like any other completion.

**Daemon exit codes:** `-2` timeout, `-3` failed to spawn, `-4` daemon crashed
mid-execution (never retried), `-5` cancelled, `-6` expired in the queue.

**Expiry.** `timeout` bounds how long a task *runs*; `max_age_sec` bounds how
long it may *wait*. If the daemon is down (asleep, rebooted) the backlog would
otherwise all execute on restart — hours late, after the caller gave up, which
for a "deploy" or "push" is worse than never running. Past `now - ts_submitted >
max_age`, the daemon skips execution and writes a normal result with
`exit_code=-6` and `cancelled`-style `expired: True`. The owner's
`BRIDGE_MAX_TASK_AGE_SEC` (default 3600s, `0` disables) is a ceiling a caller can
only tighten. A missing or unparseable `ts_submitted` fails *open* — never
expired — so an older client keeps working.

**Redaction.** Task output is scrubbed on the write path — result file, progress
log, and status line all live under `BRIDGE_ROOT`, so all three are covered. The
daemon's own `BRIDGE_TOKEN` is redacted with certainty; vendor key prefixes,
`Authorization:` headers, inline URL passwords, private-key blocks, and long
values assigned to key-ish names are matched heuristically. Secrets become
`[redacted:<kind>]` (ASCII, so `json.dumps` doesn't escape it). `BRIDGE_REDACT=0`
disables it for debugging. **Best-effort:** an unrecognised secret shape, or one
split across two lines, passes through — see SECURITY.md.

**Bounded output.** stdout/stderr are capped at `BRIDGE_MAX_OUTPUT_BYTES` (64 KiB)
while streaming, keeping the tail. When output is dropped the result carries
`stdout_truncated` / `stdout_total_bytes` (and the stderr pair) — absent otherwise,
so don't treat their absence as "no output".


## Model-tiered delegation (hard rule — applies to every conversation, Abhi 2026-07-02)

Never burn frontier-model quota on work a cheaper tier handles. Every subagent/Task
delegation MUST carry a model override:

| Tier | Model | Use for |
|---|---|---|
| 0 | no LLM | polling, status checks, test runs, deploys — scripts only |
| 1 | haiku | triage, summaries, classification, boilerplate |
| 2 | sonnet (DEFAULT for delegation) | coding, tests, refactors, debugging, PR fixes |
| 3 | opus | multi-file design, architecture, tricky cross-module debugging |
| 4 | frontier (main thread) | orchestration, synthesis, verifying workers' diffs, high-stakes decisions |

Verification at a higher tier is MANDATORY on every delegated result. Fallback: retry
once same tier -> escalate one tier -> after 2 escalations stop and ask the human.
Never a single lane, never silent.
