# Bridge Initialization — Knowledge Base for First-Time Users

This is what a Cowork session needs to know the first time it connects to the
bridge. Read it once, then get to work. The same content is available
programmatically via `get_bridge_context()` (see
[`cowork_to_code_bridge/bridge_init.py`](../cowork_to_code_bridge/bridge_init.py))
so it travels with the package even when this file isn't mounted into the sandbox.

---

## 1. What the bridge is

You are a **Cowork session**. The bridge connects you to **Claude Code running on
the user's own machine** (macOS or Linux) through a small file-based daemon. Tasks
that need the real computer run *there*; results come back *here*.

There is no network call from your side. Everything moves through a shared
bind-mounted directory (`BRIDGE_ROOT`) containing `queue/`, `results/`, and
`to_cowork/`. The bridge is **idempotent** and **survives reboots**.

### Capabilities
| You can…                         | Examples                                  |
|----------------------------------|-------------------------------------------|
| Run scripts / commands           | any whitelisted script on the machine     |
| Build / run / test apps          | `npm run build`, `pytest`, app launch     |
| Use git against local repos      | push, pull, status, rebase                |
| Install packages                 | npm, pip, brew, docker                     |
| Inspect machine health           | RAM, disk, processes                       |
| Pass messages both ways          | Cowork ↔ Claude Code                       |

---

## 2. First-connection flow

```python
from cowork_to_code_bridge.bridge_init import (
    is_first_connection, get_bridge_context,
    get_initialization_message, mark_bridge_initialized,
)

if is_first_connection():
    print(get_initialization_message())  # friendly intro for the user
    print(get_bridge_context())          # load capabilities into context
    mark_bridge_initialized()            # remember — shown once per machine
```

- `is_first_connection()` — `True` until the machine is initialized. Pure read.
- `get_bridge_context()` — the full reference (this document, inlined). Pure.
- `get_initialization_message()` — short user-facing intro. Pure.
- `mark_bridge_initialized()` — drops a `.bridge_initialized` marker in
  `BRIDGE_ROOT`. **Idempotent**: safe to call repeatedly; the original timestamp
  is preserved. The write is atomic.

The marker lives in the ephemeral bridge state directory (gitignored) — never in
the repo — so it's per-machine, not per-clone.

---

## 3. Function reference

### `call_remote(script, args=None, timeout=60, ...)` — **blocking**
Run a script and wait for it. Returns `{exit_code, stdout, stderr, ...}`. Use when
you need the answer now and the work fits inside your sandbox timeout.

### `queue_task(script, args=None, timeout=60, idempotency_key=None, ...)` — **non-blocking**
Queue a task and return immediately: `{task_id, status:"queued", timestamp}`. Use
for long-running work or short sandbox timeouts. Pair with `poll_task_result`.

### `poll_task_result(task_id)` — **non-blocking, idempotent**
Check on a queued task. `status` ∈ `{"queued", "running", "completed", "unknown"}`;
on `"completed"` the dict also carries the full result. Safe to call repeatedly.
While `"running"` it also surfaces the daemon's live ticker (written every ~2s):
`elapsed_s`, `last_line`, `state`, plus a pre-rendered `status_line` like
`⣾ Working… 42s elapsed` — show it to the user instead of going silent between polls.

### `call_remote_streaming(script, ..., on_progress=None, on_status=None)` — **blocking, live output**
Like `call_remote`, but streams output while the task runs. `on_progress` receives
each new chunk of stdout/stderr; `on_status` receives the daemon's ~2s status dicts
(`{elapsed_s, last_line, state}`) — feed them to
`format_status_line(status, verb="Building", show_last_line=True)` for a
spinner/elapsed ticker. Same result dict and idempotency guarantees as
`call_remote`. Use for builds/test runs where waiting blind is unacceptable.

### `post_message_to_cowork(message_type, content, parent_task_id=None)`
Machine side → Cowork. `message_type` ∈ `{"progress","completed","error","info"}`.
Returns a `request_id`.

### `detect_messages_from_claude_code(parent_task_id=None)` — **idempotent**
Read messages Claude Code posted back. Optional `parent_task_id` filter. Returns a
list (empty if none). Safe to poll.

---

## 4. MODEL ROUTING — Mandatory Complexity Declaration

**Every task requires an explicit `model_preference` parameter.** This is not optional.
The bridge routes to the right Claude model tier (Haiku, Sonnet, Opus, Fable) based on
task complexity. You declare the tier; the bridge handles cascading fallbacks if needed.

### Why mandatory?

- **Token efficiency**: Use the cheapest model that handles the task. Haiku for quick
  lookups, Sonnet for standard work, Opus for complex reasoning.
- **Cost transparency**: You control what gets sent where. Every routed task records
  which model was selected and why.
- **Audit trail**: Full history of routing decisions for cost tracking and learning.

### How to use it

```python
from cowork_to_code_bridge.model_router import route_task

# Explicit model preference — MANDATORY
result = route_task(
    "scripts/analyze.sh",
    args=["quarterly_data.csv"],
    model_preference="sonnet",    # ← REQUIRED: "haiku", "sonnet", "opus", or "fable"
    fallback_strategy="cascade_up"  # optional: cascade up/down if preferred model unavailable
)

print(f"Routed to: {result['selected_model']}")
print(f"Fallback used: {result['fallback_used']}")
```

### Model tiers (cost ↔ capability)

