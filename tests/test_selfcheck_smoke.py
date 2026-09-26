"""Tests for selfcheck --smoke mode (used by the CI `selfcheck` job / README badge).

--smoke runs every check but always exits 0, because a fresh CI runner has no
daemon/skill installed. It asserts only that the diagnostic plumbing executes
end-to-end. Real (non-smoke) runs still exit 1 when checks fail.
"""
from __future__ import annotations

import os
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


def test_warn_is_shown_but_not_counted_as_a_failure(monkeypatch, capsys):
    """A missing claude CLI is advisory: the bridge works without it."""
    monkeypatch.setattr(selfcheck, "CHECKS", [
        ("advisory", lambda: (None, "optional thing missing")),
        ("fine", lambda: (True, "ok")),
    ])
    assert selfcheck.run_checks() == 0
    assert "WARN" in capsys.readouterr().out


def test_fail_is_still_counted(monkeypatch):
    """Negative control: WARN handling must not swallow real failures."""
    monkeypatch.setattr(selfcheck, "CHECKS", [
        ("advisory", lambda: (None, "x")), ("broken", lambda: (False, "y"))])
    assert selfcheck.run_checks() == 1


def test_missing_claude_cli_is_a_warning(monkeypatch, tmp_path):
    monkeypatch.setattr(selfcheck.shutil, "which", lambda _n: None)
    monkeypatch.setattr(selfcheck.Path, "home", classmethod(lambda cls: tmp_path))
    monkeypatch.setattr(selfcheck.os.path, "exists", lambda _p: False)
    real_exists = selfcheck.Path.exists
    monkeypatch.setattr(selfcheck.Path, "exists",
                        lambda self: False if self.name == "claude" else real_exists(self))
    ok, detail = selfcheck.check_claude_cli()
    assert ok is None and "run_claude.sh" in detail


@pytest.mark.parametrize("cmdline", [
    # What install.sh actually launches first: the console script. The first
    # version of this test only covered the module form and passed while the
    # real e2e failed.
    b"/usr/bin/python3\x00/home/u/.local/bin/cowork-to-code-bridge-daemon\x00",
    b"python3\x00-m\x00cowork_to_code_bridge.daemon\x00",
])
def test_linux_manual_daemon_is_recognised(monkeypatch, tmp_path, cmdline):
    """No systemd user bus -> the installer runs a setsid daemon; that's healthy."""
    monkeypatch.setattr(selfcheck.platform, "system", lambda: "Linux")
    monkeypatch.setattr(selfcheck.subprocess, "run", lambda *a, **k: subprocess.CompletedProcess(
        a[0], 1, stdout="inactive\n", stderr=""))
    monkeypatch.setattr(selfcheck, "BRIDGE_ROOT", tmp_path)
    (tmp_path / "daemon.pid").write_text(str(os.getpid()))
    fake_proc = tmp_path / "proc_cmdline"
    fake_proc.write_bytes(cmdline)
    real_path = selfcheck.Path
    monkeypatch.setattr(selfcheck, "Path", lambda p, *r: fake_proc
                        if str(p).startswith("/proc/") else real_path(p, *r))
    ok, detail = selfcheck.check_daemon_registered()
    assert ok is True and "manual daemon" in detail


def test_linux_stale_pidfile_pointing_at_another_process_is_not_healthy(monkeypatch, tmp_path):
    """Negative control: the pidfile is sandbox-writable; a live but unrelated
    pid must not count as a running bridge."""
    monkeypatch.setattr(selfcheck.platform, "system", lambda: "Linux")
    monkeypatch.setattr(selfcheck.subprocess, "run", lambda *a, **k: subprocess.CompletedProcess(
        a[0], 1, stdout="inactive\n", stderr=""))
    monkeypatch.setattr(selfcheck, "BRIDGE_ROOT", tmp_path)
    (tmp_path / "daemon.pid").write_text(str(os.getpid()))
    fake_proc = tmp_path / "proc_cmdline"
    fake_proc.write_bytes(b"/usr/bin/vim\x00notes.txt\x00")
    real_path = selfcheck.Path
    monkeypatch.setattr(selfcheck, "Path", lambda p, *r: fake_proc
                        if str(p).startswith("/proc/") else real_path(p, *r))
    ok, _ = selfcheck.check_daemon_registered()
    assert ok is False
