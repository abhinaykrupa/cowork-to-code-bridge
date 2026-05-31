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
