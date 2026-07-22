"""Tests for core bridge initialization functions (bridge_init.py).

Covers:
  - is_first_connection() — marker detection
  - mark_bridge_initialized() — marker creation and idempotency
  - get_bridge_context() — knowledge base delivery
  - get_initialization_message() — user-friendly message
"""
import json
import time

from cowork_to_code_bridge.bridge_init import (
    MARKER_NAME,
    _resolve_bridge_root,
    get_bridge_context,
    get_initialization_message,
    is_first_connection,
    mark_bridge_initialized,
)

# --------------------------------------------------------------------------- #
# _resolve_bridge_root — resolution order
# --------------------------------------------------------------------------- #

def test_resolve_prefers_explicit_arg(tmp_path, monkeypatch):
    """An explicit bridge_root wins over $BRIDGE_ROOT and cwd fallbacks."""
    monkeypatch.setenv("BRIDGE_ROOT", "/some/other/place")
    assert _resolve_bridge_root(tmp_path) == tmp_path


def test_resolve_uses_env_when_no_arg(tmp_path, monkeypatch):
    """$BRIDGE_ROOT is used when no explicit arg is given."""
    monkeypatch.setenv("BRIDGE_ROOT", str(tmp_path))
    assert _resolve_bridge_root() == tmp_path


def test_resolve_falls_back_to_cwd_bridge(tmp_path, monkeypatch):
    """With no arg and no env, an existing $PWD/bridge is used."""
    monkeypatch.delenv("BRIDGE_ROOT", raising=False)
    (tmp_path / "bridge").mkdir()
    monkeypatch.chdir(tmp_path)
    assert _resolve_bridge_root() == tmp_path / "bridge"


def test_resolve_falls_back_to_package_relative(tmp_path, monkeypatch):
    """With nothing else available, falls back to the package-relative bridge."""
    monkeypatch.delenv("BRIDGE_ROOT", raising=False)
    monkeypatch.chdir(tmp_path)  # no ./bridge here
    resolved = _resolve_bridge_root()
    assert resolved.name == "bridge"


# --------------------------------------------------------------------------- #
# is_first_connection
# --------------------------------------------------------------------------- #

def test_is_first_connection_on_fresh_bridge(tmp_path):
    """is_first_connection() returns True when marker does not exist."""
    assert is_first_connection(bridge_root=tmp_path) is True
    assert not (tmp_path / MARKER_NAME).exists()


def test_is_first_connection_after_initialization(tmp_path):
    """is_first_connection() returns False after mark_bridge_initialized()."""
    mark_bridge_initialized(bridge_root=tmp_path)
    assert is_first_connection(bridge_root=tmp_path) is False


def test_is_first_connection_idempotent(tmp_path):
    """is_first_connection() can be called repeatedly without side effects."""
    result1 = is_first_connection(bridge_root=tmp_path)
    result2 = is_first_connection(bridge_root=tmp_path)
    result3 = is_first_connection(bridge_root=tmp_path)
    assert result1 == result2 == result3 is True


def test_is_first_connection_detects_existing_marker(tmp_path):
    """is_first_connection() recognizes a manually-created marker."""
    marker = tmp_path / MARKER_NAME
    marker.write_text("{}")
    assert is_first_connection(bridge_root=tmp_path) is False


def test_is_first_connection_uses_env_bridge_root(tmp_path, monkeypatch):
    """is_first_connection() respects BRIDGE_ROOT environment variable."""
    monkeypatch.setenv("BRIDGE_ROOT", str(tmp_path))
    assert is_first_connection() is True
    mark_bridge_initialized(bridge_root=tmp_path)
    assert is_first_connection() is False


# --------------------------------------------------------------------------- #
# mark_bridge_initialized
# --------------------------------------------------------------------------- #

def test_mark_bridge_initialized_creates_marker(tmp_path):
    """mark_bridge_initialized() creates the marker file."""
    result = mark_bridge_initialized(bridge_root=tmp_path)

    marker = tmp_path / MARKER_NAME
    assert marker.exists()
    assert result["initialized"] is True
    assert result["already_initialized"] is False


