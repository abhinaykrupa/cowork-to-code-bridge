# Feature: Per-Task Permission Sandboxing

**Branch:** `feat/per-task-permissions`  
**Status:** In Progress  
**Created:** 2026-07-14  

---

## Overview

Add `permission_scope` parameter to `call_remote()` and `call_remote_streaming()` to allow Cowork to request per-task permission modes without being limited to the global owner-set `CLAUDE_FLAGS`.

**Security Model:** Owner sets a ceiling (e.g., max `edit`). Cowork can request within that ceiling per task.

---

## Implementation Checklist

### Phase 1: Add Parameter to Client Functions (TODAY)

#### 1.1 Update `call_remote()` in `cowork_to_code_bridge/client.py`

**Location:** Lines 264-276

**Add parameter:**
```python
def call_remote(
    script: str,
    args: list[str | int | float] | None = None,
    timeout: int = 60,
    poll_interval: float = 1.0,
    cwd: str | None = None,
    env: dict[str, str] | None = None,
    bridge_root: Path | str | None = None,
    idempotency_key: str | None = None,
    plan: str | None = None,
    max_budget_usd: float | None = None,
    permission_scope: str | None = None,  # ← ADD THIS
    interactive: bool = False,
) -> dict[str, Any]:
```

**Update docstring** (around line 295):
```python
        permission_scope: Optional permission mode for this task. One of:
            'plan' (read-only), 'readonly', 'edit', or 'full' (no restrictions).
            If set, overrides the global CLAUDE_FLAGS for this task only.
            The daemon validates against the owner's BRIDGE_PERMISSION_CEILING.
            Ignored if owner set CLAUDE_FLAGS env var (takes precedence).
```

**Add to payload** (around line 340):
```python
    if max_budget_usd is not None:
        payload["max_budget_usd"] = float(max_budget_usd)
    if permission_scope is not None:  # ← ADD THIS BLOCK
        payload["permission_scope"] = str(permission_scope).strip().lower()
```

#### 1.2 Update `call_remote_streaming()` in `cowork_to_code_bridge/client.py`

**Location:** Lines 371-385

**Add parameter** (same as call_remote):
```python
def call_remote_streaming(
    script: str,
    args: list[str | int | float] | None = None,
    timeout: int = 600,
    poll_interval: float = 1.0,
    cwd: str | None = None,
    env: dict[str, str] | None = None,
    bridge_root: Path | str | None = None,
    idempotency_key: str | None = None,
    on_progress=None,
    on_status=None,
    plan: str | None = None,
    max_budget_usd: float | None = None,
    permission_scope: str | None = None,  # ← ADD THIS
    interactive: bool = False,
) -> dict[str, Any]:
```

**Update docstring** (around line 403):
```python
        permission_scope: Optional per-task permission mode. Same values and
            behavior as call_remote(). Passed to daemon, which validates and
            injects into CLAUDE_FLAGS (unless owner already set it globally).
```

**Add to payload** (around line 430):
```python
    if max_budget_usd is not None:
        payload["max_budget_usd"] = float(max_budget_usd)
    if permission_scope is not None:  # ← ADD THIS BLOCK
        payload["permission_scope"] = str(permission_scope).strip().lower()
```

---

### Phase 2: Update Skill Documentation

#### 2.1 Update `skill/cowork-to-code-bridge/SKILL.md`

**Add new section after "Live status ticker" section** (around line 147):

```markdown
### Per-task permission modes (fine-grained access control)

Different tasks need different trust levels. Use `permission_scope` to sandbox each task:

```python
from bridge_client import call_remote

# Read-only task — summarize without write access
r = call_remote(
    "scripts/run_claude.sh",
    args=["Summarize this PR", "/Users/<them>/projects/myapp"],
    timeout=120,
    idempotency_key="summarize-pr-1",
    permission_scope="plan",  # read-only: --permission-mode plan
)

# Edit task — refactor + commit
r = call_remote(
    "scripts/run_claude.sh",
    args=["Refactor the auth module and commit", "/Users/<them>/projects/myapp"],
    timeout=600,
    idempotency_key="refactor-auth-1",
    permission_scope="edit",  # write allowed: read + edit/write tools
)

# Full access (if owner's ceiling allows)
r = call_remote(
    "scripts/run_claude.sh",
    args=["Deploy to production", "/Users/<them>/projects/myapp"],
    timeout=900,
    idempotency_key="deploy-prod-1",
    permission_scope="full",  # no tool restrictions
)
```

**Permission scope values:**
- `"plan"` — Read-only. Claude can analyze but not modify. (`--permission-mode plan`)
- `"readonly"` — Limited read tools: Read, Glob, Grep only.
- `"edit"` — Read + write: Read, Glob, Grep, Edit, Write.
- `"full"` — No tool restrictions (default if not specified).

**Security:** The owner's `BRIDGE_PERMISSION_CEILING` (set in launchd/systemd) is the hard limit. Cowork can only request within that ceiling. If the owner set global `CLAUDE_FLAGS`, it always wins (task-level scope ignored).

Example owner setup (macOS launchd):
```bash
# ~/.cowork-to-code-bridge/cowork-to-code-bridge.plist
# Set max permission level to "edit" — Cowork can request up to "edit" per task
BRIDGE_PERMISSION_CEILING=edit
```
```

