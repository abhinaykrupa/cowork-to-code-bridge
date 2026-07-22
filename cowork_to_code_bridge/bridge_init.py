"""
bridge_init.py — first-connection detection and initialization knowledge.

When a Cowork session connects to the bridge for the first time, it has no idea
what the bridge can do. This module hands it that knowledge — a compact, agnostic
description of the bridge's capabilities and the four functions that drive it —
and remembers (via a marker file) that the knowledge has been delivered, so the
context is offered exactly once per machine instead of on every reconnect.

Everything here is:
  - Agnostic:    no user/project-specific assumptions; reads BRIDGE_ROOT like the
                 rest of the client.
  - Idempotent:  is_first_connection() and mark_bridge_initialized() are safe to
                 call any number of times; the marker is written atomically.
  - Non-blocking: no network, no daemon round-trip, no polling — every call
                 returns immediately off the local filesystem.

Typical use (from a Cowork session, right after connecting):

    from cowork_to_code_bridge.bridge_init import (
        is_first_connection, get_bridge_context, mark_bridge_initialized,
        get_initialization_message,
    )

    if is_first_connection():
        print(get_initialization_message())   # show the user a friendly intro
        print(get_bridge_context())            # load capabilities into context
        mark_bridge_initialized()              # don't repeat next time
"""
from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any

# Name of the marker file dropped in BRIDGE_ROOT once the context has been read.
# Lives in the ephemeral bridge state dir (gitignored), never in the repo.
MARKER_NAME = ".bridge_initialized"

# Sub-directory under BRIDGE_ROOT holding one marker file per interface that has
# been initialized (e.g. .initialized/cowork, .initialized/ci-cd). Distinct from
# the single global MARKER_NAME above, which tracks the legacy machine-wide intro.
INITIALIZED_DIR = ".initialized"

# Canonical set of interfaces the bridge knows how to introduce itself to.
# detect_caller_interface() returns one of these, or "unknown" for callers it
# can't fingerprint. Order matters: detection checks the most specific markers
# first so an ambiguous caller resolves to the narrowest match.
INTERFACES = ("cowork", "claude-code", "hermes", "ci-cd", "script", "unknown")


def _resolve_bridge_root(bridge_root: Path | str | None = None) -> Path:
    """Find the bridge directory, matching client.py's resolution order.

    Order: explicit arg > $BRIDGE_ROOT > $PWD/bridge > package-relative fallback.
    Kept in sync with cowork_to_code_bridge.client._resolve_bridge_root so the
    marker lands next to queue/ and results/.
    """
    if bridge_root:
        return Path(bridge_root)
    env = os.environ.get("BRIDGE_ROOT")
    if env:
        return Path(env)
    cwd_bridge = Path.cwd() / "bridge"
    if cwd_bridge.exists():
        return cwd_bridge
    return Path(__file__).resolve().parents[2] / "bridge"


def get_bridge_context() -> str:
    """Return the full initialization knowledge base as a string.

    This is the same content as docs/BRIDGE_INIT.md, inlined so it travels with
    the package and is available even when the docs/ tree isn't mounted into the
    Cowork sandbox. Pure function — no side effects, returns immediately.

    Load this into a session's context on first connection so the agent knows
    what the bridge can do before it tries to use it.
    """
    return _BRIDGE_CONTEXT


def is_first_connection(bridge_root: Path | str | None = None) -> bool:
    """True if this machine has not yet been initialized (marker absent).

    Idempotent and non-blocking: only checks for the existence of the marker
    file in BRIDGE_ROOT. Never writes. Call freely.

    Args:
        bridge_root: Override the auto-detected bridge directory.
    """
    root = _resolve_bridge_root(bridge_root)
    return not (root / MARKER_NAME).exists()


