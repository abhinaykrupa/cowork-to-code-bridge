"""A caller must not be able to turn an allowlisted script into arbitrary code.

The owner's controls are the script allowlist and BRIDGE_PERMISSION_CEILING.
Both assume the *script* is what runs. The per-task `env` field (exposed by
`call_remote(..., env=...)` / `queue_task`) was merged into the child
environment with the caller winning for every var outside a 7-name list, and
free to add any new one. Two lines were enough for code execution under the
most restrictive ceiling, running only a harmless `hello.sh`:

    env={"BASH_ENV": "/bridge/queue/payload.sh"}   # bash sources it first
    env={"PATH": "/bridge/queue:/usr/bin:/bin"}     # hijack `bash`, `git`, ...

The sandbox-writable BRIDGE_ROOT/.env was a second, persistent path to the same
place, since it is merged into every task's environment.

In the default layout the sandbox can also write scripts/ directly, so this is
defence in depth there. With BRIDGE_SCRIPTS pointed outside the mount (the
hardened layout), the allowlist and ceiling are the boundary, and this is the
bypass that would otherwise remain. Independently of layout, the old code also
contradicted its own comment: it said a caller "can only SET vars not already
in daemon env" while letting the caller override any non-protected one.

Each test asserts on a real side effect — a marker file the injected code would
create — never on a log line, paired with a control proving a benign variable
still reaches the script.
"""
from __future__ import annotations

import importlib
import json
import os
import threading

import pytest


@pytest.fixture
def bridge(tmp_path, monkeypatch):
    root = tmp_path / "bridge"
    root.mkdir()
    monkeypatch.setenv("BRIDGE_ROOT", str(root))
    monkeypatch.setenv("BRIDGE_TOKEN", "test-token")
    monkeypatch.setenv("BRIDGE_PERMISSION_CEILING", "plan")
    monkeypatch.delenv("BRIDGE_CALLER_ENV", raising=False)
    monkeypatch.delenv("BRIDGE_MAX_TASK_AGE_SEC", raising=False)

    def _build():
        import cowork_to_code_bridge.daemon as d
        importlib.reload(d)
        for sub in (d.QUEUE, d.RESULTS, d.PROCESSED, d.INFLIGHT, d.PROGRESS,
                    d.CANCEL, d.SCRIPTS_DIR):
            sub.mkdir(parents=True, exist_ok=True)
        hello = d.SCRIPTS_DIR / "hello.sh"
        hello.write_text("#!/usr/bin/env bash\necho hello\n")
        hello.chmod(0o755)
        show = d.SCRIPTS_DIR / "show_env.sh"
        show.write_text("#!/usr/bin/env bash\nenv | sort\n")
        show.chmod(0o755)
        return d

    return _build, root, tmp_path


def _run(d, cmd_id, env=None, script="scripts/hello.sh"):
    q = d.QUEUE / f"{cmd_id}.json"
    payload = {"id": cmd_id, "script": script, "args": [], "timeout": 10,
               "token": "test-token"}
    if env is not None:
        payload["env"] = env
    q.write_text(json.dumps(payload))
    d.run_one(q, "test-token", {}, {})
    return json.loads((d.RESULTS / f"{cmd_id}.json").read_text())


def _env_lines(res):
    return dict(line.split("=", 1) for line in res["stdout"].splitlines() if "=" in line)


# ── the two PoCs ─────────────────────────────────────────────────────────────

def test_bash_env_injection_does_not_execute(bridge):
    build, root, tmp = bridge
    d = build()
    pwned = tmp / "PWNED"
    payload = root / "queue" / "payload.txt"
    payload.write_text(f"touch {pwned}\n")
    res = _run(d, "bashenv", env={"BASH_ENV": str(payload)})
    assert res["exit_code"] == 0
    assert not pwned.exists(), "BASH_ENV from the caller was sourced by the script"


def test_path_override_does_not_hijack_binaries(bridge):
    build, root, tmp = bridge
    d = build()
    pwned = tmp / "PWNED_PATH"
    fake = root / "queue" / "bash"
    fake.write_text(f"#!/bin/sh\ntouch {pwned}\n")
    fake.chmod(0o755)
    _run(d, "pathhijack", env={"PATH": f"{root / 'queue'}:/usr/bin:/bin"})
    assert not pwned.exists(), "caller PATH let a planted binary run"


# ── the rules behind the fix ─────────────────────────────────────────────────

@pytest.mark.parametrize("name", [
    "LD_PRELOAD", "DYLD_INSERT_LIBRARIES", "PYTHONSTARTUP", "PYTHONPATH",
    "NODE_OPTIONS", "PERL5OPT", "RUBYOPT", "GIT_SSH_COMMAND", "GIT_CONFIG_GLOBAL",
    "ANTHROPIC_BASE_URL", "CLAUDE_CONFIG_DIR", "HTTPS_PROXY", "AWS_CONFIG_FILE",
    "HOME", "XDG_CONFIG_HOME", "ZDOTDIR", "LESSOPEN", "OPENSSL_CONF",
    "BASH_FUNC_ls%%", "http_proxy", "lower_case", "BAD-NAME", "",
])
def test_dangerous_or_malformed_names_are_dropped(bridge, name):
    build, _, _ = bridge
    d = build()
    res = _run(d, "deny", env={name: "INJECTED_VALUE"}, script="scripts/show_env.sh")
    assert "INJECTED_VALUE" not in res["stdout"], f"{name!r} reached the script"
    assert name in res.get("env_rejected", []), "caller is not told what was dropped"