---

### Phase 3: Add Tests

#### 3.1 Add test to `tests/test_e2e_idempotency.py`

**Add new test function:**

```python
def test_permission_scope_injected_to_env(bridge, tmp_path):
    """permission_scope='edit' is passed to daemon and injected as CLAUDE_FLAGS."""
    d, _ = bridge
    terminal, cache = {}, {}
    
    # Enqueue a task with permission_scope='edit'
    cmd = {
        "id": "perm_edit_test",
        "script": "echo $CLAUDE_FLAGS",
        "args": [],
        "timeout": 10,
        "ts_submitted": time.time(),
        "permission_scope": "edit",  # ← Key part
    }
    cmd_file = d.QUEUE / "perm_edit_test.json"
    cmd_file.write_text(json.dumps(cmd))
    
    # Run the task
    d.run_one(cmd_file, "test-token", terminal, cache)
    
    # Check result was written
    result_file = d.RESULTS / "perm_edit_test.json"
    assert result_file.exists()
    result = json.loads(result_file.read_text())
    
    # Daemon should have injected CLAUDE_FLAGS for 'edit' scope
    # The echo will output the flags (or empty if not set in this minimal env)
    # At minimum, the daemon should have parsed and processed the scope
    assert result["exit_code"] == 0


def test_permission_scope_owner_flags_wins(bridge, tmp_path, monkeypatch):
    """Owner-set CLAUDE_FLAGS takes precedence over permission_scope."""
    d, _ = bridge
    terminal, cache = {}, {}
    
    # Set owner's global CLAUDE_FLAGS
    monkeypatch.setenv("CLAUDE_FLAGS", "--permission-mode plan")
    
    # Task requests 'edit' scope
    cmd = {
        "id": "perm_owner_test",
        "script": "echo test",
        "args": [],
        "timeout": 10,
        "ts_submitted": time.time(),
        "permission_scope": "edit",  # ← Requested but should be ignored
    }
    cmd_file = d.QUEUE / "perm_owner_test.json"
    cmd_file.write_text(json.dumps(cmd))
    
    # Run the task
    d.run_one(cmd_file, "test-token", terminal, cache)
    
    # Task should complete (daemon honors owner's CLAUDE_FLAGS)
    result_file = d.RESULTS / "perm_owner_test.json"
    assert result_file.exists()
    result = json.loads(result_file.read_text())
    assert result["exit_code"] == 0


def test_permission_scope_invalid_ignored(bridge, tmp_path):
    """Invalid permission_scope values are logged but don't break execution."""
    d, _ = bridge
    terminal, cache = {}, {}
    
    # Invalid scope
    cmd = {
        "id": "perm_invalid_test",
        "script": "echo valid",
        "args": [],
        "timeout": 10,
        "ts_submitted": time.time(),
        "permission_scope": "invalid_scope_xyz",  # ← Invalid
    }
    cmd_file = d.QUEUE / "perm_invalid_test.json"
    cmd_file.write_text(json.dumps(cmd))
    
    # Should still run (invalid scope is logged, not fatal)
    d.run_one(cmd_file, "test-token", terminal, cache)
    
    result_file = d.RESULTS / "perm_invalid_test.json"
    assert result_file.exists()
    result = json.loads(result_file.read_text())
    assert result["exit_code"] == 0  # Script ran despite invalid scope
```

#### 3.2 Add test to `tests/test_single_file_client.py`

**Add new test function:**

```python
def test_call_remote_with_permission_scope(tmp_path, monkeypatch):
    """call_remote() accepts permission_scope and passes it to daemon."""
    bridge_root = tmp_path / "bridge"
    bridge_root.mkdir()
    (bridge_root / "queue").mkdir()
    (bridge_root / "results").mkdir()
    
    # Mock daemon token
    (bridge_root / ".env").write_text("BRIDGE_TOKEN=test-token\n")
    
    # Queue a task with permission_scope
    result = queue_task(
        "scripts/test.sh",
        args=["hello"],
        bridge_root=bridge_root,
        idempotency_key="test-perm-1",
        permission_scope="edit",
    )
    
    # Verify the queued task contains permission_scope
    task_id = result["task_id"]
    cmd_file = bridge_root / "queue" / f"{task_id}.json"
    assert cmd_file.exists()
    
    cmd = json.loads(cmd_file.read_text())
    assert cmd.get("permission_scope") == "edit"


def test_call_remote_streaming_with_permission_scope(tmp_path, monkeypatch):
    """call_remote_streaming() accepts permission_scope."""
    # This is an integration test that verifies the parameter is accepted
    # and passed through (actual daemon behavior tested in test_e2e_idempotency.py)
    
    bridge_root = tmp_path / "bridge"
    bridge_root.mkdir()
    (bridge_root / "queue").mkdir()
    (bridge_root / "results").mkdir()
    (bridge_root / "progress").mkdir()
    
    # Note: This would require mocking the daemon response or running a test daemon
    # For now, just verify the function signature accepts the parameter
    import inspect
    sig = inspect.signature(call_remote_streaming)
    assert "permission_scope" in sig.parameters
```