def mark_bridge_initialized(bridge_root: Path | str | None = None) -> dict[str, Any]:
    """Create the .bridge_initialized marker so future connections skip the intro.

    Idempotent: if the marker already exists it is left untouched and its original
    timestamp is preserved. The write is atomic (write-temp-then-rename), so a
    crashed or concurrent call can never leave a half-written marker.

    Args:
        bridge_root: Override the auto-detected bridge directory.

    Returns:
        Dict with keys:
          initialized (bool)        always True after this returns
          already_initialized (bool) True if the marker existed before this call
          marker_path (str)         absolute path to the marker
          ts (float)                initialization timestamp (original if pre-existing)
    """
    root = _resolve_bridge_root(bridge_root)
    root.mkdir(parents=True, exist_ok=True)
    marker = root / MARKER_NAME

    if marker.exists():
        try:
            existing = json.loads(marker.read_text())
            ts = float(existing.get("ts", 0.0))
        except (OSError, json.JSONDecodeError, TypeError, ValueError):
            ts = 0.0
        return {
            "initialized": True,
            "already_initialized": True,
            "marker_path": str(marker),
            "ts": ts,
        }

    ts = time.time()
    payload = {
        "initialized": True,
        "ts": ts,
        "version": _INIT_VERSION,
    }
    tmp = marker.with_suffix(marker.suffix + ".tmp")
    tmp.write_text(json.dumps(payload))
    tmp.rename(marker)

    return {
        "initialized": True,
        "already_initialized": False,
        "marker_path": str(marker),
        "ts": ts,
    }


def get_initialization_message() -> str:
    """Return a short, user-friendly message to show on the first connection.

    Plain text, safe to print directly to a Cowork chat. Pure function.
    """
    return _INIT_MESSAGE


# --------------------------------------------------------------------------- #
# Interface-aware initialization
# --------------------------------------------------------------------------- #


def detect_caller_interface(env: dict[str, str] | None = None) -> str:
    """Identify which kind of system is connecting to the bridge.

    Returns one of INTERFACES: "cowork", "claude-code", "hermes", "ci-cd",
    "script", or "unknown". Pure and non-blocking — inspects environment
    variables only (defaulting to os.environ), never the filesystem or network.

    Detection is ordered most-specific-first so an ambiguous caller resolves to
    the narrowest match:

      1. CI/CD      — GITHUB_ACTIONS / GITLAB_CI / generic CI markers. Checked
                      first because a CI runner may *also* set BRIDGE_ROOT, and
                      its calling pattern (idempotent queue + poll) is the one
                      that matters there.
      2. Hermes / external agents — explicit BRIDGE_CALLER / BRIDGE_USER_AGENT
                      identity headers the caller stamps on itself.
      3. Cowork     — BRIDGE_ROOT plus a Cowork/sandbox marker.
      4. Claude Code — BRIDGE_ROOT in a local (non-sandbox) execution context.
      5. script     — direct daemon access with no rich identity, but a bridge
                      dir is reachable.
      6. unknown    — nothing recognizable.

    Args:
        env: Environment mapping to inspect. Defaults to os.environ. Pass an
            explicit dict to simulate a caller in tests.
    """
    e = os.environ if env is None else env

    # 1. CI/CD — wins even if BRIDGE_ROOT is also set.
    ci_markers = ("GITHUB_ACTIONS", "GITLAB_CI", "CIRCLECI", "BUILDKITE",
                  "JENKINS_URL", "TRAVIS")
    if any(_truthy(e.get(m)) for m in ci_markers) or _truthy(e.get("CI")):
        return "ci-cd"

    # 2. Explicit self-identification from external agents / future systems.
    caller = (e.get("BRIDGE_CALLER") or e.get("BRIDGE_USER_AGENT") or "").strip().lower()
    if caller:
        if "hermes" in caller:
            return "hermes"
        if "cowork" in caller:
            return "cowork"
        if "claude-code" in caller or "claude_code" in caller:
            return "claude-code"
        if caller in INTERFACES:
            return caller

    has_bridge_root = bool(e.get("BRIDGE_ROOT"))

    # 3. Cowork sandbox — BRIDGE_ROOT plus a sandbox fingerprint.
    cowork_markers = ("COWORK", "COWORK_SESSION", "COWORK_SESSION_ID",
                      "SANDBOX", "ANTHROPIC_SANDBOX")
    if has_bridge_root and any(_truthy(e.get(m)) for m in cowork_markers):
        return "cowork"

    # 4. Claude Code — local execution context with the bridge wired up.
    if _truthy(e.get("CLAUDE_CODE")) or _truthy(e.get("CLAUDECODE")):
        return "claude-code"

    # 5. Bridge reachable but no rich identity → a direct/script caller.
    if has_bridge_root:
        return "script"

    return "unknown"