def test_mark_bridge_initialized_marker_format(tmp_path):
    """Marker file contains interface name, timestamp, version."""
    result = mark_bridge_initialized(bridge_root=tmp_path)
    marker = tmp_path / MARKER_NAME

    payload = json.loads(marker.read_text())
    assert "ts" in payload
    assert "version" in payload
    assert payload["ts"] == result["ts"]


def test_mark_bridge_initialized_is_idempotent(tmp_path):
    """Calling mark_bridge_initialized() twice returns same timestamp."""
    first = mark_bridge_initialized(bridge_root=tmp_path)
    second = mark_bridge_initialized(bridge_root=tmp_path)

    assert first["ts"] == second["ts"]
    assert second["already_initialized"] is True
    assert first["already_initialized"] is False


def test_mark_bridge_initialized_preserves_existing_marker(tmp_path):
    """If marker exists, mark_bridge_initialized() does not overwrite it."""
    first = mark_bridge_initialized(bridge_root=tmp_path)
    time.sleep(0.01)  # Ensure timestamp would differ if written
    second = mark_bridge_initialized(bridge_root=tmp_path)

    # Same timestamp means file was not rewritten
    assert first["ts"] == second["ts"]


def test_mark_bridge_initialized_atomic_write(tmp_path):
    """Marker is written atomically (.tmp then rename)."""
    mark_bridge_initialized(bridge_root=tmp_path)
    marker = tmp_path / MARKER_NAME

    # Should not have .tmp file (it was renamed)
    tmp_file = marker.with_suffix(f"{MARKER_NAME}.tmp")
    assert marker.exists()
    assert not tmp_file.exists()


def test_mark_bridge_initialized_tolerates_corrupt_marker(tmp_path):
    """A pre-existing but unparseable marker is reported as already-initialized."""
    marker = tmp_path / MARKER_NAME
    marker.write_text("not-json{{{")
    result = mark_bridge_initialized(bridge_root=tmp_path)
    assert result["already_initialized"] is True
    assert result["initialized"] is True
    assert result["ts"] == 0.0  # unparseable timestamp falls back to 0.0


def test_mark_bridge_initialized_returns_timestamp(tmp_path):
    """mark_bridge_initialized() returns Unix timestamp."""
    result = mark_bridge_initialized(bridge_root=tmp_path)
    ts = result["ts"]

    assert isinstance(ts, (int, float))
    assert ts > 0
    # Sanity: timestamp should be recent (within last hour)
    now = time.time()
    assert abs(now - ts) < 3600


# --------------------------------------------------------------------------- #
# get_bridge_context
# --------------------------------------------------------------------------- #

def test_get_bridge_context_returns_string():
    """get_bridge_context() returns non-empty string."""
    ctx = get_bridge_context()
    assert isinstance(ctx, str)
    assert len(ctx) > 100


def test_get_bridge_context_is_markdown():
    """get_bridge_context() returns Markdown (starts with #)."""
    ctx = get_bridge_context()
    assert ctx.strip().startswith("#")


def test_get_bridge_context_covers_core_functions():
    """Returned knowledge base mentions core functions and patterns."""
    ctx = get_bridge_context()

    # Core functions should be documented
    assert "queue_task" in ctx
    assert "poll_task_result" in ctx
    assert "call_remote" in ctx
    # Live-progress surface (#56): streaming call + ticker helpers must be
    # discoverable by a fresh Cowork session, or long tasks go silent.
    assert "call_remote_streaming" in ctx
    assert "status_line" in ctx
    assert "format_status_line" in ctx

    # Common patterns
    assert "idempotency" in ctx.lower() or "idempotent" in ctx.lower()
    assert "timeout" in ctx.lower()


def test_get_bridge_context_is_pure_function():
    """get_bridge_context() returns consistent result across calls."""
    ctx1 = get_bridge_context()
    ctx2 = get_bridge_context()
    assert ctx1 == ctx2