| Tier   | Best for                              | Tokens    |
|--------|---------------------------------------|-----------|
| Haiku  | Quick lookups, formatting, simple tasks | minimal   |
| Sonnet | Standard work, moderate complexity     | moderate  |
| Opus   | Complex reasoning, planning, analysis  | higher    |
| Fable   | Frontier reasoning (future)            | highest   |

### Fallback strategies

- **`cascade_up`** (default): if preferred unavailable, try higher tiers. Haiku → Sonnet → Opus → Fable.
- **`cascade_down`**: if preferred unavailable, try lower tiers. Opus → Sonnet → Haiku.
- **`fail_fast`**: no fallback; error if preferred tier unavailable.

### What the router tracks

Each routed task stores a routing decision record:

```python
{
  "requested_model": "haiku",           # what you asked for
  "selected_model": "sonnet",           # what was actually used (may differ if fallback)
  "fallback_strategy": "cascade_up",    # how to handle unavailability
  "cascade_order": [...],               # full list of tiers to try
  "fallback_used": true,                # did we fall back?
  "attempted_models": ["haiku","sonnet"], # which models were tried
  "ts_routed": 1716067200               # when the decision was made
}
```

Retrieve routing metadata later:

```python
from cowork_to_code_bridge.model_router import get_routing_metadata
metadata = get_routing_metadata(task_id, bridge_root=...)
print(f"Cost: {metadata['selected_model']}")
```

### Errors if you forget

Missing `model_preference` raises `ValueError`:

```
model_preference is MANDATORY. Specify 'haiku', 'sonnet', 'opus', or 'fable'.
See BRIDGE_INIT.md for routing requirements.
```

---

## 6. When to use each

| Goal                                 | Use                                |
|--------------------------------------|------------------------------------|
| Quick command, need result now       | `call_remote`                      |
| Long build/test, or short timeout    | `queue_task` + `poll_task_result`  |
| Watch a long task's output live      | `call_remote_streaming`            |
| Avoid duplicate runs on retry        | `queue_task(idempotency_key=...)`  |
| Machine reports progress to Cowork    | `post_message_to_cowork`           |
| Cowork reads machine updates          | `detect_messages_from_claude_code` |
| Token-efficient model selection      | `route_task(model_preference=...)`  |

---

## 7. Async vs blocking

| | Blocking (`call_remote`) | Async (`queue_task` → `poll_task_result`) |
|---|---|---|
| Calls | one call, one result | queue, return, poll later |
| Best for | quick commands | slow / uncertain work |
| Risk | dies if work outlives sandbox timeout | none — task runs on the machine regardless |

**Rule of thumb: if it might take longer than ~30s, queue it.**

---

## 8. Idempotency guarantees

- `poll_task_result` and `detect_messages_from_claude_code` are **pure reads** —
  call as often as you like.
- `queue_task(idempotency_key=...)` won't double-execute the same logical task on
  retry.
- `is_first_connection()` only reads; `mark_bridge_initialized()` is safe to call
  repeatedly and preserves the original timestamp.

---

## 9. Common usage patterns

**Blocking — run tests:**
```python
from cowork_to_code_bridge import call_remote
r = call_remote("scripts/run_tests.sh", timeout=120)
print(r["exit_code"], r["stdout"])
```

**Async — long build, poll later:**
```python
from cowork_to_code_bridge.client import queue_task, poll_task_result
job = queue_task("scripts/build.sh", timeout=1800,
                 idempotency_key="build-main-2026-06-18")
# ... later turn ...
res = poll_task_result(job["task_id"])
if res["status"] == "completed":
    print(res["exit_code"], res["stdout"])
```

**Streaming — long build with a live ticker:**
```python
from cowork_to_code_bridge.client import call_remote_streaming, format_status_line
r = call_remote_streaming(
    "scripts/build.sh", timeout=900, idempotency_key="build-main-2026-06-18",
    on_status=lambda s: print(format_status_line(s, verb="Building",
                                                 show_last_line=True)),
)
```

**Bidirectional — watch for progress from the machine:**
```python
from cowork_to_code_bridge.client import detect_messages_from_claude_code
for m in detect_messages_from_claude_code(parent_task_id=job["task_id"]):
    print(m["type"], m["content"])
```

**Model routing — token-efficient task execution:**
```python
from cowork_to_code_bridge.model_router import route_task, get_routing_metadata

# Route to appropriate model tier (MANDATORY model_preference)
result = route_task(
    "scripts/analyze_quarterly_report.sh",
    args=["Q2_2026.pdf"],
    model_preference="opus",         # High complexity: reasoning + analysis
    fallback_strategy="cascade_up"   # Try Opus, then Fable if unavailable
)

# Check which model was actually used
print(f"Used {result['selected_model']} (requested {result['requested_model']})")

# Later: audit the routing decision
metadata = get_routing_metadata(result["task_id"])
print(f"Cost optimized: {metadata['selected_model']} (fallback: {metadata['fallback_used']})")
```

---

## 10. Best practices

- Prefer **`queue_task`** for anything slow; never block your sandbox on a long job.
- Always pass an **`idempotency_key`** for state-changing work (deploys,
  migrations) so retries don't double-fire.
- **Poll, don't spin** — call `poll_task_result` on later turns, not in a tight loop.
- While a task is `"running"`, surface `poll_task_result`'s **`status_line`** (or
  use `call_remote_streaming`'s `on_status`) so the user sees a live spinner, not
  silence.
- Use **`post_message_to_cowork`** from the machine side to stream progress instead
  of going silent during long jobs.
- Treat reads (`poll_*` / `detect_*`) as free and side-effect-free; treat
  `queue_*` / `call_*` as the only things that change state.