def _truthy(value: str | None) -> bool:
    """True if an env-var string is set to anything other than a falsey token."""
    if value is None:
        return False
    return value.strip().lower() not in ("", "0", "false", "no", "off")


def get_initialization_for_interface(interface: str) -> dict[str, Any]:
    """Return tailored initialization knowledge for one interface.

    Each interface gets the capability subset and call-pattern examples that
    matter for how *it* talks to the bridge. Unknown / unrecognized interfaces
    fall back to a minimal interface spec that any system can bootstrap from.

    Pure function — no side effects.

    Returns a dict with keys:
      interface (str)        the resolved interface name (echoes input, or
                             "unknown" if not recognized)
      title (str)            short human label
      summary (str)          one-line description of what this caller is
      capabilities (list)    the functions/patterns relevant to this caller
      examples (str)         copy-pasteable example matching its calling pattern
      format (str)           the natural response format: "markdown", "cli",
                             or "structured"
    """
    key = interface if interface in _INTERFACE_KB else "unknown"
    # Return a copy so callers can mutate freely without corrupting the table.
    kb = _INTERFACE_KB[key]
    return {
        "interface": key,
        "title": kb["title"],
        "summary": kb["summary"],
        "capabilities": list(kb["capabilities"]),
        "examples": kb["examples"],
        "format": kb["format"],
    }


def mark_interface_initialized(
    interface: str, bridge_root: Path | str | None = None
) -> dict[str, Any]:
    """Record that one interface has been initialized.

    Creates ``BRIDGE_ROOT/.initialized/{interface}``. Idempotent: a pre-existing
    marker is left untouched and its original timestamp preserved. Writes are
    atomic (temp-then-rename). Unknown interface names are normalized to
    "unknown" so a marker file is never created from arbitrary caller input.

    Args:
        interface: One of INTERFACES (others collapse to "unknown").
        bridge_root: Override the auto-detected bridge directory.

    Returns:
        Dict with keys: interface, initialized (bool, always True),
        already_initialized (bool), marker_path (str), ts (float).
    """
    key = interface if interface in INTERFACES else "unknown"
    root = _resolve_bridge_root(bridge_root)
    init_dir = root / INITIALIZED_DIR
    init_dir.mkdir(parents=True, exist_ok=True)
    marker = init_dir / key

    if marker.exists():
        try:
            existing = json.loads(marker.read_text())
            ts = float(existing.get("ts", 0.0))
        except (OSError, json.JSONDecodeError, TypeError, ValueError):
            ts = 0.0
        return {
            "interface": key,
            "initialized": True,
            "already_initialized": True,
            "marker_path": str(marker),
            "ts": ts,
        }

    ts = time.time()
    payload = {"interface": key, "initialized": True, "ts": ts, "version": _INIT_VERSION}
    tmp = marker.with_suffix(".tmp")
    tmp.write_text(json.dumps(payload))
    tmp.rename(marker)

    return {
        "interface": key,
        "initialized": True,
        "already_initialized": False,
        "marker_path": str(marker),
        "ts": ts,
    }


def is_interface_initialized(
    interface: str, bridge_root: Path | str | None = None
) -> bool:
    """True if this interface already has an .initialized/{interface} marker.

    Idempotent, read-only counterpart to mark_interface_initialized(). Lets a
    caller skip re-serving init knowledge to a system it has already greeted.
    """
    key = interface if interface in INTERFACES else "unknown"
    root = _resolve_bridge_root(bridge_root)
    return (root / INITIALIZED_DIR / key).exists()