def test_get_bridge_context_has_code_examples():
    """Returned knowledge base includes runnable code examples."""
    ctx = get_bridge_context()
    # Examples are shown as indented import/usage snippets, not fenced blocks.
    assert "from cowork_to_code_bridge" in ctx
    assert "queue_task(" in ctx


def test_get_bridge_context_mentions_bridge_root():
    """Knowledge base explains bridge directory structure."""
    ctx = get_bridge_context()
    assert "BRIDGE_ROOT" in ctx or "bridge_root" in ctx.lower()


# --------------------------------------------------------------------------- #
# get_initialization_message
# --------------------------------------------------------------------------- #

def test_get_initialization_message_returns_string():
    """get_initialization_message() returns non-empty string."""
    msg = get_initialization_message()
    assert isinstance(msg, str)
    assert len(msg) > 50


def test_get_initialization_message_is_user_friendly():
    """User-facing message is welcoming and explains the bridge."""
    msg = get_initialization_message()

    # Should be conversational, not just raw docs
    msg_lower = msg.lower()
    assert any(w in msg_lower for w in [
        "welcome", "first time", "connected", "bridge",
        "async", "queue", "task"
    ])


def test_get_initialization_message_mentions_first_connection():
    """Message indicates this is a first-connection scenario."""
    msg = get_initialization_message()
    msg_lower = msg.lower()
    assert any(w in msg_lower for w in [
        "first", "initialize", "new", "welcome"
    ])


def test_get_initialization_message_is_concise():
    """Message is friendly but not excessively long."""
    msg = get_initialization_message()
    # Should be readable in one sitting, not a novel
    lines = msg.strip().split("\n")
    assert len(lines) < 50


def test_get_initialization_message_is_pure_function():
    """get_initialization_message() returns consistent result."""
    msg1 = get_initialization_message()
    msg2 = get_initialization_message()
    assert msg1 == msg2


# --------------------------------------------------------------------------- #
# Integration tests
# --------------------------------------------------------------------------- #

def test_first_connection_workflow(tmp_path):
    """Complete first-connection workflow: check → read → mark."""
    # 1. Check if first connection
    assert is_first_connection(bridge_root=tmp_path) is True

    # 2. Read the intro message (doesn't modify state)
    msg = get_initialization_message()
    assert len(msg) > 0
    assert is_first_connection(bridge_root=tmp_path) is True

    # 3. Read the knowledge base (still doesn't modify state)
    ctx = get_bridge_context()
    assert len(ctx) > 0
    assert is_first_connection(bridge_root=tmp_path) is True

    # 4. Mark as initialized (modifies state)
    result = mark_bridge_initialized(bridge_root=tmp_path)
    assert result["initialized"] is True

    # 5. Verify no longer first connection
    assert is_first_connection(bridge_root=tmp_path) is False

    # 6. Reading message again doesn't change state
    msg2 = get_initialization_message()
    assert msg == msg2
    assert is_first_connection(bridge_root=tmp_path) is False


def test_repeated_initialization_is_safe(tmp_path):
    """Multiple sequential initializations are idempotent and safe."""
    timestamps = []
    for _ in range(3):
        result = mark_bridge_initialized(bridge_root=tmp_path)
        timestamps.append(result["ts"])
        assert is_first_connection(bridge_root=tmp_path) is False

    # All should have same timestamp (idempotent)
    assert len(set(timestamps)) == 1


def test_marker_survives_repeated_checks(tmp_path):
    """Marker is created once and survives repeated is_first_connection() calls."""
    # Initialize
    mark_bridge_initialized(bridge_root=tmp_path)
    marker = tmp_path / MARKER_NAME
    original_mtime = marker.stat().st_mtime

    # Check repeatedly
    for _ in range(10):
        assert is_first_connection(bridge_root=tmp_path) is False

    # Marker file should not have been rewritten
    final_mtime = marker.stat().st_mtime
    assert original_mtime == final_mtime
