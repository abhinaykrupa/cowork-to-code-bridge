# Stateful Long-Running Operations in MCP

## Overview

This document formalizes the **stateful operation pattern** for MCP servers handling long-running, non-blocking tasks. It addresses a key gap in the MCP spec: *how should an MCP server handle operations that outlive a single request/response cycle?*

**Key Problem:** MCP's request/response model assumes quick turnaround. For operations like code generation, testing, or debugging—which may take minutes—the protocol needs explicit semantics for:
- Stable operation IDs for resumption
- Typed waiting states during execution
- Idempotent polling semantics
- Cancellation signaling
- Resume receipts capturing partial progress

This pattern is implemented in `cowork-to-code-bridge` and validated in production (Hermes, Open Claw, Crew.ai).

---

## Core Concepts

### 1. Operation ID (Stable, Idempotent)

Every long-running operation gets a unique, stable identifier.

**Properties:**
- **Immutable** — doesn't change between requests
- **Unique** — no collisions across concurrent operations
- **Opaque to caller** — implementer chooses format (UUID, timestamp-hash, etc.)
- **Resumable** — if connection drops, same ID retrieves same operation state

**Format (recommended):**
```
{server-id}_{unix-timestamp}_{request-hash}_{sequence}
```

Example: `bridge_1718556000_a4f2c1_01`

**Usage:**
```json
{
  "jsonrpc": "2.0",
  "id": 1,
  "method": "tools/call",
  "params": {
    "name": "escalate_to_claude",
    "arguments": {
      "request": "Debug the API failure",
      "wait_seconds": 0,
      "operation_id": null  // Server generates if null
    }
  }
}
```

### 2. Typed Waiting States

An operation progresses through predictable states:

```
┌─────────────┐
│   QUEUED    │  Operation accepted, awaiting execution
└──────┬──────┘
       │
       ▼
┌─────────────┐
│  EXECUTING  │  Operation in progress (sub-states possible)
└──────┬──────┘
       │
       ├─────────▶ ┌─────────────┐
       │           │  COMPLETED  │  Finished with result
       │           └─────────────┘
       │
       └─────────▶ ┌─────────────┐
                   │   ERROR     │  Failed with error
                   └─────────────┘
```

**State Schema:**

```typescript
interface OperationState {
  operation_id: string;
  status: "queued" | "executing" | "completed" | "error" | "cancelled";
  created_at: number;           // unix timestamp
  updated_at: number;
  progress?: {
    step: string;               // human-readable phase
    percent_complete: number;   // 0-100, null if indeterminate
    message?: string;
  };
  result?: any;                 // set when status == "completed"
  error?: {
    code: string;               // error classification
    message: string;
    details?: Record<string, any>;
  };
}
```

### 3. Idempotent Poll Semantics

Polling for operation status must be **fully idempotent** — same request always returns same state.

**Pattern:**
```json
// Request (idempotent — no side effects)
{
  "jsonrpc": "2.0",
  "id": 2,
  "method": "tools/call",
  "params": {
    "name": "get_operation_status",
    "arguments": {
      "operation_id": "bridge_1718556000_a4f2c1_01"
    }
  }
}

// Response (cached if operation is finished)
{
  "jsonrpc": "2.0",
  "id": 2,
  "result": {
    "operation_id": "bridge_1718556000_a4f2c1_01",
    "status": "completed",
    "result": {
      "stdout": "...",
      "exit_code": 0
    },
    "completed_at": 1718556180
  }
}
```

**Guarantees:**
- ✅ Same operation_id always returns same state (until it transitions)
- ✅ Multiple concurrent polls don't cause duplicate work
- ✅ Polls don't have side effects (read-only)
- ✅ Network retries are safe

### 4. Cancellation Signaling

Operations can be cancelled if the caller changes its mind.