def serve_init_response(
    interface: str | None = None,
    *,
    bridge_root: Path | str | None = None,
    mark: bool = False,
    env: dict[str, str] | None = None,
) -> str:
    """Produce the right initialization payload for a caller, in its native format.

    This is the one-call entry point a daemon (or any dispatcher) uses to answer
    "who's connecting and what should I tell them?":

      - interface=None → auto-detect via detect_caller_interface(env).
      - LLM-ish callers (cowork, claude-code, hermes) get **Markdown** — a
        readable capability reference to load into context.
      - script callers get a **concise CLI/plaintext** cheat-sheet.
      - ci-cd and unknown/custom systems get **structured JSON** that's trivial
        to parse programmatically.

    Args:
        interface: Force a specific interface; auto-detect when None.
        bridge_root: Override the bridge directory (only used when mark=True).
        mark: When True, also call mark_interface_initialized() as a side effect
            so subsequent connections can be skipped. Default False (pure read).
        env: Environment mapping for auto-detection. Defaults to os.environ.

    Returns:
        A string: Markdown, a CLI cheat-sheet, or a JSON document, depending on
        the interface's natural format.
    """
    resolved = interface if interface in INTERFACES else (
        detect_caller_interface(env) if interface is None else "unknown"
    )
    kb = get_initialization_for_interface(resolved)

    if mark:
        mark_interface_initialized(resolved, bridge_root=bridge_root)

    fmt = kb["format"]
    if fmt == "structured":
        return json.dumps(kb, indent=2)
    if fmt == "cli":
        return _render_cli(kb)
    return _render_markdown(kb)


def _render_markdown(kb: dict[str, Any]) -> str:
    lines = [
        f"# {kb['title']} — Bridge Initialization",
        "",
        kb["summary"],
        "",
        "## Relevant capabilities",
    ]
    lines += [f"- {c}" for c in kb["capabilities"]]
    lines += ["", "## Example", "", "```python", kb["examples"].rstrip(), "```"]
    return "\n".join(lines) + "\n"


def _render_cli(kb: dict[str, Any]) -> str:
    lines = [
        f"{kb['title']} — bridge init",
        kb["summary"],
        "",
        "Capabilities:",
    ]
    lines += [f"  - {c}" for c in kb["capabilities"]]
    lines += ["", "Example:", kb["examples"].rstrip()]
    return "\n".join(lines) + "\n"


# --------------------------------------------------------------------------- #
# Static content
# --------------------------------------------------------------------------- #

_INIT_VERSION = 1

