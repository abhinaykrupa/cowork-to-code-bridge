"""Opt-in hardened install: the allowlist, and everything else the host
executes, lives outside the folder Cowork mounts read-write.

In the default layout the sandbox can write BRIDGE_ROOT/scripts/, so it can add
its own "allowlisted" script. BRIDGE_HARDENED=1 moves the scripts directory out
of the mount and records it in the service definition as BRIDGE_SCRIPTS.

Found while building it: on non-systemd Linux, cron ran BRIDGE_ROOT/start-daemon.sh
at every reboot, and that starter sourced BRIDGE_ROOT/lib/daemon_service.sh — two
sandbox-writable files executed by the host. Hardened mode moves both out too.

Uninstall must remove a hardened scripts directory without ever rm -rf'ing a
path merely because a service definition names it; the installer's marker file
is the only licence to delete.

Shell functions are tested by extracting their real text from the shipped
scripts, so the tests cannot drift from what runs.
"""
from __future__ import annotations

import importlib
import plistlib
import re
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
INSTALL = (REPO / "install.sh").read_text()
UNINSTALL = (REPO / "daemon" / "uninstall.sh").read_text()
SERVICE_LIB = (REPO / "scripts" / "lib" / "daemon_service.sh").read_text()
MARKER = ".cowork-to-code-bridge-scripts"


def _fn(text: str, name: str) -> str:
    m = re.search(rf"^{name}\(\) \{{.*?^\}}\n", text, re.S | re.M)
    assert m, f"{name}() missing"
    return m.group(0)


def _bash(code: str, *args: str, env: dict | None = None) -> subprocess.CompletedProcess:
    return subprocess.run(["bash", "-c", code, "bash", *args], capture_output=True,
                          text=True, env={"PATH": "/usr/bin:/bin", **(env or {})})


# ── layout selection ─────────────────────────────────────────────────────────

def test_default_layout_is_unchanged(tmp_path):
    out = _bash(_fn(INSTALL, "bridge_layout") + 'bridge_layout "$1" 0 ""', "/r",
                env={"HOME": str(tmp_path)})
    assert out.stdout.strip() == "/r/scripts|/r"


def test_hardened_layout_moves_scripts_and_host_state_out(tmp_path):
    out = _bash(_fn(INSTALL, "bridge_layout") + 'bridge_layout "$1" 1 ""', "/r",
                env={"HOME": str(tmp_path)})
    scripts, state = out.stdout.strip().split("|")
    assert scripts == f"{tmp_path}/.bridge-scripts"
    assert state == f"{tmp_path}/.local/share/cowork-to-code-bridge"
    assert not scripts.startswith("/r") and not state.startswith("/r")


def test_hardened_scripts_dir_can_be_overridden(tmp_path):
    out = _bash(_fn(INSTALL, "bridge_layout") + 'bridge_layout "$1" 1 "$2"', "/r", "/opt/s",
                env={"HOME": str(tmp_path)})
    assert out.stdout.strip().split("|")[0] == "/opt/s"


# ── install.sh wiring ────────────────────────────────────────────────────────

def test_no_script_is_written_into_the_mount_directly():
    """Every bundled script goes through $SCRIPTS_DIR, never $BRIDGE_ROOT/scripts."""
    stray = re.findall(r'(?:cat >|chmod \+x) "\$BRIDGE_ROOT/scripts', INSTALL)
    assert not stray, f"{len(stray)} script writes bypass $SCRIPTS_DIR"
    assert INSTALL.count('cat > "$SCRIPTS_DIR/') >= 20


def test_service_definitions_carry_bridge_scripts():
    assert '<key>BRIDGE_SCRIPTS</key><string>$SCRIPTS_DIR</string>' in INSTALL
    assert 'Environment=BRIDGE_SCRIPTS=$SCRIPTS_DIR' in INSTALL


def test_reboot_starter_and_its_library_live_in_host_state_dir():
    assert 'START_SCRIPT="$HOST_STATE_DIR/start-daemon.sh"' in INSTALL
    assert 'START_SCRIPT="$BRIDGE_ROOT/start-daemon.sh"' not in INSTALL
    assert '"$HOST_STATE_DIR/lib/daemon_service.sh"' in INSTALL
    # The generated starter sources the host-side copy and exports BRIDGE_SCRIPTS.
    assert 'echo "source \\"$HOST_STATE_DIR/lib/daemon_service.sh\\""' in INSTALL
    assert 'echo "export BRIDGE_SCRIPTS"' in INSTALL


def test_manual_start_exports_bridge_scripts():
    assert '[[ -n "${BRIDGE_SCRIPTS:-}" ]] && export BRIDGE_SCRIPTS' in SERVICE_LIB


# ── cron cleanup covers both starter locations ───────────────────────────────

