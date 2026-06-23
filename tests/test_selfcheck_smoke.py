"""Tests for selfcheck --smoke mode (used by the CI `selfcheck` job / README badge).

--smoke runs every check but always exits 0, because a fresh CI runner has no
daemon/skill installed. It asserts only that the diagnostic plumbing executes
end-to-end. Real (non-smoke) runs still exit 1 when checks fail.
"""
from __future__ import annotations

import subprocess
import sys

import pytest

from cowork_to_code_bridge import selfcheck


def test_run_checks_returns_failure_count():
    """run_checks() runs every CHECK and returns an int in [0, len(CHECKS)]."""
    failures = selfcheck.run_checks()
    assert isinstance(failures, int)
    assert 0 <= failures <= len(selfcheck.CHECKS)


def test_smoke_mode_always_exits_zero(monkeypatch):
    """--smoke exits 0 even when every underlying check fails."""
    # Force every check to fail; smoke mode must still exit 0.
    monkeypatch.setattr(
        selfcheck, "CHECKS",
        [("always fails", lambda: (False, "forced failure"))],
    )
    monkeypatch.setattr(sys, "argv", ["selfcheck", "--smoke"])
    with pytest.raises(SystemExit) as exc:
        selfcheck.main()
    assert exc.value.code == 0


def test_non_smoke_exits_nonzero_on_failure(monkeypatch):
    """Without --smoke, a failing check exits 1 (the real diagnostic contract)."""
    monkeypatch.setattr(
        selfcheck, "CHECKS",
        [("always fails", lambda: (False, "forced failure"))],
    )
    monkeypatch.setattr(sys, "argv", ["selfcheck"])
    with pytest.raises(SystemExit) as exc:
        selfcheck.main()
    assert exc.value.code == 1


def test_smoke_via_console_subprocess():
    """The installed console script runs in --smoke and exits 0 end-to-end."""
    result = subprocess.run(
        [sys.executable, "-m", "cowork_to_code_bridge.selfcheck", "--smoke"],
        capture_output=True, text=True, timeout=60,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "Smoke OK" in result.stdout