# Per-interface knowledge base. Each entry is the tailored subset of bridge
# capability that matters to that caller, plus an example matching how that
# caller actually invokes the bridge, and the response format it prefers.
_INTERFACE_KB: dict[str, dict[str, Any]] = {
    "cowork": {
        "title": "Claude Cowork (cloud sandbox)",
        "summary": (
            "You're a Cowork session with a short-lived sandbox. Favor async: "
            "queue work, return, and poll on a later turn so long jobs survive "
            "your timeout. Use bidirectional messaging to stream progress."
        ),
        "capabilities": [
            "queue_task(script, ...) — fire-and-forget; returns task_id",
            "poll_task_result(task_id) — idempotent status/result check",
            "call_remote(script, ...) — blocking; only for quick (<30s) work",
            "detect_messages_from_claude_code(parent_task_id=...) — read updates",
            "Always pass idempotency_key for state-changing work",
        ],
        "examples": (
            "from cowork_to_code_bridge.client import queue_task, poll_task_result\n"
            "job = queue_task('scripts/build.sh', timeout=1800,\n"
            "                 idempotency_key='build-main-2026-06-18')\n"
            "# ... later turn ...\n"
            "res = poll_task_result(job['task_id'])\n"
            "if res['status'] == 'completed':\n"
            "    print(res['exit_code'], res['stdout'])"
        ),
        "format": "markdown",
    },
    "claude-code": {
        "title": "Claude Code (local machine)",
        "summary": (
            "You're Claude Code running on the user's own machine — the execution "
            "side of the bridge. You have direct daemon access and full "
            "capabilities, and you push updates back to Cowork."
        ),
        "capabilities": [
            "Full daemon access — run any whitelisted script directly",
            "call_remote / queue_task / poll_task_result available",
            "post_message_to_cowork(type, content, parent_task_id=...) — push updates",
            "Stream progress instead of going silent on long jobs",
            "git / build / test / package-install on the real machine",
        ],
        "examples": (
            "from cowork_to_code_bridge.client import post_message_to_cowork\n"
            "post_message_to_cowork('progress', 'Build 40% complete',\n"
            "                       parent_task_id=task_id)\n"
            "# ... on completion ...\n"
            "post_message_to_cowork('completed', 'Build succeeded', parent_task_id=task_id)"
        ),
        "format": "markdown",
    },
    "hermes": {
        "title": "Hermes / External Agent",
        "summary": (
            "You're an external agent reaching the bridge over its MCP server. "
            "Use MCP tools; messages follow the bridge's structured message "
            "format (type + content + optional parent_task_id)."
        ),
        "capabilities": [
            "Connect via the bridge MCP server (cowork_to_code_bridge.mcp_server)",
            "MCP tools mirror the client: queue/poll/call/message",
            "Message format: {type, content, parent_task_id?, request_id}",
            "type ∈ {progress, completed, error, info}",
            "Idempotent reads (poll/detect); pass idempotency_key on writes",
        ],
        "examples": (
            "# Over MCP, invoke the bridge tools by name:\n"
            "queue_task(script='scripts/run.sh', idempotency_key='hermes-job-1')\n"
            "poll_task_result(task_id='...')\n"
            "# Structured message back:\n"
            "post_message_to_cowork(message_type='info', content='ack')"
        ),
        "format": "markdown",
    },
    "ci-cd": {
        "title": "CI/CD System",
        "summary": (
            "You're an automated pipeline (GitHub Actions, GitLab CI, etc.). "
            "Queue tasks idempotently and poll for status; never block a runner "
            "on a long job, and make retries safe."
        ),
        "capabilities": [
            "queue_task with a deterministic idempotency_key (e.g. commit SHA)",
            "poll_task_result in a bounded loop until completed/timeout",
            "Treat non-zero exit_code as pipeline failure",
            "Retries are safe when idempotency_key is stable",
        ],
        "examples": (
            "queue_task(script='scripts/deploy.sh',\n"
            "           idempotency_key=f'deploy-{GIT_SHA}')\n"
            "# poll until terminal:\n"
            "while True:\n"
            "    r = poll_task_result(task_id)\n"
            "    if r['status'] in ('completed', 'unknown'): break"
        ),
        "format": "structured",
    },
    "script": {
        "title": "Direct Script / Custom Caller",
        "summary": (
            "You're a raw script talking to the bridge filesystem directly, "
            "without the Python client. Drop task files into queue/ and read "
            "result files out of results/."
        ),
        "capabilities": [
            "queue/  — write a JSON task file: {script, args, timeout, idempotency_key}",
            "results/ — read JSON result: {task_id, status, exit_code, stdout, stderr}",
            "to_cowork/ — machine→Cowork messages land here",
            "Poll a result by reading results/<task_id>.json",
            "BRIDGE_ROOT env var points at the shared directory",
        ],
        "examples": (
            "# bash: queue a task and poll for its result\n"
            "echo '{\"script\":\"scripts/run.sh\",\"timeout\":60}' \\\n"
            "  > \"$BRIDGE_ROOT/queue/$(uuidgen).json\"\n"
            "cat \"$BRIDGE_ROOT/results/<task_id>.json\""
        ),
        "format": "cli",
    },
    "unknown": {
        "title": "Unknown / Future System",
        "summary": (
            "Minimal interface spec for an unrecognized caller. The bridge is a "
            "file-based async RPC: write a task, poll for a result, both through "
            "the shared BRIDGE_ROOT directory."
        ),
        "capabilities": [
            "BRIDGE_ROOT holds queue/, results/, to_cowork/",
            "Submit: write JSON {script, args?, timeout?, idempotency_key?} to queue/",
            "Result: read JSON {task_id, status, exit_code, stdout, stderr} from results/",
            "status ∈ {queued, running, completed, unknown}",
            "All reads are side-effect-free; writes should carry idempotency_key",
        ],
        "examples": (
            "task = {'script': 'scripts/run.sh', 'timeout': 60,\n"
            "        'idempotency_key': 'my-unique-key'}\n"
            "# write task to $BRIDGE_ROOT/queue/<id>.json\n"
            "# read $BRIDGE_ROOT/results/<id>.json until status == 'completed'"
        ),
        "format": "structured",
    },
}

