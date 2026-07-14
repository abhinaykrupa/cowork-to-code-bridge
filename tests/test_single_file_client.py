"""
Guard tests for the single-file Cowork client (bridge_client.py).

bridge_client.py is a self-contained copy of cowork_to_code_bridge/client.py,
fetched into the Cowork sandbox with one network request (the sandbox blocks
pip / outbound egress). These tests ensure it:
  1. imports with zero third-party dependencies (pure stdlib), and
  2. exposes the same public API (call_remote, daemon_alive) with matching
     call_remote signatures, so it can't silently drift from the package.
"""
from __future__ import annotations

import ast
import inspect
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SINGLE = REPO / "bridge_client.py"


def _imported_top_modules(path: Path) -> set[str]:
    tree = ast.parse(path.read_text())
    mods: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            mods.update(a.name.split(".")[0] for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            mods.add(node.module.split(".")[0])
    return mods


def test_single_file_exists():
    assert SINGLE.exists(), "bridge_client.py must exist at repo root"


def test_single_file_is_pure_stdlib():
    mods = _imported_top_modules(SINGLE) - {"__future__"}
    stdlib = set(sys.stdlib_module_names)
    non_stdlib = sorted(mods - stdlib)
    assert not non_stdlib, f"bridge_client.py must be stdlib-only; found: {non_stdlib}"


def test_single_file_exposes_public_api():
    import importlib.util

    spec = importlib.util.spec_from_file_location("bridge_client", SINGLE)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    assert hasattr(mod, "call_remote")
    assert hasattr(mod, "call_remote_streaming")
    assert hasattr(mod, "daemon_alive")


def _load_single():
    import importlib.util

    spec = importlib.util.spec_from_file_location("bridge_client", SINGLE)
    single = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(single)  # type: ignore[union-attr]
    return single


def test_call_remote_signature_matches_package():
    """The single-file call_remote must accept the same params as the package."""
    single = _load_single()
    from cowork_to_code_bridge import client as pkg

    single_params = set(inspect.signature(single.call_remote).parameters)
    pkg_params = set(inspect.signature(pkg.call_remote).parameters)
    assert single_params == pkg_params, (
        f"call_remote drifted: single-file={sorted(single_params)} "
        f"package={sorted(pkg_params)}"
    )


def test_streaming_signature_matches_package():
    """The single-file call_remote_streaming must match the package signature."""
    single = _load_single()
    from cowork_to_code_bridge import client as pkg

    single_params = set(inspect.signature(single.call_remote_streaming).parameters)
    pkg_params = set(inspect.signature(pkg.call_remote_streaming).parameters)
    assert single_params == pkg_params, (
        f"call_remote_streaming drifted: single-file={sorted(single_params)} "
        f"package={sorted(pkg_params)}"
    )


# The full set of functions CLAUDE.md advertises as the bridge's public surface.
# If the package grows or renames one of these, the single-file copy must keep up
# or a Cowork sandbox using the fallback gets an AttributeError at call time.
_PUBLIC_API = (
    "queue_task",
    "poll_task_result",
    "call_remote",
    "call_remote_streaming",
    "reply_to_machine",
    "resume_remote",
    "daemon_alive",
    "post_message_to_cowork",
    "detect_messages_from_claude_code",
    "format_status_line",
)


def test_single_file_has_full_public_api():
    """Every public function in the package must exist in the single-file copy.

    Regression guard: bridge_client.py previously lost queue_task,
    poll_task_result, post_message_to_cowork and detect_messages_from_claude_code
    while still claiming in its header to be "kept in sync".
    """
    single = _load_single()
    missing = [name for name in _PUBLIC_API if not hasattr(single, name)]
    assert not missing, f"bridge_client.py is missing public functions: {missing}"


def test_single_file_signatures_match_package_for_all_public_api():
    """Each shared public function must have identical params in both copies."""
    single = _load_single()
    from cowork_to_code_bridge import client as pkg

    drifted = {}
    for name in _PUBLIC_API:
        if not (hasattr(single, name) and hasattr(pkg, name)):
            continue
        s = set(inspect.signature(getattr(single, name)).parameters)
        p = set(inspect.signature(getattr(pkg, name)).parameters)
        if s != p:
            drifted[name] = {"single": sorted(s), "package": sorted(p)}
    assert not drifted, f"single-file signatures drifted from package: {drifted}"


def test_call_remote_accepts_permission_scope(tmp_path):
    """call_remote() accepts permission_scope parameter and passes it to daemon."""
    import json
    from cowork_to_code_bridge import queue_task

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


def test_call_remote_streaming_accepts_permission_scope():
    """call_remote_streaming() signature includes permission_scope parameter."""
    import inspect
    from cowork_to_code_bridge import call_remote_streaming

    # Verify the function signature includes permission_scope
    sig = inspect.signature(call_remote_streaming)
    assert "permission_scope" in sig.parameters, \
        "call_remote_streaming() missing permission_scope parameter"

    # Verify it's optional (has default value)
    param = sig.parameters["permission_scope"]
    assert param.default is None, "permission_scope should default to None"