@pytest.mark.parametrize("starter", [
    "/home/u/.cowork-to-code-bridge/start-daemon.sh",
    "/home/u/.local/share/cowork-to-code-bridge/start-daemon.sh",
])
def test_cron_removal_matches_both_layouts(tmp_path, starter):
    store = tmp_path / "crontab.txt"
    store.write_text(f"0 * * * * other-job\n# cowork-to-code-bridge @reboot\n@reboot {starter}\n")
    stub = tmp_path / "bin"
    stub.mkdir()
    (stub / "crontab").write_text(
        f'#!/bin/bash\nif [ "$1" = "-l" ]; then cat {store}; else cat > {store}; fi\n')
    (stub / "crontab").chmod(0o755)
    # BRIDGE_ROOT is always set in real runs. Leaving it unset made the old
    # pattern collapse to "/start-daemon.sh", which matched both paths by
    # accident and let this test pass against the buggy code.
    _bash(SERVICE_LIB + "\nbridge_remove_cron_reboot",
          env={"PATH": f"{stub}:/usr/bin:/bin", "HOME": "/home/u",
               "BRIDGE_ROOT": "/home/u/.cowork-to-code-bridge"})
    left = store.read_text()
    assert "start-daemon.sh" not in left, left
    assert "other-job" in left, "cron cleanup removed an unrelated job"


# ── uninstall.sh: the marker is the only licence to delete ───────────────────

def _remove(dir_: Path, root: Path) -> int:
    code = f'SCRIPTS_MARKER="{MARKER}"\n' + _fn(UNINSTALL, "remove_marked_scripts_dir") + \
        'remove_marked_scripts_dir "$1" "$2"'
    return _bash(code, str(dir_), str(root)).returncode


def test_uninstall_sh_removes_a_marked_dir_outside_the_root(tmp_path):
    d = tmp_path / "s"; d.mkdir(); (d / MARKER).touch()
    assert _remove(d, tmp_path / "root") == 0 and not d.exists()


def test_uninstall_sh_keeps_an_unmarked_dir(tmp_path):
    d = tmp_path / "users_own_bin"; d.mkdir(); (d / "precious.sh").write_text("x")
    assert _remove(d, tmp_path / "root") != 0 and (d / "precious.sh").exists()


def test_uninstall_sh_keeps_a_marked_dir_inside_the_root(tmp_path):
    root = tmp_path / "root"; d = root / "scripts"; d.mkdir(parents=True); (d / MARKER).touch()
    assert _remove(d, root) != 0 and d.exists()


def test_uninstall_sh_keeps_a_symlinked_dir(tmp_path):
    real = tmp_path / "real"; real.mkdir(); (real / MARKER).touch()
    link = tmp_path / "link"; link.symlink_to(real, target_is_directory=True)
    assert _remove(link, tmp_path / "root") != 0 and real.exists()


# ── uninstall.py mirrors it ──────────────────────────────────────────────────

@pytest.fixture
def un(monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    monkeypatch.delenv("XDG_DATA_HOME", raising=False)
    import cowork_to_code_bridge.uninstall as u
    return importlib.reload(u)


def test_uninstall_py_reads_scripts_dir_from_plist(un, tmp_path):
    plist = tmp_path / "p.plist"
    plist.write_bytes(plistlib.dumps({"EnvironmentVariables": {"BRIDGE_SCRIPTS": "/x/s"}}))
    assert un.service_scripts_dir(plist, tmp_path / "none", tmp_path / "none") == Path("/x/s")


def test_uninstall_py_reads_scripts_dir_from_unit_and_starter(un, tmp_path):
    unit = tmp_path / "u.service"
    unit.write_text("[Service]\nEnvironment=BRIDGE_SCRIPTS=/y/s\n")
    assert un.service_scripts_dir(tmp_path / "none", unit, tmp_path / "none") == Path("/y/s")
    starter = tmp_path / "start.sh"
    starter.write_text('#!/bin/bash\nBRIDGE_SCRIPTS="/z/s"\nexport BRIDGE_SCRIPTS\n')
    assert un.service_scripts_dir(tmp_path / "none", tmp_path / "none", starter) == Path("/z/s")


def test_uninstall_py_marker_guard(un, tmp_path):
    root = tmp_path / "root"; root.mkdir()
    marked = tmp_path / "m"; marked.mkdir(); (marked / MARKER).touch()
    unmarked = tmp_path / "u"; unmarked.mkdir(); (unmarked / "keep.sh").write_text("x")
    inside = root / "scripts"; inside.mkdir(); (inside / MARKER).touch()
    assert un.remove_marked_scripts_dir(marked, root) is True and not marked.exists()
    assert un.remove_marked_scripts_dir(unmarked, root) is False and unmarked.exists()
    assert un.remove_marked_scripts_dir(inside, root) is False and inside.exists()
    assert un.remove_marked_scripts_dir(None, root) is False


def test_uninstall_py_host_state_dir_is_outside_default_root(un):
    assert un.HOST_STATE_DIR != un.DEFAULT_BRIDGE_ROOT
    assert un.DEFAULT_BRIDGE_ROOT not in un.HOST_STATE_DIR.parents
