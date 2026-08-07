"""Guards for BRIDGE_ROOT resolution and the TCC-protected-root failure mode.

Two real outages motivated these tests, both of which presented as "the daemon
is registered but every task times out":

1. **Split-brain root.** selfcheck defaulted to ``$HOME/.cowork-to-code-bridge``
   while the installed daemon served whatever root the installer wrote into the
   launchd plist / systemd unit. selfcheck then pinged a directory no daemon was
   watching and blamed the daemon.

2. **TCC-protected root.** On macOS 13+, ``~/Documents``/``~/Desktop``/
   ``~/Downloads`` are TCC-protected. A daemon whose plist ``WorkingDirectory``
   lives there runs fine when started by hand (the shell has consent) but
   launchd cannot chdir into it and kills the job with EX_CONFIG (78) *before*
   Python starts — so nothing reaches daemon.log or daemon.err, and KeepAlive
   respawns it forever in silence.
"""
from __future__ import annotations

import importlib
import plistlib
import subprocess
from pathlib import Path

import pytest

from cowork_to_code_bridge import selfcheck


def _reload(monkeypatch, *, home: Path, env_root: str | None):
    """Re-import selfcheck with a patched HOME and BRIDGE_ROOT.

    Module-level resolution happens at import time, so the module must be
    reloaded for a changed environment to take effect.
    """
    monkeypatch.setenv("HOME", str(home))
    if env_root is None:
        monkeypatch.delenv("BRIDGE_ROOT", raising=False)
    else:
        monkeypatch.setenv("BRIDGE_ROOT", env_root)
    return importlib.reload(selfcheck)


def _write_plist(home: Path, bridge_root: str) -> None:
    p = home / "Library" / "LaunchAgents"
    p.mkdir(parents=True, exist_ok=True)
    target = p / "dev.cowork-to-code-bridge.daemon.plist"
    target.write_bytes(plistlib.dumps({
        "Label": "dev.cowork-to-code-bridge.daemon",
        "EnvironmentVariables": {"BRIDGE_ROOT": bridge_root},
        "WorkingDirectory": bridge_root,
    }))


def _write_unit(home: Path, bridge_root: str) -> None:
    d = home / ".config" / "systemd" / "user"
    d.mkdir(parents=True, exist_ok=True)
    (d / "cowork-to-code-bridge.service").write_text(
        "[Service]\n"
        f"Environment=BRIDGE_ROOT={bridge_root}\n"
    )


@pytest.fixture(autouse=True)
def _restore():
    """Every test reloads the module; restore the real one afterwards."""
    yield
    importlib.reload(selfcheck)


# ── root resolution ──────────────────────────────────────────────────────────

def test_reads_root_from_launchd_plist(monkeypatch, tmp_path):
    """With no env var, the plist's BRIDGE_ROOT wins over the default."""
    monkeypatch.setattr("platform.system", lambda: "Darwin")
    served = tmp_path / "served-root"
    served.mkdir()
    _write_plist(tmp_path, str(served))

    sc = _reload(monkeypatch, home=tmp_path, env_root=None)
    assert sc.BRIDGE_ROOT == served  # noqa: SIM300
    assert sc.BRIDGE_ROOT_SOURCE == "installed daemon service"


def test_reads_root_from_systemd_unit(monkeypatch, tmp_path):
    """Linux equivalent: parse Environment=BRIDGE_ROOT= from the unit file."""
    monkeypatch.setattr("platform.system", lambda: "Linux")
    served = tmp_path / "served-root"
    served.mkdir()
    _write_unit(tmp_path, str(served))

    sc = _reload(monkeypatch, home=tmp_path, env_root=None)
    assert sc.BRIDGE_ROOT == served  # noqa: SIM300
    assert sc.BRIDGE_ROOT_SOURCE == "installed daemon service"


def test_explicit_env_var_beats_service_definition(monkeypatch, tmp_path):
    """An explicit BRIDGE_ROOT is deliberate and must win over the plist."""
    monkeypatch.setattr("platform.system", lambda: "Darwin")
    _write_plist(tmp_path, str(tmp_path / "served-root"))
    override = tmp_path / "scratch"
    override.mkdir()

    sc = _reload(monkeypatch, home=tmp_path, env_root=str(override))
    assert sc.BRIDGE_ROOT == override  # noqa: SIM300
    assert sc.BRIDGE_ROOT_SOURCE == "BRIDGE_ROOT env var"