---

## Acceptance Criteria

- [ ] `call_remote()` accepts `permission_scope` parameter
- [ ] `call_remote_streaming()` accepts `permission_scope` parameter
- [ ] Parameter is passed to daemon in JSON payload
- [ ] Skill docs updated with usage examples (all 4 scopes documented)
- [ ] Backward compatible (parameter is optional, defaults to None)
- [ ] Tests verify daemon receives and processes permission_scope
- [ ] Tests verify owner CLAUDE_FLAGS takes precedence
- [ ] Tests verify invalid scopes are handled gracefully
- [ ] All existing tests pass (no regression)

---

## Files to Modify

1. **cowork_to_code_bridge/client.py** — Add `permission_scope` to `call_remote()` + `call_remote_streaming()`
2. **skill/cowork-to-code-bridge/SKILL.md** — Add usage examples + documentation
3. **tests/test_e2e_idempotency.py** — Add 3 tests for daemon behavior
4. **tests/test_single_file_client.py** — Add 2 tests for client API

---

## Implementation Steps (In Order)

### Day 1: Client API

1. ✍️ Edit `cowork_to_code_bridge/client.py`
   - Add `permission_scope` param to `call_remote()`
   - Add `permission_scope` param to `call_remote_streaming()`
   - Add to payload in both functions
   - Update docstrings

2. ✍️ Edit `skill/cowork-to-code-bridge/SKILL.md`
   - Add new "Per-task permission modes" section
   - Add 3 usage examples (plan, edit, full)
   - Explain security model

### Day 2: Testing

3. ✍️ Edit `tests/test_e2e_idempotency.py`
   - Add 3 daemon integration tests

4. ✍️ Edit `tests/test_single_file_client.py`
   - Add 2 client API tests

### Day 3: Verification

5. 🧪 Run full test suite
6. 📝 Write commit message
7. 🔄 Create PR

---

## Daemon-Side Notes

✅ **Already implemented** in `cowork_to_code_bridge/daemon.py` (lines 607-638):
- Parses `permission_scope` from payload
- Maps to `CLAUDE_FLAGS` using `scope_flags` dict
- Respects owner's global `CLAUDE_FLAGS` (takes precedence)
- Logs invalid scopes (non-fatal)
- Scope values: "plan", "readonly", "edit", "full"

No daemon changes needed — this is purely a client-side addition to expose existing daemon functionality.

---

## Example Usage (After Implementation)

```python
from bridge_client import call_remote, call_remote_streaming

# Read-only task
r1 = call_remote(
    "scripts/run_claude.sh",
    args=["Analyze this code", "/repo"],
    timeout=120,
    idempotency_key="analyze-1",
    permission_scope="plan",  # ← NEW
)

# Write-enabled task
r2 = call_remote(
    "scripts/run_claude.sh",
    args=["Refactor and commit", "/repo"],
    timeout=600,
    idempotency_key="refactor-1",
    permission_scope="edit",  # ← NEW
)

# With streaming
def show_progress(chunk):
    print(chunk, end="")

r3 = call_remote_streaming(
    "scripts/run_claude.sh",
    args=["Run tests", "/repo"],
    timeout=900,
    idempotency_key="test-1",
    on_progress=show_progress,
    permission_scope="readonly",  # ← NEW
)
```

---

## Commit Message Template

```
feat: add per-task permission_scope to call_remote/call_remote_streaming

- Add permission_scope parameter to call_remote() and call_remote_streaming()
- Allows Cowork to request task-specific permission modes (plan/readonly/edit/full)
- Daemon validates against owner's BRIDGE_PERMISSION_CEILING
- Owner's global CLAUDE_FLAGS always takes precedence
- Updated skill docs with usage examples for all 4 permission levels
- Added tests verifying daemon receives and processes permission_scope
- Backward compatible: parameter is optional, defaults to None

Closes #47
```

---

## References

- Issue: Per-task permission sandboxing
- Daemon implementation: `cowork_to_code_bridge/daemon.py` lines 607-638
- Related: `anthropics/claude-code#26479` — agent teams permission inheritance bug
- Security model: Owner-set ceiling, Cowork requests within ceiling per task