**Pattern:**
```json
// Request
{
  "jsonrpc": "2.0",
  "id": 3,
  "method": "tools/call",
  "params": {
    "name": "cancel_operation",
    "arguments": {
      "operation_id": "bridge_1718556000_a4f2c1_01",
      "reason": "Caller timeout exceeded"
    }
  }
}

// Response
{
  "jsonrpc": "2.0",
  "id": 3,
  "result": {
    "operation_id": "bridge_1718556000_a4f2c1_01",
    "status": "cancelled",
    "cancelled_at": 1718556120,
    "reason": "Caller timeout exceeded"
  }
}
```

**Semantics:**
- **Before execution starts:** Operation skips immediately, state → "cancelled"
- **During execution:** Server begins graceful shutdown (SIGTERM, not SIGKILL)
- **After completion:** Cancellation request is idempotent (no change)

### 5. Resume Receipt (Partial Progress)

When an operation is paused or interrupted, the resume receipt captures enough state to resume.

**Pattern:**
```json
{
  "operation_id": "bridge_1718556000_a4f2c1_01",
  "status": "executing",
  "resume_receipt": {
    "checkpoint_id": "chk_67890",
    "context": {
      "last_completed_step": "code_generation",
      "generated_code": "def foo():\n  pass",
      "test_results": {...}
    },
    "next_steps": [
      "run_linter",
      "run_tests",
      "commit"
    ],
    "can_resume": true,
    "resume_from": "run_linter"
  }
}
```

**Use cases:**
- Agent disconnects mid-operation → resume from checkpoint
- Timeout on first try → resume with context
- Multi-stage workflows → pause between stages

---

## Implementation: cowork-to-code-bridge

### Tool: `escalate_to_claude` (with stateful semantics)

```json
{
  "name": "escalate_to_claude",
  "description": "Hand a task to Claude Code; track execution asynchronously",
  "inputSchema": {
    "type": "object",
    "properties": {
      "request": {
        "type": "string",
        "description": "Task to delegate to Claude Code"
      },
      "wait_seconds": {
        "type": "integer",
        "default": 0,
        "description": "Max time to wait for result (0 = return immediately with operation_id)"
      },
      "operation_id": {
        "type": "string",
        "nullable": true,
        "description": "Resume an existing operation; null = create new"
      }
    },
    "required": ["request"]
  }
}
```

### Tool: `get_operation_status` (NEW)

```json
{
  "name": "get_operation_status",
  "description": "Check status of a long-running operation",
  "inputSchema": {
    "type": "object",
    "properties": {
      "operation_id": {
        "type": "string",
        "description": "Operation ID to poll"
      }
    },
    "required": ["operation_id"]
  }
}
```

### Tool: `cancel_operation` (NEW)

```json
{
  "name": "cancel_operation",
  "description": "Cancel a running operation",
  "inputSchema": {
    "type": "object",
    "properties": {
      "operation_id": {
        "type": "string",
        "description": "Operation to cancel"
      },
      "reason": {
        "type": "string",
        "description": "Reason for cancellation"
      }
    },
    "required": ["operation_id"]
  }
}
```

### File Structure

**Queue (in `~/.cowork-to-code-bridge/`):**
```
queue/
  op_bridge_1718556000_a4f2c1_01.json      # Pending operation
  
operations/
  bridge_1718556000_a4f2c1_01.json         # State + checkpoint
  bridge_1718556000_a4f2c1_01.log          # Streaming output
  
results/
  bridge_1718556000_a4f2c1_01.json         # Final result (cached)
```

**Operation State File:**
```json
{
  "operation_id": "bridge_1718556000_a4f2c1_01",
  "status": "executing",
  "created_at": 1718556000,
  "updated_at": 1718556045,
  "request": "Debug the API failure",
  "progress": {
    "step": "Running tests...",
    "percent_complete": 65,
    "message": "Test 4/6 passed"
  },
  "execution_details": {
    "started_at": 1718556005,
    "pid": 12345
  },
  "resume_receipt": {
    "checkpoint_id": "chk_67890",
    "context": {
      "tests_passed": 4,
      "tests_failed": 0,
      "current_test": "test_api_health"
    },
    "can_resume": true,
    "resume_from": "test_5"
  }
}
```

---

## Design Decisions

### Why File-Based Queue (not in-memory)?