def test_falls_back_to_default_when_not_installed(monkeypatch, tmp_path):
    """No service file and no env var → the documented default."""
    monkeypatch.setattr("platform.system", lambda: "Darwin")
    sc = _reload(monkeypatch, home=tmp_path, env_root=None)
    assert sc.BRIDGE_ROOT == tmp_path / ".cowork-to-code-bridge"  # noqa: SIM300
    assert sc.BRIDGE_ROOT_SOURCE == "default"


def test_malformed_service_file_does_not_crash(monkeypatch, tmp_path):
    """A corrupt plist must degrade to the default, not raise."""
    monkeypatch.setattr("platform.system", lambda: "Darwin")
    p = tmp_path / "Library" / "LaunchAgents"
    p.mkdir(parents=True)
    (p / "dev.cowork-to-code-bridge.daemon.plist").write_bytes(b"not a plist")

    sc = _reload(monkeypatch, home=tmp_path, env_root=None)
    assert sc.BRIDGE_ROOT == tmp_path / ".cowork-to-code-bridge"  # noqa: SIM300


# ── mismatch is reported at the root check, not as a ping timeout ────────────

def test_mismatch_between_env_and_service_is_reported(monkeypatch, tmp_path):
    """The split-brain case fails check 1 with both paths named.

    Negative control: this is exactly the state that used to PASS here and then
    fail mysteriously at the ping check.
    """
    monkeypatch.setattr("platform.system", lambda: "Darwin")
    served = tmp_path / "served-root"
    served.mkdir()
    other = tmp_path / "other-root"
    other.mkdir()
    _write_plist(tmp_path, str(served))

    sc = _reload(monkeypatch, home=tmp_path, env_root=str(other))
    ok, detail = sc.check_bridge_root()
    assert ok is False
    assert str(served) in detail and str(other) in detail


def test_matching_roots_pass(monkeypatch, tmp_path):
    """No mismatch → check 1 passes and reports where the root came from."""
    monkeypatch.setattr("platform.system", lambda: "Darwin")
    served = tmp_path / "served-root"
    served.mkdir()
    _write_plist(tmp_path, str(served))

    sc = _reload(monkeypatch, home=tmp_path, env_root=None)
    ok, detail = sc.check_bridge_root()
    assert ok is True
    assert "installed daemon service" in detail


# ── EX_CONFIG (78) is diagnosed, not left as "not running" ───────────────────

def test_exit_78_is_diagnosed_as_tcc(monkeypatch, tmp_path):
    """A dead job with status 78 names TCC as the cause.

    launchd reports `-<TAB>78<TAB><label>` when it cannot chdir into a
    TCC-protected WorkingDirectory. That is unrecoverable by restarting, so the
    message must point at reinstalling with a different root.
    """
    monkeypatch.setattr("platform.system", lambda: "Darwin")
    sc = _reload(monkeypatch, home=tmp_path, env_root=str(tmp_path / "Documents" / "b"))

    monkeypatch.setattr(
        subprocess, "run",
        lambda *a, **k: subprocess.CompletedProcess(
            a[0], 0, stdout="-\t78\tdev.cowork-to-code-bridge.daemon\n", stderr=""),
    )
    ok, detail = sc.check_daemon_registered()
    assert ok is False
    assert "EX_CONFIG" in detail
    assert "TCC" in detail


def test_other_nonzero_exit_is_not_blamed_on_tcc(monkeypatch, tmp_path):
    """Negative control: a plain stopped job must NOT claim a TCC problem."""
    monkeypatch.setattr("platform.system", lambda: "Darwin")
    sc = _reload(monkeypatch, home=tmp_path, env_root=None)

    monkeypatch.setattr(
        subprocess, "run",
        lambda *a, **k: subprocess.CompletedProcess(
            a[0], 0, stdout="-\t0\tdev.cowork-to-code-bridge.daemon\n", stderr=""),
    )
    ok, detail = sc.check_daemon_registered()
    assert ok is False
    assert "TCC" not in detail


def test_running_daemon_still_passes(monkeypatch, tmp_path):
    """Negative control: a live pid passes regardless of the new branches."""
    monkeypatch.setattr("platform.system", lambda: "Darwin")
    sc = _reload(monkeypatch, home=tmp_path, env_root=None)

    monkeypatch.setattr(
        subprocess, "run",
        lambda *a, **k: subprocess.CompletedProcess(
            a[0], 0, stdout="4242\t0\tdev.cowork-to-code-bridge.daemon\n", stderr=""),
    )
    ok, detail = sc.check_daemon_registered()
    assert ok is True
    assert "4242" in detail