def test_caller_cannot_override_an_existing_owner_var(bridge, monkeypatch):
    build, _, _ = bridge
    monkeypatch.setenv("OWNER_SETTING", "owner-value")
    d = build()
    res = _run(d, "override", env={"OWNER_SETTING": "caller-value"},
               script="scripts/show_env.sh")
    assert _env_lines(res).get("OWNER_SETTING") == "owner-value"
    assert "OWNER_SETTING" in res.get("env_rejected", [])


def test_owner_can_disable_caller_env_entirely(bridge, monkeypatch):
    build, _, _ = bridge
    monkeypatch.setenv("BRIDGE_CALLER_ENV", "0")
    d = build()
    res = _run(d, "off", env={"MY_FLAG": "1"}, script="scripts/show_env.sh")
    assert "MY_FLAG" not in _env_lines(res)


# ── .env: the persistent second path ─────────────────────────────────────────

def test_dotenv_cannot_inject_bash_env(bridge):
    build, root, tmp = bridge
    pwned = tmp / "PWNED_DOTENV"
    payload = root / "p.sh"
    payload.write_text(f"touch {pwned}\n")
    (root / ".env").write_text(f"BRIDGE_TOKEN=test-token\nBASH_ENV={payload}\n")
    d = build()
    _run(d, "dotenv")
    assert not pwned.exists(), "BASH_ENV from the sandbox-writable .env was honoured"


def test_dotenv_fifo_does_not_hang(bridge):
    build, root, _ = bridge
    d = build()
    os.mkfifo(root / ".env")
    t = threading.Thread(target=d.load_env, daemon=True)
    t.start()
    t.join(timeout=5)
    stuck = t.is_alive()
    if stuck:
        with open(root / ".env", "w"):
            pass
    assert not stuck, "a FIFO at .env blocks every task"


# ── negative controls ────────────────────────────────────────────────────────

def test_benign_caller_var_still_reaches_the_script(bridge):
    build, _, _ = bridge
    d = build()
    res = _run(d, "benign", env={"MY_APP_MODE": "staging"}, script="scripts/show_env.sh")
    assert _env_lines(res).get("MY_APP_MODE") == "staging"
    assert "MY_APP_MODE" not in res.get("env_rejected", [])


def test_no_env_field_means_no_env_rejected_key(bridge):
    build, _, _ = bridge
    d = build()
    res = _run(d, "plain")
    assert res["exit_code"] == 0 and "env_rejected" not in res


def test_benign_dotenv_key_still_loads(bridge):
    build, root, _ = bridge
    (root / ".env").write_text("BRIDGE_TOKEN=test-token\nMY_DOTENV_KEY=present\n")
    d = build()
    res = _run(d, "dotenv_ok", script="scripts/show_env.sh")
    assert _env_lines(res).get("MY_DOTENV_KEY") == "present"


def test_script_sees_the_root_the_daemon_serves(bridge):
    """Even with a misleading .env, $BRIDGE_ROOT in the child is the real root."""
    build, root, tmp = bridge
    (root / ".env").write_text(f"BRIDGE_TOKEN=test-token\nBRIDGE_ROOT={tmp / 'elsewhere'}\n")
    d = build()
    res = _run(d, "root", script="scripts/show_env.sh")
    assert _env_lines(res).get("BRIDGE_ROOT") == str(root)


def test_hardened_layout_ignores_scripts_planted_in_the_mount(tmp_path, monkeypatch):
    """With BRIDGE_SCRIPTS outside the mount, a script the sandbox writes into
    BRIDGE_ROOT/scripts/ is not runnable — the allowlist is a real boundary."""
    root = tmp_path / "bridge"
    trusted = tmp_path / "owner_scripts"   # NOT under the mount
    for p in (root, trusted):
        p.mkdir()
    monkeypatch.setenv("BRIDGE_ROOT", str(root))
    monkeypatch.setenv("BRIDGE_SCRIPTS", str(trusted))
    monkeypatch.setenv("BRIDGE_TOKEN", "test-token")
    import cowork_to_code_bridge.daemon as d
    importlib.reload(d)
    for sub in (d.QUEUE, d.RESULTS, d.PROCESSED, d.INFLIGHT, d.PROGRESS, d.CANCEL):
        sub.mkdir(parents=True, exist_ok=True)
    pwned = tmp_path / "PWNED_PLANTED"
    planted = root / "scripts"
    planted.mkdir()
    (planted / "evil.sh").write_text(f"#!/bin/sh\ntouch {pwned}\n")
    (planted / "evil.sh").chmod(0o755)
    ok = trusted / "ok.sh"
    ok.write_text("#!/bin/sh\necho trusted\n")
    ok.chmod(0o755)

    res = _run(d, "planted", script="scripts/evil.sh")
    assert not pwned.exists(), "a script planted inside the mount ran"
    assert res["exit_code"] == -1

    res = _run(d, "trusted", script="scripts/ok.sh")   # negative control
    assert res["exit_code"] == 0 and "trusted" in res["stdout"]