| Factor | File-Based | In-Memory |
|---|---|---|
| **Crash Recovery** | ✅ State survives daemon restart | ❌ Lost on crash |
| **Multi-Process Access** | ✅ Safe via atomic writes | ❌ Requires IPC/mutex |
| **Auditability** | ✅ Full state history on disk | ❌ Hidden in memory |
| **Cross-Tool Integration** | ✅ Scripts, MCPs, direct files all see same state | ❌ MCP-only |

**Decision:** File-based for resilience and auditability.

### Why Polling (not Webhooks)?

| Factor | Polling | Webhooks |
|---|---|---|
| **Complexity** | ✅ Simple (read file) | ❌ Network server, TLS, auth |
| **Firewall-Friendly** | ✅ Works behind NAT/firewall | ❌ Requires inbound port |
| **Late Binding** | ✅ Caller decides when to check | ❌ Must provide callback upfront |
| **Error Recovery** | ✅ Caller controls retry logic | ❌ Lost if callback unreachable |

**Decision:** Polling for simplicity and robustness.

### Why Separate Operation State from Result?

- **Querying during execution** → `operations/<id>.json` has progress, checkpoint
- **After completion** → Both files exist (state is cache-warm)
- **Garbage collection** → Results can be pruned after 7 days; operations kept longer for audit

---

## Usage Patterns

### Pattern 1: Fire-and-Forget (Immediate Return)

```python
# Caller doesn't wait
response = mcp.call_tool("escalate_to_claude", {
    "request": "Run the full test suite",
    "wait_seconds": 0  # Return immediately
})
# response = {
#   "operation_id": "bridge_..._01",
#   "status": "queued"
# }

# Check back later
for i in range(10):
    status = mcp.call_tool("get_operation_status", {
        "operation_id": "bridge_..._01"
    })
    if status["status"] in ["completed", "error"]:
        break
    time.sleep(30)  # Poll every 30s
```

### Pattern 2: Wait with Timeout

```python
# Caller waits up to 300 seconds
response = mcp.call_tool("escalate_to_claude", {
    "request": "Debug the API",
    "wait_seconds": 300  # Block for 5 min max
})
# If server responds before timeout: result is in response["result"]
# If timeout: response["status"] = "executing", response["operation_id"] present
```

### Pattern 3: Resume from Checkpoint

```python
# First attempt timed out; resume with context
response = mcp.call_tool("escalate_to_claude", {
    "request": "Debug the API (resume from checkpoint)",
    "operation_id": "bridge_..._01",  # Same operation_id = resume
    "wait_seconds": 300
})
# Server sees existing operation → uses checkpoint → continues from there
```

### Pattern 4: Graceful Cancellation

```python
# Operation taking too long; cancel it
cancel_response = mcp.call_tool("cancel_operation", {
    "operation_id": "bridge_..._01",
    "reason": "Exceeded caller's SLA"
})
# If not started: immediate cancellation
# If running: SIGTERM sent to process, waits 10s for graceful shutdown
```

---

## Guarantees & Trade-offs

### Guarantees Provided

| Guarantee | Why | Implication |
|---|---|---|
| **Stable Operation IDs** | Deterministic hash of request | Same request = resumable state |
| **Idempotent Polling** | Read-only queries, cached results | Safe to retry, no side effects |
| **Atomic State Transitions** | Write-ahead logging + atomic rename | No partial updates |
| **Crash Recovery** | State preserved to disk | Survives daemon/system restarts |
| **Ordered Execution** | FIFO queue for operations | Fair scheduling, LIFO within operation |

### Trade-offs Accepted

| Trade-off | Why | When It Matters |
|---|---|---|
| **No Real-Time Push** | Polling is simpler, more robust | Latency-sensitive apps (100ms deadline) |
| **No Shared Memory** | File-based state is slower | >1000 concurrent operations |
| **Timeout Always Finishes** | Can't distinguish "slow" from "stuck" | Need SLA < operation's natural duration |
| **Cancellation Is Best-Effort** | No guarantee process stops immediately | Safety-critical operations |

---

## Extensibility

### Adding Progress Callbacks