_INIT_MESSAGE = """\
🌉  Bridge connected for the first time.

You're now talking to Claude Code running on the user's own machine. Anything
that needs the real computer — builds, tests, git, installs, system checks — can
run there and the results come back here.

Quick mental model:
  • call_remote(...)                 run something and wait for the result
  • queue_task(...) + poll_task_result(...)   fire-and-forget, then poll later
  • post_message_to_cowork(...)      Claude Code → Cowork updates
  • detect_messages_from_claude_code(...)   read those updates back

Run get_bridge_context() for the full reference, or read docs/BRIDGE_INIT.md.
This intro is shown once; later connections skip straight to work.
"""

_BRIDGE_CONTEXT = """\
# Bridge Capabilities — Initialization Context

You are a Cowork session connected to **Claude Code running on the user's own
machine** (macOS or Linux) through a small file-based bridge. Tasks that need the
real computer run there; results flow back to you.

## What the bridge can do
- Run any whitelisted script or command on the machine.
- Build / run / test real applications.
- git operations (push, pull, status) against local repos.
- Install packages (npm, pip, brew, docker, …).
- Inspect machine health (RAM, disk, processes).
- Pass messages both directions between Cowork and Claude Code.

The bridge is file-based and idempotent: it survives reboots and short sandbox
timeouts. There is no network call from your side — everything moves through a
shared bind-mounted directory (BRIDGE_ROOT) holding queue/, results/, and
to_cowork/.

## Function reference

### call_remote(script, args=None, timeout=60, ...)  — BLOCKING
Run a script on the machine and wait for it to finish. Returns a dict with
exit_code, stdout, stderr. Use when you need the answer right now and the work
fits inside your sandbox timeout.

### queue_task(script, args=None, timeout=60, idempotency_key=None, ...)  — NON-BLOCKING
Queue a task and return immediately with {task_id, status:"queued", timestamp}.
Use for long-running work, or whenever your sandbox has a short timeout (e.g.
~45s). Pair with poll_task_result.

### poll_task_result(task_id)  — NON-BLOCKING, IDEMPOTENT
Check on a queued task. Returns status one of: "queued", "running", "completed"
(with full result), or "unknown". Safe to call repeatedly — no side effects.
While "running" the dict also carries a live ticker from the daemon's status
file (written every ~2s): elapsed_s, last_line, state, plus a pre-rendered
status_line like "⣾ Working… 42s elapsed" — show it to the user instead of
going silent between polls.

### call_remote_streaming(script, ..., on_progress=None, on_status=None)  — BLOCKING, LIVE OUTPUT
Like call_remote, but streams the script's output while it runs. on_progress
receives each new chunk of stdout/stderr text; on_status receives the daemon's
~2s status dicts ({elapsed_s, last_line, state}) — feed them to
format_status_line(status, verb="Building", show_last_line=True) for a
spinner/elapsed ticker. Same result dict and idempotency guarantees as
call_remote. Use for builds and test runs where waiting blind is unacceptable.

### post_message_to_cowork(message_type, content, parent_task_id=None)
Used by Claude Code (machine side) to push a structured update back to Cowork:
message_type ∈ {"progress","completed","error","info"}. Returns a request_id.

### detect_messages_from_claude_code(parent_task_id=None)  — IDEMPOTENT
Read messages Claude Code posted back. Optionally filter to one parent_task_id.
Returns a list (empty if none). Safe to poll.

## When to use each

| Goal                                   | Use                              |
|----------------------------------------|----------------------------------|
| Quick command, need result now         | call_remote                      |
| Long build/test, or short timeout      | queue_task + poll_task_result    |
| Watch a long task's output live        | call_remote_streaming            |
| Avoid duplicate runs on retry          | queue_task(idempotency_key=...)  |
| Cap what a task can cost               | max_budget_usd=2.00              |
| Limit what a task may change           | permission_scope="readonly"      |
| Get a human to approve first           | plan="what this will do"         |
| Machine reports progress to Cowork     | post_message_to_cowork           |
| Cowork reads machine updates           | detect_messages_from_claude_code |

## Safety controls (opt-in, per task)

These are extra keyword arguments to call_remote / queue_task. All are
optional; the daemon's owner sets the hard ceilings, and a caller can only
ever narrow them, never widen them.

### max_budget_usd=<float>
Per-task API spend ceiling, passed to run_claude.sh as --max-budget-usd. If
the agent hits the ceiling before finishing, it stops and reports what it
managed to do. The owner may set BRIDGE_MAX_BUDGET_USD as a global hard
ceiling; when both exist the effective limit is the LOWER of the two.
Ignored for non-claude scripts.

### permission_scope=<"plan"|"readonly"|"edit"|"full">
How much the Claude Code agent is allowed to do on the machine for this one
task. The owner may set BRIDGE_PERMISSION_CEILING; a caller asking for more
than the ceiling is clamped down to it silently.

### plan=<str>
Plain-English description of what the task will do. If scripts/approve_plan.sh
exists on the machine, the daemon runs it with this text BEFORE the real
script — a human-in-the-loop gate. The hook exits 0 to allow or 2 to reject
(rejection returns exit_code=-1 with the hook's stderr as the error). If the
hook isn't installed the field is ignored.

Example — a costly refactor, capped and sandboxed:
    queue_task("scripts/run_claude.sh",
               args=["Refactor the auth module", "/path/to/repo"],
               timeout=1800,
               max_budget_usd=2.00,
               permission_scope="edit",
               idempotency_key="refactor-auth-2026-06-18")

## Async vs blocking
- **Blocking (call_remote):** simplest; one call, one result. Risk: if the work
  outlives your sandbox timeout, the call dies even though the task may finish on
  the machine.
- **Async (queue_task → poll_task_result):** robust for anything slow or
  uncertain. Queue, return, poll on a later turn. The task keeps running on the
  machine regardless of your sandbox lifecycle.

Rule of thumb: if it might take longer than ~30s, queue it.

## Idempotency guarantees
- poll_task_result and detect_messages_from_claude_code are pure reads — call
  them as often as you like.
- queue_task with an idempotency_key won't double-execute the same logical task
  on retry.
- Initialization (this module) is marker-based: is_first_connection() only reads,
  mark_bridge_initialized() is safe to call repeatedly and preserves the original
  timestamp.

## Common usage patterns

Blocking — run tests and read the result:
    from cowork_to_code_bridge import call_remote
    r = call_remote("scripts/run_tests.sh", timeout=120)
    print(r["exit_code"], r["stdout"])

Async — long build, poll later:
    from cowork_to_code_bridge.client import queue_task, poll_task_result
    job = queue_task("scripts/build.sh", timeout=1800,
                     idempotency_key="build-main-2026-06-18")
    # ... later turn ...
    res = poll_task_result(job["task_id"])
    if res["status"] == "completed":
        print(res["exit_code"], res["stdout"])

Streaming — long build with a live ticker:
    from cowork_to_code_bridge.client import call_remote_streaming, format_status_line
    r = call_remote_streaming(
        "scripts/build.sh", timeout=900, idempotency_key="build-main-2026-06-18",
        on_status=lambda s: print(format_status_line(s, verb="Building",
                                                     show_last_line=True)),
    )

Bidirectional — watch for progress from the machine:
    from cowork_to_code_bridge.client import detect_messages_from_claude_code
    for m in detect_messages_from_claude_code(parent_task_id=job["task_id"]):
        print(m["type"], m["content"])

## Best practices
- Prefer **queue_task** for anything slow; never block your sandbox on a long job.
- Always pass an **idempotency_key** for state-changing work (deploys, migrations)
  so retries don't double-fire.
- **Poll, don't spin:** call poll_task_result on later turns, not in a tight loop.
- While a task is "running", surface poll_task_result's **status_line** (or use
  call_remote_streaming's on_status) so the user sees a live spinner, not silence.
- Pass **max_budget_usd** on any run_claude.sh task whose scope is open-ended
  ("refactor everything") — an uncapped agent task can run for hours.
- Ask for the **narrowest permission_scope** that still does the job; use
  "readonly" for anything that only needs to inspect the machine.
- Use **post_message_to_cowork** from the machine side to stream progress instead
  of going silent during long jobs.
- Treat reads (poll/detect) as free and side-effect-free; treat queue/call as the
  only things that change state.
"""
