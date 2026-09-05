"""The client must resolve the same BRIDGE_ROOT the installed daemon serves.

Selfcheck was taught to read the daemon's launchd plist / systemd unit (PR #83),
but the client copies still preferred `$PWD/bridge`. When a project directory
contains a stale `bridge/` from an earlier install, every task is written into a
directory no daemon is watching — the caller sees a 30s TimeoutError naming the
daemon, while the daemon is healthy and idle a few directories away.

Reproduced live: `call_remote("scripts/mac_ram.sh")` from the project root timed
out, while the same call with BRIDGE_ROOT pointed at the served root returned
exit=0 immediately.

All three client copies (package, single-file, skill) must agree — see
docs/ and the single-file parity guard.
"""
from __future__ import annotations

import importlib.util
import plistlib
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
CLIENTS = {
    "package": REPO / "cowork_to_code_bridge" / "client.py",
    "single_file": REPO / "bridge_client.py",
    "skill": REPO / "skill" / "cowork-to-code-bridge" / "bridge_client.py",
}


def _load(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(params=sorted(CLIENTS), ids=sorted(CLIENTS))
def client(request):
    return _load(CLIENTS[request.param], f"client_{request.param}")


def _write_plist(home: Path, root: str) -> None:
    d = home / "Library" / "LaunchAgents"
    d.mkdir(parents=True, exist_ok=True)
    (d / "dev.cowork-to-code-bridge.daemon.plist").write_bytes(plistlib.dumps({
        "Label": "dev.cowork-to-code-bridge.daemon",
        "EnvironmentVariables": {"BRIDGE_ROOT": root},
    }))


def test_service_root_beats_stale_cwd_bridge(client, monkeypatch, tmp_path):
    """The regression: a leftover ./bridge must not win over the served root."""
    monkeypatch.setattr(client.platform, "system", lambda: "Darwin")
    monkeypatch.delenv("BRIDGE_ROOT", raising=False)
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))

    served = tmp_path / "served"; served.mkdir()
    _write_plist(tmp_path, str(served))

    stale = tmp_path / "project"; (stale / "bridge").mkdir(parents=True)
    monkeypatch.chdir(stale)

    assert client._resolve_bridge_root() == served


def test_explicit_env_var_still_wins(client, monkeypatch, tmp_path):
    """An explicit BRIDGE_ROOT is deliberate and outranks the service file."""
    monkeypatch.setattr(client.platform, "system", lambda: "Darwin")
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    _write_plist(tmp_path, str(tmp_path / "served"))
    override = tmp_path / "scratch"
    monkeypatch.setenv("BRIDGE_ROOT", str(override))
    assert client._resolve_bridge_root() == override


def test_cwd_bridge_used_when_no_service(client, monkeypatch, tmp_path):
    """Negative control: without an installed daemon, ./bridge is still valid."""
    monkeypatch.setattr(client.platform, "system", lambda: "Darwin")
    monkeypatch.delenv("BRIDGE_ROOT", raising=False)
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    proj = tmp_path / "project"; (proj / "bridge").mkdir(parents=True)
    monkeypatch.chdir(proj)
    assert client._resolve_bridge_root() == proj / "bridge"


def test_malformed_plist_does_not_raise(client, monkeypatch, tmp_path):
    """A corrupt service file degrades to the next candidate, never crashes."""
    monkeypatch.setattr(client.platform, "system", lambda: "Darwin")
    monkeypatch.delenv("BRIDGE_ROOT", raising=False)
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    d = tmp_path / "Library" / "LaunchAgents"; d.mkdir(parents=True)
    (d / "dev.cowork-to-code-bridge.daemon.plist").write_bytes(b"not a plist")
    proj = tmp_path / "project"; (proj / "bridge").mkdir(parents=True)
    monkeypatch.chdir(proj)
    assert client._resolve_bridge_root() == proj / "bridge"


def test_all_three_clients_resolve_identically(monkeypatch, tmp_path):
    """The three copies must never disagree about where the bridge is."""
    served = tmp_path / "served"; served.mkdir()
    _write_plist(tmp_path, str(served))
    results = {}
    for name, path in CLIENTS.items():
        m = _load(path, f"parity_{name}")
        monkeypatch.setattr(m.platform, "system", lambda: "Darwin")
        monkeypatch.delenv("BRIDGE_ROOT", raising=False)
        monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
        results[name] = m._resolve_bridge_root()
    assert len(set(results.values())) == 1, f"clients disagree: {results}"