# ── the installer's TCC guard ───────────────────────────────────────────────
#
# install.sh pins BRIDGE_ROOT to "$HOME/.cowork-to-code-bridge" (line ~28) and
# does NOT honour a BRIDGE_ROOT from the environment, so the stock installer
# cannot land in a TCC directory. The guard exists for the paths that *can*:
# a hand-edited plist, a relocated home directory, or a future flag. These
# tests exercise the guard logic directly rather than driving a full install
# (which needs network and launchd).

# The OS check is injected rather than read from the host, so these tests are
# deterministic on every runner: CI must exercise BOTH the Darwin branch (where
# the guard fires) and the non-Darwin branch (where it must stay out of the
# way). Reading the real `uname` would silently skip half the contract on
# whichever platform the job happens to run on.
_GUARD = r'''
BRIDGE_ROOT="$1"
_OS="$2"
c_red() { printf "%s\n" "$1"; }
if [[ "$_OS" == "Darwin" ]]; then
  _root_real="$(cd "$(dirname "$BRIDGE_ROOT")" 2>/dev/null && pwd -P || echo "$BRIDGE_ROOT")"
  for _tcc in "$HOME/Documents" "$HOME/Desktop" "$HOME/Downloads"; do
    if [[ "$_root_real" == "$_tcc" || "$_root_real" == "$_tcc"/* ]]; then
      c_red "TCC: refusing $BRIDGE_ROOT"
      exit 1
    fi
  done
fi
echo "accepted"
'''


def _run_guard(home: Path, root: Path, os_name: str = "Darwin"):
    return subprocess.run(
        ["bash", "-c", _GUARD, "bash", str(root), os_name],
        env={"HOME": str(home), "PATH": "/usr/bin:/bin"},
        capture_output=True, text=True, timeout=30,
    )


@pytest.mark.parametrize("sub", ["Documents", "Desktop", "Downloads"])
def test_guard_refuses_tcc_protected_root(sub, tmp_path):
    """On macOS, a root inside any TCC-protected folder is refused."""
    root = tmp_path / sub / "bridge"
    root.parent.mkdir(parents=True)
    proc = _run_guard(tmp_path, root, os_name="Darwin")
    assert proc.returncode != 0
    assert "TCC" in proc.stdout + proc.stderr


@pytest.mark.parametrize("sub", ["Documents", "Desktop", "Downloads"])
def test_guard_is_a_noop_off_macos(sub, tmp_path):
    """Off macOS the guard must not fire — TCC is a macOS-only mechanism.

    ~/Documents carries no such restriction on Linux, and there is no launchd
    to fail. Refusing there would break perfectly valid Linux installs.
    """
    root = tmp_path / sub / "bridge"
    root.parent.mkdir(parents=True)
    proc = _run_guard(tmp_path, root, os_name="Linux")
    assert proc.returncode == 0, "TCC guard must not fire off macOS"
    assert "accepted" in proc.stdout


def test_guard_accepts_a_safe_root(tmp_path):
    """Negative control: a normal root under $HOME is accepted."""
    root = tmp_path / ".cowork-to-code-bridge"
    root.mkdir()
    proc = _run_guard(tmp_path, root, os_name="Darwin")
    assert proc.returncode == 0
    assert "accepted" in proc.stdout


def test_guard_accepts_lookalike_sibling(tmp_path):
    """Negative control: 'DocumentsArchive' must not match 'Documents'."""
    root = tmp_path / "DocumentsArchive" / "bridge"
    root.parent.mkdir(parents=True)
    proc = _run_guard(tmp_path, root, os_name="Darwin")
    assert proc.returncode == 0, "prefix match wrongly caught a sibling directory"


def test_installer_pins_root_outside_tcc():
    """install.sh's own default root is not TCC-protected.

    This is what actually protects stock installs; the guard is defence in
    depth behind it.
    """
    install = Path(__file__).resolve().parent.parent / "install.sh"
    text = install.read_text()
    assert 'BRIDGE_ROOT="$HOME/.cowork-to-code-bridge"' in text
    for bad in ("$HOME/Documents", "$HOME/Desktop", "$HOME/Downloads"):
        assert f'BRIDGE_ROOT="{bad}' not in text


def test_installer_carries_the_tcc_guard():
    """The guard must stay in install.sh — deleting it should fail CI."""
    install = Path(__file__).resolve().parent.parent / "install.sh"
    text = install.read_text()
    assert "TCC" in text, "install.sh lost its TCC guard"
    for d in ("Documents", "Desktop", "Downloads"):
        assert f'$HOME/{d}"' in text, f"TCC guard no longer covers {d}"
