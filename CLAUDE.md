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
| `post_message_to_cowork` | no | machine → Cowork update |
| `detect_messages_from_claude_code` | no (idempotent) | read those updates |

**Rule of thumb:** if work might take longer than ~30s, `queue_task` it rather
than blocking with `call_remote`. Pass an `idempotency_key` for state-changing
work so retries don't double-fire.


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