Future: Agent can write progress deltas to `operations/<id>.log`, streamed to caller.

```json
// Streamed line-by-line
{"event": "step_started", "step": "code_generation", "timestamp": 1718556010}
{"event": "step_progress", "percent": 25, "message": "Analyzing error", "timestamp": 1718556015}
{"event": "step_completed", "step": "code_generation", "timestamp": 1718556020}
```

### Adding Rate Limiting

Per-agent quota system (planned for Phase 4):

```json
{
  "operation_id": "bridge_..._01",
  "status": "queued",
  "queue_position": 3,
  "queue_reason": "Rate limit reached: 5/10 operations in progress for agent X",
  "estimated_wait_seconds": 45
}
```

### Adding Sub-Operations

Complex operations can spawn child operations (tree structure):

```json
{
  "operation_id": "bridge_..._01",
  "status": "executing",
  "child_operations": [
    "bridge_..._02",  // Generate code
    "bridge_..._03"   // Run tests
  ],
  "progress": {
    "percent_complete": 50,
    "message": "Waiting for child operations"
  }
}
```

---

## Comparison: Other Frameworks

### LangChain RunAsync / AgentExecutor

- ✅ Similar async pattern (queue + poll)
- ❌ No explicit operation IDs (uses internal refs)
- ❌ No resumption from checkpoint
- ❌ Tightly coupled to LangChain (not portable)

### Crew.ai Tools

- ✅ Tool-based delegation
- ❌ No async semantics (blocks agent)
- ❌ No state persistence
- ❌ Single-threaded execution

### Temporal/Durable Execution Engines

- ✅ Full async + resumption semantics
- ✅ Checkpoint system
- ❌ Heavyweight (requires Temporal server)
- ❌ Learning curve (workflow DSL)

### This Pattern

- ✅ Lightweight (files + simple polling)
- ✅ Explicit operation model (not hidden)
- ✅ First-class checkpoints (resumable)
- ✅ Portable (any MCP client)
- ❌ Manual polling (not event-driven)

---

## Testing Strategy

### Unit Tests

- ✅ Operation ID generation (uniqueness)
- ✅ State transitions (valid paths only)
- ✅ Idempotent polling (same result after multiple calls)
- ✅ Atomic file updates (no corruption)
- ✅ Cancellation (both pre- and during execution)

### Integration Tests

- ✅ End-to-end escalation (MCP → Queue → Agent → Result)
- ✅ Checkpoint recovery (operation resumes with context)
- ✅ Concurrent operations (multiple agents escalate simultaneously)
- ✅ Network failures (dropped connection, retry works)
- ✅ Process death (daemon crashes, state recovered)

---

## Spec Compliance

This pattern extends the **MCP v1.0 specification** (as of June 2026):

| MCP Concept | How Pattern Uses It |
|---|---|
| **tools/call** | Invokes `escalate_to_claude`, `get_operation_status`, `cancel_operation` |
| **Request/Response** | Standard JSONRPC 2.0 wrapping (no changes) |
| **Error Handling** | Uses JSONRPC error codes (-32603, -32601, etc.) |
| **Streaming** | Future: `logs/<operation_id>.log` for progress events |

---

## Reference Implementation

**Files:**
- `cowork_to_code_bridge/mcp_server.py` — MCP server with stateful tools
- `tests/test_mcp_server.py` — Unit + integration tests
- `docs/EXTERNAL_AGENT_INTEGRATION.md` — Integration guide for Hermes/Open Claw
- `examples/hermes-mcp-config.json` — Configuration example

**Status:** Production (v0.5.0+), tested with Hermes, Open Claw, Crew.ai

---

## Further Reading

- [MCP Specification](https://modelcontextprotocol.io/specification)
- [EXTERNAL_AGENT_INTEGRATION.md](./EXTERNAL_AGENT_INTEGRATION.md) — How to use with frameworks
- [MCP_SERVER_IMPLEMENTATION.md](./MCP_SERVER_IMPLEMENTATION.md) — Architecture details
- [SECURITY.md](../SECURITY.md) — Threat model
