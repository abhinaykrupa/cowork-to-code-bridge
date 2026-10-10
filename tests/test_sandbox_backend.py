"""Tests for opt-in Linux sandboxing backend (Vetto / Bubblewrap).

Verifies backend detection, command argv wrapping, preservation of Claude
execution parameters (CLAUDE_FLAGS, MAX_BUDGET_USD, CLAUDE_MODEL_TIER, CLAUDE_EFFORT),
and parity between canonical and legacy daemon implementations.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from cowork_to_code_bridge.daemon import run_one
from cowork_to_code_bridge.sandbox import detect_sandbox_backend, wrap_argv

REPO_ROOT = Path(__file__).resolve().parents[1]


# ---------------------------------------------------------------------------
# 1. detect_sandbox_backend
# ---------------------------------------------------------------------------


def test_detect_sandbox_backend_default() -> None:
    """When BRIDGE_SANDBOX is unset, detection returns 'off'."""
    assert detect_sandbox_backend(env={}, platform="linux") == "off"


@pytest.mark.parametrize("val", ["off", "OFF", "0", "false", "no", "none", ""])
def test_detect_sandbox_backend_off_values(val: str) -> None:
    """Disabled values for BRIDGE_SANDBOX all return 'off'."""
    assert detect_sandbox_backend(env={"BRIDGE_SANDBOX": val}, platform="linux") == "off"


@pytest.mark.parametrize("platform", ["darwin", "win32", "freebsd"])
def test_detect_sandbox_backend_non_linux(platform: str) -> None:
    """Non-Linux platforms always fall back to 'off'."""
    assert detect_sandbox_backend(env={"BRIDGE_SANDBOX": "vetto"}, platform=platform) == "off"
    assert detect_sandbox_backend(env={"BRIDGE_SANDBOX": "bwrap"}, platform=platform) == "off"
    assert detect_sandbox_backend(env={"BRIDGE_SANDBOX": "auto"}, platform=platform) == "off"


def test_detect_sandbox_backend_explicit_vetto_and_bwrap() -> None:
    """Explicit 'vetto' or 'bwrap' returns that backend on Linux."""
    assert detect_sandbox_backend(env={"BRIDGE_SANDBOX": "vetto"}, platform="linux") == "vetto"
    assert detect_sandbox_backend(env={"BRIDGE_SANDBOX": "bwrap"}, platform="linux") == "bwrap"


def test_detect_sandbox_backend_unknown_falls_back_to_off() -> None:
    """Unrecognized backend values safely fall back to 'off'."""
    assert detect_sandbox_backend(env={"BRIDGE_SANDBOX": "invalid"}, platform="linux") == "off"


def test_detect_sandbox_backend_auto(monkeypatch: pytest.MonkeyPatch) -> None:
    """auto detects vetto first, then bwrap, else off."""
    # 1. When vetto is on PATH -> 'vetto'
    def mock_which_vetto(cmd: str) -> str | None:
        if cmd == "vetto":
            return "/usr/local/bin/vetto"
        if cmd == "bwrap":
            return "/usr/bin/bwrap"
        return None

    monkeypatch.setattr("shutil.which", mock_which_vetto)
    assert detect_sandbox_backend(env={"BRIDGE_SANDBOX": "auto"}, platform="linux") == "vetto"

    # 2. When only bwrap is on PATH -> 'bwrap'
    def mock_which_bwrap(cmd: str) -> str | None:
        if cmd == "bwrap":
            return "/usr/bin/bwrap"
        return None

    monkeypatch.setattr("shutil.which", mock_which_bwrap)
    assert detect_sandbox_backend(env={"BRIDGE_SANDBOX": "auto"}, platform="linux") == "bwrap"

    # 3. When neither is on PATH -> 'off'
    monkeypatch.setattr("shutil.which", lambda _: None)
    assert detect_sandbox_backend(env={"BRIDGE_SANDBOX": "auto"}, platform="linux") == "off"


# ---------------------------------------------------------------------------
# 2. wrap_argv
# ---------------------------------------------------------------------------


def test_wrap_argv_off() -> None:
    """backend='off' returns original argv unchanged."""
    argv = ["bash", "/path/to/script.sh", "arg1"]
    wrapped = wrap_argv(argv, "scripts/run_claude.sh", "/tmp", Path("/tmp"), backend="off")
    assert wrapped == argv
    assert wrapped is not argv  # defensive copy


def test_wrap_argv_vetto_default_profile() -> None:
    """vetto backend wraps with default profile for non-Claude scripts."""
    argv = ["bash", "/path/to/mac_health.sh", "--json"]
    wrapped = wrap_argv(
        argv, "scripts/mac_health.sh", "/workspace", Path("/bridge"), backend="vetto"
    )
    expected = [
        "vetto", "--profile", "default", "run", "--",
        "bash", "/path/to/mac_health.sh", "--json"
    ]
    assert wrapped == expected


@pytest.mark.parametrize(
    "script",
    ["scripts/run_claude.sh", "run_claude.sh", "scripts/escalate_to_claude.sh"],
)
def test_wrap_argv_vetto_claude_profile(script: str) -> None:
    """vetto backend wraps with claude profile for Claude scripts."""
    argv = ["bash", "/path/to/run_claude.sh", "fix tests"]
    wrapped = wrap_argv(argv, script, "/workspace", Path("/bridge"), backend="vetto")
    expected = [
        "vetto", "--profile", "claude", "run", "--",
        "bash", "/path/to/run_claude.sh", "fix tests"
    ]
    assert wrapped == expected


def test_wrap_argv_bwrap(tmp_path: Path) -> None:
    """bwrap backend wraps with mount isolation for cwd, bridge_root, .ssh, and .env."""
    cwd = tmp_path / "workspace"
    cwd.mkdir()
    bridge_root = tmp_path / "bridge"
    bridge_root.mkdir()
    argv = ["bash", "/path/to/run_claude.sh", "do task"]

    wrapped = wrap_argv(argv, "scripts/run_claude.sh", str(cwd), bridge_root, backend="bwrap")

    assert wrapped[0] == "bwrap"
    assert "--ro-bind" in wrapped
    assert "/" in wrapped
    assert "--dev" in wrapped
    assert "--proc" in wrapped
    assert "--tmpfs" in wrapped
    assert any(".ssh" in arg for arg in wrapped)
    assert any(".env" in arg for arg in wrapped)
    assert str(cwd.resolve()) in wrapped
    assert str(bridge_root.resolve()) in wrapped
    assert "--die-with-parent" in wrapped
    assert wrapped[-3:] == argv


def test_wrap_argv_auto_resolution(monkeypatch: pytest.MonkeyPatch) -> None:
    """backend='auto' auto-resolves via detect_sandbox_backend."""
    monkeypatch.setattr("cowork_to_code_bridge.sandbox.detect_sandbox_backend", lambda: "vetto")
    argv = ["python3", "task.py"]
    wrapped = wrap_argv(argv, "task.py", "/cwd", Path("/bridge"), backend="auto")
    assert wrapped == ["vetto", "--profile", "default", "run", "--", "python3", "task.py"]


# ---------------------------------------------------------------------------
# 3. Environment & Parameter Preservation in daemon
# ---------------------------------------------------------------------------


def test_daemon_preserves_claude_env_and_wraps_in_run_one(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """run_one() wraps argv when BRIDGE_SANDBOX is active and preserves Claude env vars."""
    bridge_root = tmp_path / "bridge"
    bridge_root.mkdir()
    scripts_dir = bridge_root / "scripts"
    scripts_dir.mkdir()
    queue_dir = bridge_root / "queue"
    queue_dir.mkdir()
    results_dir = bridge_root / "results"
    results_dir.mkdir()
    inflight_dir = bridge_root / "inflight"
    inflight_dir.mkdir()
    progress_dir = bridge_root / "progress"
    progress_dir.mkdir()
    processed_dir = bridge_root / "processed"
    processed_dir.mkdir()

    # Create dummy script
    script_file = scripts_dir / "run_claude.sh"
    script_file.write_text("#!/bin/bash\necho ok\n")
    script_file.chmod(0o755)

    # Queue command with routing env vars
    cmd_id = "test-cmd-001"
    cmd_path = queue_dir / f"{cmd_id}.json"
    cmd_payload = {
        "script": "scripts/run_claude.sh",
        "args": ["perform task"],
        "model_tier": "haiku",
        "effort": "low",
        "permission_scope": "readonly",
        "max_budget_usd": 3.50,
        "timeout": 30,
    }
    cmd_path.write_text(json.dumps(cmd_payload))

    # Configure daemon paths and environment
    monkeypatch.setattr("cowork_to_code_bridge.daemon.BRIDGE_ROOT", bridge_root)
    monkeypatch.setattr("cowork_to_code_bridge.daemon.SCRIPTS_DIR", scripts_dir)
    monkeypatch.setattr("cowork_to_code_bridge.daemon.QUEUE", queue_dir)
    monkeypatch.setattr("cowork_to_code_bridge.daemon.RESULTS", results_dir)
    monkeypatch.setattr("cowork_to_code_bridge.daemon.INFLIGHT", inflight_dir)
    monkeypatch.setattr("cowork_to_code_bridge.daemon.PROGRESS", progress_dir)
    monkeypatch.setattr("cowork_to_code_bridge.daemon.PROCESSED", processed_dir)
    monkeypatch.setattr("cowork_to_code_bridge.daemon.JOURNAL", bridge_root / "journal.log")
    monkeypatch.setattr("cowork_to_code_bridge.daemon.MAX_TIMEOUT_SEC", 600)
    monkeypatch.setattr("cowork_to_code_bridge.daemon.CALLER_ENV_ENABLED", True)

    monkeypatch.setenv("BRIDGE_SANDBOX", "vetto")
    monkeypatch.setattr("sys.platform", "linux")

    # Intercept _run_streaming
    captured: dict[str, Any] = {}

    def mock_run_streaming(
        argv: list[str], cwd: str, env: dict[str, str], timeout: int, *args: Any, **kwargs: Any
    ) -> dict[str, Any]:
        captured["argv"] = argv
        captured["cwd"] = cwd
        captured["env"] = env
        captured["timeout"] = timeout
        return {"exit_code": 0, "stdout": "done", "stderr": ""}

    monkeypatch.setattr("cowork_to_code_bridge.daemon._run_streaming", mock_run_streaming)

    # Execute run_one
    run_one(cmd_path, token_required=None, terminal={}, idem_cache={})

    # Assertions
    assert "argv" in captured, "_run_streaming was not called"
    wrapped_argv = captured["argv"]
    # Verifies wrap_argv was invoked with Vetto and 'claude' profile
    assert wrapped_argv[:5] == ["vetto", "--profile", "claude", "run", "--"]
    assert wrapped_argv[5] == "bash"
    assert wrapped_argv[6] == str(script_file.resolve())
    assert wrapped_argv[7] == "perform task"

    env = captured["env"]
    # Ensure Claude and routing execution parameters are preserved
    assert env.get("CLAUDE_MODEL_TIER") == "haiku"
    assert env.get("CLAUDE_EFFORT") == "low"
    assert env.get("CLAUDE_FLAGS") == "--allowedTools Read,Glob,Grep"
    assert env.get("MAX_BUDGET_USD") == "3.5000"


# ---------------------------------------------------------------------------
# 4. Parity Between Canonical and Legacy Daemons
# ---------------------------------------------------------------------------


def test_daemon_sandbox_wiring_parity() -> None:
    """cowork_to_code_bridge/daemon.py and daemon/daemon.py must maintain sandbox wiring parity."""
    canonical = (REPO_ROOT / "cowork_to_code_bridge" / "daemon.py").read_text()
    legacy = (REPO_ROOT / "daemon" / "daemon.py").read_text()

    needles = [
        "detect_sandbox_backend",
        "wrap_argv",
        "sandbox_backend = detect_sandbox_backend()",
        "argv = wrap_argv(argv, script, cwd, BRIDGE_ROOT, sandbox_backend)",
    ]

    for needle in needles:
        assert needle in canonical, f"canonical daemon missing marker: {needle!r}"
        assert needle in legacy, f"legacy daemon drifted, missing marker: {needle!r}"
