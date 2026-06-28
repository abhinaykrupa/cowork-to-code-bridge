from __future__ import annotations

import os
import platform
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
INSTALL_SH = REPO_ROOT / "install.sh"
IS_MACOS = platform.system() == "Darwin"

# mac_ram.sh prints "Total RAM:" on macOS (sysctl branch) but uses `free`/`/proc`
# on Linux, where the output is the `free -h` table ("Mem:"). The expected
# fragment must match whichever OS the test actually runs on.
RAM_FRAGMENT = "Total RAM:" if IS_MACOS else "Mem:"


def _extract_script(script_name: str, marker: str) -> str:
    lines = INSTALL_SH.read_text().splitlines()
    start = None
    body: list[str] = []
    prefix = f'cat > "$BRIDGE_ROOT/scripts/{script_name}" <<\'{marker}\''

    for index, line in enumerate(lines):
        if line == prefix:
            start = index + 1
            break

    if start is None:
        raise AssertionError(f"Could not find {script_name} in install.sh")

    for line in lines[start:]:
        if line == marker:
            return "\n".join(body) + "\n"
        body.append(line)

    raise AssertionError(f"Could not find closing marker {marker} for {script_name}")


@pytest.fixture()
def generated_scripts(tmp_path: Path) -> Path:
    scripts_dir = tmp_path / "scripts"
    scripts_dir.mkdir()

    for script_name, marker in [
        ("mac_health.sh", "MH"),
        ("mac_ram.sh", "MR"),
        ("mac_disk.sh", "MD"),
        ("mac_top.sh", "MT"),
        ("mac_network.sh", "MN"),
    ]:
        script_path = scripts_dir / script_name
        script_path.write_text(_extract_script(script_name, marker))
        script_path.chmod(0o755)

    return scripts_dir


@pytest.mark.parametrize(
    ("script_name", "args", "expected_fragments"),
    [
        (
            "mac_health.sh",
            [],
            [
                "=== HOST ===",
                "=== UPTIME / LOAD ===",
                "=== CPU ===",
                "=== MEMORY ===",
                "=== DISK ===",
                "=== TOP 5 PROCS BY CPU ===",
            ],
        ),
        ("mac_ram.sh", [], [RAM_FRAGMENT]),
        ("mac_disk.sh", [], ["=== DISK USAGE ===", "=== ALL MOUNTED VOLUMES ==="]),
        ("mac_top.sh", ["5"], ["=== by CPU ===", "=== by MEM ==="]),
        (
            "mac_network.sh",
            [],
            [
                "=== interfaces (active) ===",
                "=== default route ===",
                "=== connectivity ===",
            ],
        ),
    ],
)
def test_generated_system_scripts_exit_zero_and_print_expected_sections(
    generated_scripts: Path, script_name: str, args: list[str], expected_fragments: list[str]
) -> None:
    result = subprocess.run(
        [str(generated_scripts / script_name), *args],
        check=False,
        capture_output=True,
        text=True,
        env={**os.environ, "LC_ALL": "C"},
    )

    assert result.returncode == 0, result.stderr
    for fragment in expected_fragments:
        # mac_ram.sh on Linux uses `free` (-> "Mem:"), or falls back to
        # /proc/meminfo (-> "MemTotal:") on the rare box without `free`.
        if fragment == "Mem:":
            assert ("Mem:" in result.stdout) or ("MemTotal" in result.stdout), result.stdout
        else:
            assert fragment in result.stdout


@pytest.mark.parametrize(
    ("script_name", "marker"),
    [
        ("mac_health.sh", "MH"),
        ("mac_ram.sh", "MR"),
        ("mac_disk.sh", "MD"),
        ("mac_top.sh", "MT"),
        ("mac_network.sh", "MN"),
    ],
)
def test_example_system_scripts_match_install_templates(script_name: str, marker: str) -> None:
    example_path = REPO_ROOT / "examples" / "allowed_scripts" / script_name
    assert example_path.read_text() == _extract_script(script_name, marker)


# ─────────────────────────────────────────────────────────────────────────────
# mac_health.sh --json tests
# ─────────────────────────────────────────────────────────────────────────────

@pytest.fixture()
def mac_health_script(tmp_path: Path) -> Path:
    script = tmp_path / "mac_health.sh"
    script.write_text(_extract_script("mac_health.sh", "MH"))
    script.chmod(0o755)
    return script


def test_mac_health_default_text_output(mac_health_script: Path) -> None:
    """Default (no flag) output is human-readable text with expected sections."""
    result = subprocess.run(
        [str(mac_health_script)],
        capture_output=True, text=True, check=False,
        env={**os.environ, "LC_ALL": "C"},
    )
    assert result.returncode == 0, result.stderr
    for section in ["=== HOST ===", "=== UPTIME / LOAD ===", "=== MEMORY ===", "=== DISK ==="]:
        assert section in result.stdout, f"missing {section!r} in text output"


def test_mac_health_json_flag_valid_json(mac_health_script: Path) -> None:
    """--json flag produces valid, parseable JSON."""
    import json
    result = subprocess.run(
        [str(mac_health_script), "--json"],
        capture_output=True, text=True, check=False,
        env={**os.environ, "LC_ALL": "C"},
    )
    assert result.returncode == 0, result.stderr
    data = json.loads(result.stdout)  # raises if invalid JSON
    assert isinstance(data, dict)


def test_mac_health_json_has_required_keys(mac_health_script: Path) -> None:
    """--json output contains all documented fields."""
    import json
    result = subprocess.run(
        [str(mac_health_script), "--json"],
        capture_output=True, text=True, check=False,
        env={**os.environ, "LC_ALL": "C"},
    )
    assert result.returncode == 0, result.stderr
    data = json.loads(result.stdout)
    required = {
        "host", "os", "uptime",
        "load_1m", "load_5m", "load_15m",
        "memory_total_bytes", "memory_free_bytes", "memory_used_bytes", "memory_used_pct",
        "disk_total_1k", "disk_used_1k", "disk_avail_1k", "disk_used_pct",
        "top_procs",
    }
    missing = required - data.keys()
    assert not missing, f"missing keys in JSON output: {missing}"


def test_mac_health_json_top_procs_structure(mac_health_script: Path) -> None:
    """top_procs is a list of dicts with expected per-process keys."""
    import json
    result = subprocess.run(
        [str(mac_health_script), "--json"],
        capture_output=True, text=True, check=False,
        env={**os.environ, "LC_ALL": "C"},
    )
    assert result.returncode == 0, result.stderr
    data = json.loads(result.stdout)
    procs = data["top_procs"]
    assert isinstance(procs, list)
    for proc in procs:
        for key in ("pid", "cpu_pct", "mem_pct", "name"):
            assert key in proc, f"proc missing key {key!r}: {proc}"


def test_mac_health_json_memory_bytes_positive(mac_health_script: Path) -> None:
    """memory_total_bytes should be a positive integer on any real machine."""
    import json
    result = subprocess.run(
        [str(mac_health_script), "--json"],
        capture_output=True, text=True, check=False,
        env={**os.environ, "LC_ALL": "C"},
    )
    assert result.returncode == 0, result.stderr
    data = json.loads(result.stdout)
    assert isinstance(data["memory_total_bytes"], int)
    assert data["memory_total_bytes"] > 0, "memory_total_bytes should be > 0"


def test_mac_health_text_mode_unchanged(mac_health_script: Path) -> None:
    """Text output must NOT contain JSON artefacts (no braces/quotes at line start)."""
    result = subprocess.run(
        [str(mac_health_script)],
        capture_output=True, text=True, check=False,
        env={**os.environ, "LC_ALL": "C"},
    )
    assert result.returncode == 0, result.stderr
    # First character of output should not be '{' (that would mean JSON leaked into text mode)
    assert not result.stdout.strip().startswith("{"), "text mode output looks like JSON"


# ─────────────────────────────────────────────────────────────────────────────
# process_kill.sh tests
# ─────────────────────────────────────────────────────────────────────────────

@pytest.fixture()
def process_kill_script(tmp_path: Path) -> Path:
    """Extract process_kill.sh from install.sh into tmp dir and make executable."""
    script_path = tmp_path / "process_kill.sh"
    script_path.write_text(_extract_script("process_kill.sh", "PK"))
    script_path.chmod(0o755)
    return script_path


def _fake_kill(tmp_path: Path, behaviour: str) -> Path:
    """Create a fake kill binary.

    behaviour:
      'success'  — exits 0 for both -0 (exists check) and -TERM
      'no_proc'  — exits 1 for -0 (process not found)
    """
    kill = tmp_path / "fake_kill"
    if behaviour == "success":
        kill.write_text("#!/usr/bin/env bash\nexit 0\n")
    else:  # no_proc
        kill.write_text("#!/usr/bin/env bash\nexit 1\n")
    kill.chmod(0o755)
    return kill


def _fake_pgrep(tmp_path: Path, pids: list[int] | None) -> Path:
    """Create a fake pgrep that returns given PIDs (one per line), or exits 1 if None."""
    pgrep = tmp_path / "fake_pgrep"
    if pids is None:
        pgrep.write_text("#!/usr/bin/env bash\nexit 1\n")
    else:
        output = "\\n".join(str(p) for p in pids)
        pgrep.write_text(f'#!/usr/bin/env bash\nprintf "{output}\\n"\nexit 0\n')
    pgrep.chmod(0o755)
    return pgrep


def _run_pk(script: Path, args: list[str], env: dict | None = None) -> subprocess.CompletedProcess:
    merged = {**os.environ, **(env or {})}
    return subprocess.run(
        [str(script), *args],
        capture_output=True, text=True, check=False, env=merged,
    )


# ── Safety guards ─────────────────────────────────────────────────────────────

def test_process_kill_refuses_pid_le_10(process_kill_script: Path, tmp_path: Path) -> None:
    fake_kill = _fake_kill(tmp_path, "success")
    result = _run_pk(process_kill_script, ["5"], {"BRIDGE_KILL_CMD": str(fake_kill)})
    assert result.returncode != 0
    assert "10" in result.stderr


def test_process_kill_refuses_pid_1(process_kill_script: Path, tmp_path: Path) -> None:
    fake_kill = _fake_kill(tmp_path, "success")
    result = _run_pk(process_kill_script, ["1"], {"BRIDGE_KILL_CMD": str(fake_kill)})
    assert result.returncode != 0


@pytest.mark.parametrize(
    "name", ["launchd", "kernel_task", "systemd", "init", "kernel", "kthreadd"]
)
def test_process_kill_refuses_protected_names(
    process_kill_script: Path, tmp_path: Path, name: str
) -> None:
    fake_pgrep = _fake_pgrep(tmp_path, [9999])
    fake_kill = _fake_kill(tmp_path, "success")
    result = _run_pk(
        process_kill_script, [name],
        {"BRIDGE_PGREP_CMD": str(fake_pgrep), "BRIDGE_KILL_CMD": str(fake_kill)},
    )
    assert result.returncode != 0
    assert "refusing" in result.stderr.lower() or "protected" in result.stderr.lower()


def test_process_kill_refuses_nonexistent_pid(process_kill_script: Path, tmp_path: Path) -> None:
    fake_kill = _fake_kill(tmp_path, "no_proc")
    result = _run_pk(process_kill_script, ["9999"], {"BRIDGE_KILL_CMD": str(fake_kill)})
    assert result.returncode != 0
    assert "no process" in result.stderr.lower()


# ── Name-path behaviour ───────────────────────────────────────────────────────

def test_process_kill_name_not_found(process_kill_script: Path, tmp_path: Path) -> None:
    fake_pgrep = _fake_pgrep(tmp_path, None)
    result = _run_pk(process_kill_script, ["myapp"], {"BRIDGE_PGREP_CMD": str(fake_pgrep)})
    assert result.returncode != 0
    assert "no process" in result.stderr.lower()


def test_process_kill_multiple_matches_no_all_flag(
    process_kill_script: Path, tmp_path: Path
) -> None:
    fake_pgrep = _fake_pgrep(tmp_path, [1234, 5678])
    fake_kill = _fake_kill(tmp_path, "success")
    result = _run_pk(
        process_kill_script, ["myapp"],
        {"BRIDGE_PGREP_CMD": str(fake_pgrep), "BRIDGE_KILL_CMD": str(fake_kill)},
    )
    assert result.returncode != 0
    assert "--all" in result.stderr


def test_process_kill_multiple_matches_with_all_flag(
    process_kill_script: Path, tmp_path: Path
) -> None:
    # First pgrep call returns 2 PIDs; second (post-kill check) returns empty.
    stateful_pgrep = tmp_path / "fake_pgrep_stateful"
    stateful_pgrep.write_text(
        '#!/usr/bin/env bash\n'
        'STATE="$(dirname "$0")/.called"\n'
        'if [[ ! -f "$STATE" ]]; then touch "$STATE"; printf "1234\\n5678\\n"; exit 0; fi\n'
        'exit 1\n'
    )
    stateful_pgrep.chmod(0o755)
    fake_kill = _fake_kill(tmp_path, "success")
    result = _run_pk(
        process_kill_script, ["myapp", "--all"],
        {"BRIDGE_PGREP_CMD": str(stateful_pgrep), "BRIDGE_KILL_CMD": str(fake_kill)},
    )
    assert result.returncode == 0
    assert "✓" in result.stdout or "terminated" in result.stdout.lower()


def test_process_kill_single_match_succeeds(
    process_kill_script: Path, tmp_path: Path
) -> None:
    stateful_pgrep = tmp_path / "fake_pgrep_single"
    stateful_pgrep.write_text(
        '#!/usr/bin/env bash\n'
        'STATE="$(dirname "$0")/.called"\n'
        'if [[ ! -f "$STATE" ]]; then touch "$STATE"; printf "9999\\n"; exit 0; fi\n'
        'exit 1\n'
    )
    stateful_pgrep.chmod(0o755)
    fake_kill = _fake_kill(tmp_path, "success")
    result = _run_pk(
        process_kill_script, ["myapp"],
        {"BRIDGE_PGREP_CMD": str(stateful_pgrep), "BRIDGE_KILL_CMD": str(fake_kill)},
    )
    assert result.returncode == 0
    assert "✓" in result.stdout or "terminated" in result.stdout.lower()


# ── Template sync ─────────────────────────────────────────────────────────────

def test_process_kill_example_matches_install_template() -> None:
    """examples/allowed_scripts/process_kill.sh must be identical to the install.sh heredoc."""
    example = REPO_ROOT / "examples" / "allowed_scripts" / "process_kill.sh"
    assert example.read_text() == _extract_script("process_kill.sh", "PK")


# ── run_claude.sh model-router wiring ─────────────────────────────────────────
# The installed run_claude.sh (the install.sh heredoc) is what runs on a real
# machine. Its header comments are deliberately condensed vs the canonical
# examples/ copy, so a byte-for-byte drift check would be too brittle. Instead
# guard the behaviour that actually matters: the model tier → --model routing
# must be present AND wired into the final exec. It silently regressed once
# (the model router shipped to examples/ + the daemon but never to install.sh,
# so --model was never passed on real installs).

def test_install_run_claude_has_model_router() -> None:
    body = _extract_script("run_claude.sh", "RUNCLAUDE")
    # tier map present, all four tiers mapped to concrete model IDs
    assert "tier_to_model_id()" in body
    assert "claude-haiku-4-5-20251001" in body
    assert "claude-sonnet-4-6" in body
    assert "claude-opus-4-8" in body
    assert "claude-fable-5" in body
    assert "CLAUDE_MODEL_TIER" in body
    # and actually passed to the CLI in the exec line
    exec_line = next(line for line in body.splitlines() if line.startswith("exec "))
    assert '"${MODEL_FLAGS[@]}"' in exec_line, (
        f"run_claude.sh exec must pass MODEL_FLAGS, got: {exec_line}"
    )


def test_install_run_claude_model_map_matches_router() -> None:
    """install.sh's tier→model map must agree with model_router.TIER_TO_MODEL_ID."""
    from cowork_to_code_bridge.model_router import TIER_TO_MODEL_ID

    body = _extract_script("run_claude.sh", "RUNCLAUDE")
    for tier, model_id in TIER_TO_MODEL_ID.items():
        assert model_id in body, f"{tier.value}→{model_id} missing from install.sh run_claude.sh"


# ── newer utility scripts (list_scripts, env_check, disk_hogs, open_browser) ──

NEW_SCRIPTS = [
    ("list_scripts.sh", "LS"),
    ("env_check.sh", "EC"),
    ("disk_hogs.sh", "DH"),
    ("open_browser.sh", "OB"),
]


@pytest.mark.parametrize(("script_name", "marker"), NEW_SCRIPTS)
def test_new_example_scripts_match_install_templates(script_name: str, marker: str) -> None:
    """The examples/ copy must be byte-identical to the install.sh heredoc."""
    example_path = REPO_ROOT / "examples" / "allowed_scripts" / script_name
    assert example_path.read_text() == _extract_script(script_name, marker)


@pytest.fixture()
def new_scripts(tmp_path: Path) -> Path:
    scripts_dir = tmp_path / "scripts"
    scripts_dir.mkdir()
    for script_name, marker in NEW_SCRIPTS:
        p = scripts_dir / script_name
        p.write_text(_extract_script(script_name, marker))
        p.chmod(0o755)
    # list_scripts.sh describes whatever is in its own dir, so drop a couple of
    # extra dummy scripts in to confirm it enumerates them.
    (scripts_dir / "ping.sh").write_text("#!/usr/bin/env bash\n# ping.sh — health check.\nexit 0\n")
    (scripts_dir / "ping.sh").chmod(0o755)
    return scripts_dir


def _run(path: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [str(path), *args],
        check=False,
        capture_output=True,
        text=True,
        env={**os.environ, "LC_ALL": "C"},
    )


def test_list_scripts_enumerates_dir(new_scripts: Path) -> None:
    result = _run(new_scripts / "list_scripts.sh")
    assert result.returncode == 0, result.stderr
    assert "AVAILABLE BRIDGE SCRIPTS" in result.stdout
    assert "ping.sh" in result.stdout
    assert "env_check.sh" in result.stdout
    # must not list itself
    assert "list_scripts.sh " not in result.stdout


def test_env_check_reports_without_leaking_token(new_scripts: Path) -> None:
    secret = "SUPERSECRETTOKENVALUE12345"
    env = {**os.environ, "LC_ALL": "C", "BRIDGE_TOKEN": secret}
    result = subprocess.run(
        [str(new_scripts / "env_check.sh")],
        check=False, capture_output=True, text=True, env=env,
    )
    assert result.returncode == 0, result.stderr
    assert "BRIDGE ENVIRONMENT" in result.stdout
    assert "BRIDGE_TOKEN" in result.stdout
    # the VALUE must never appear — only "set"
    assert secret not in result.stdout
    assert "set" in result.stdout


def test_disk_hogs_lists_and_validates(new_scripts: Path, tmp_path: Path) -> None:
    target = tmp_path / "data"
    target.mkdir()
    (target / "big.bin").write_bytes(b"x" * 200_000)
    ok = _run(new_scripts / "disk_hogs.sh", str(target), "5")
    assert ok.returncode == 0, ok.stderr
    assert "LARGEST ITEMS" in ok.stdout
    # bad count is rejected
    bad = _run(new_scripts / "disk_hogs.sh", str(target), "notanumber")
    assert bad.returncode != 0
    # missing dir is rejected
    missing = _run(new_scripts / "disk_hogs.sh", str(tmp_path / "nope"))
    assert missing.returncode != 0


def test_open_browser_rejects_unsafe_urls(new_scripts: Path) -> None:
    # no arg
    assert _run(new_scripts / "open_browser.sh").returncode != 0
    # file:// scheme
    assert _run(new_scripts / "open_browser.sh", "file:///etc/passwd").returncode != 0
    # bare path
    assert _run(new_scripts / "open_browser.sh", "/etc/passwd").returncode != 0
    # a non-http scheme
    assert _run(new_scripts / "open_browser.sh", "ftp://example.com").returncode != 0


# ── docker_logs.sh (#21) ─────────────────────────────────────────────────────

DOCKER_SCRIPTS = [
    ("docker_logs.sh", "DLG"),
]


@pytest.mark.parametrize(("script_name", "marker"), DOCKER_SCRIPTS)
def test_docker_logs_example_matches_install_template(script_name: str, marker: str) -> None:
    example_path = REPO_ROOT / "examples" / "allowed_scripts" / script_name
    assert example_path.read_text() == _extract_script(script_name, marker)


@pytest.fixture()
def docker_logs_script(tmp_path: Path) -> Path:
    scripts_dir = tmp_path / "scripts"
    scripts_dir.mkdir()
    script_path = scripts_dir / "docker_logs.sh"
    script_path.write_text(_extract_script("docker_logs.sh", "DLG"))
    script_path.chmod(0o755)
    return script_path


def test_docker_logs_requires_container(docker_logs_script: Path) -> None:
    result = _run(docker_logs_script)
    assert result.returncode != 0
    assert "Usage:" in result.stderr


def test_docker_logs_rejects_invalid_lines(docker_logs_script: Path) -> None:
    result = _run(docker_logs_script, "somecontainer", "notanumber")
    assert result.returncode != 0


def test_docker_logs_container_not_found(docker_logs_script: Path) -> None:
    if subprocess.run(["which", "docker"], capture_output=True).returncode != 0:
        pytest.skip("docker not available")
    result = _run(docker_logs_script, "definitely-not-a-bridge-container-xyz")
    assert result.returncode == 1
    assert "not found" in result.stderr.lower()


# ─────────────────────────────────────────────────────────────────────────────
# mac_ram.sh --json tests (issue #7 — JSON output mode)
# ─────────────────────────────────────────────────────────────────────────────

@pytest.fixture()
def mac_ram_script(tmp_path: Path) -> Path:
    script = tmp_path / "mac_ram.sh"
    script.write_text(_extract_script("mac_ram.sh", "MR"))
    script.chmod(0o755)
    return script


def test_mac_ram_default_text_output(mac_ram_script: Path) -> None:
    """Default (no flag) output is human-readable text, not JSON."""
    result = subprocess.run(
        [str(mac_ram_script)],
        capture_output=True, text=True, check=False,
        env={**os.environ, "LC_ALL": "C"},
    )
    assert result.returncode == 0, result.stderr
    assert RAM_FRAGMENT in result.stdout
    assert not result.stdout.lstrip().startswith("{"), "text mode must not emit JSON"


def test_mac_ram_json_flag_valid_json(mac_ram_script: Path) -> None:
    """--json flag produces valid, parseable JSON."""
    import json
    result = subprocess.run(
        [str(mac_ram_script), "--json"],
        capture_output=True, text=True, check=False,
        env={**os.environ, "LC_ALL": "C"},
    )
    assert result.returncode == 0, result.stderr
    data = json.loads(result.stdout)  # raises if invalid JSON
    assert isinstance(data, dict)


def test_mac_ram_json_has_required_keys(mac_ram_script: Path) -> None:
    """--json output contains all documented fields."""
    import json
    result = subprocess.run(
        [str(mac_ram_script), "--json"],
        capture_output=True, text=True, check=False,
        env={**os.environ, "LC_ALL": "C"},
    )
    assert result.returncode == 0, result.stderr
    data = json.loads(result.stdout)
    required = {"total_bytes", "free_bytes", "used_bytes", "used_pct"}
    missing = required - data.keys()
    assert not missing, f"missing keys in JSON output: {missing}"


def test_mac_ram_json_values_are_numeric(mac_ram_script: Path) -> None:
    """All RAM fields are numeric; total is positive on any real machine."""
    import json
    result = subprocess.run(
        [str(mac_ram_script), "--json"],
        capture_output=True, text=True, check=False,
        env={**os.environ, "LC_ALL": "C"},
    )
    assert result.returncode == 0, result.stderr
    data = json.loads(result.stdout)
    for key in ("total_bytes", "free_bytes", "used_bytes", "used_pct"):
        assert isinstance(data[key], int), f"{key} should be an int: {data[key]!r}"
    assert data["total_bytes"] > 0
    assert 0 <= data["used_pct"] <= 100


# ─────────────────────────────────────────────────────────────────────────────
# mac_disk.sh / mac_top.sh / mac_network.sh / disk_hogs.sh --json (issue #7)
# Each is extracted from install.sh so the byte-sync guard above already proves
# the example copy matches; these tests only exercise the new --json branch.
# ─────────────────────────────────────────────────────────────────────────────

import json  # noqa: E402


def _extract_to(tmp_path: Path, script_name: str, marker: str) -> Path:
    script = tmp_path / script_name
    script.write_text(_extract_script(script_name, marker))
    script.chmod(0o755)
    return script


def _run_json(script: Path, *args: str) -> dict:
    result = subprocess.run(
        [str(script), *args, "--json"],
        capture_output=True, text=True, check=False,
        env={**os.environ, "LC_ALL": "C"},
    )
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)  # raises if invalid JSON


# ── mac_disk.sh --json ────────────────────────────────────────────────────────

def test_mac_disk_json_valid_and_keys(tmp_path: Path) -> None:
    script = _extract_to(tmp_path, "mac_disk.sh", "MD")
    data = _run_json(script)
    required = {"path", "total_1k", "used_1k", "avail_1k", "used_pct"}
    assert not (required - data.keys()), f"missing: {required - data.keys()}"
    assert data["total_1k"] > 0
    assert 0 <= data["used_pct"] <= 100


def test_mac_disk_text_mode_unchanged(tmp_path: Path) -> None:
    script = _extract_to(tmp_path, "mac_disk.sh", "MD")
    result = subprocess.run(
        [str(script)], capture_output=True, text=True, check=False,
        env={**os.environ, "LC_ALL": "C"},
    )
    assert result.returncode == 0, result.stderr
    assert "=== DISK USAGE ===" in result.stdout
    assert not result.stdout.lstrip().startswith("{"), "text mode must not emit JSON"


# ── mac_top.sh --json ─────────────────────────────────────────────────────────

def test_mac_top_json_structure(tmp_path: Path) -> None:
    script = _extract_to(tmp_path, "mac_top.sh", "MT")
    data = _run_json(script, "5")
    assert data["count"] == 5
    for bucket in ("by_cpu", "by_mem"):
        assert isinstance(data[bucket], list), bucket
        assert len(data[bucket]) <= 5
        for proc in data[bucket]:
            for key in ("pid", "cpu_pct", "mem_pct", "name"):
                assert key in proc, f"{bucket} proc missing {key!r}: {proc}"
            assert isinstance(proc["pid"], int)


def test_mac_top_text_mode_unchanged(tmp_path: Path) -> None:
    script = _extract_to(tmp_path, "mac_top.sh", "MT")
    result = subprocess.run(
        [str(script), "5"], capture_output=True, text=True, check=False,
        env={**os.environ, "LC_ALL": "C"},
    )
    assert result.returncode == 0, result.stderr
    assert "=== by CPU ===" in result.stdout and "=== by MEM ===" in result.stdout


# ── mac_network.sh --json ─────────────────────────────────────────────────────

def test_mac_network_json_structure(tmp_path: Path) -> None:
    script = _extract_to(tmp_path, "mac_network.sh", "MN")
    data = _run_json(script)
    assert isinstance(data["interfaces"], list)
    for iface in data["interfaces"]:
        assert "name" in iface and "addr" in iface
    assert "default_route" in data
    assert isinstance(data["online"], bool)


def test_mac_network_text_mode_unchanged(tmp_path: Path) -> None:
    script = _extract_to(tmp_path, "mac_network.sh", "MN")
    result = subprocess.run(
        [str(script)], capture_output=True, text=True, check=False,
        env={**os.environ, "LC_ALL": "C"},
    )
    assert result.returncode == 0, result.stderr
    assert "=== interfaces (active) ===" in result.stdout


# ── disk_hogs.sh --json ───────────────────────────────────────────────────────

def test_disk_hogs_json_structure(tmp_path: Path) -> None:
    script = _extract_to(tmp_path, "disk_hogs.sh", "DH")
    target = tmp_path / "data"
    target.mkdir()
    (target / "big.bin").write_bytes(b"x" * 200_000)
    (target / "small.txt").write_text("hi")
    data = _run_json(script, str(target), "5")
    assert data["path"] == str(target)
    assert data["count"] == 5
    assert isinstance(data["items"], list)
    assert len(data["items"]) >= 1
    biggest = data["items"][0]
    for key in ("size_bytes", "size_human", "name"):
        assert key in biggest, f"item missing {key!r}: {biggest}"
    assert isinstance(biggest["size_bytes"], int)
    # items are sorted descending by size
    sizes = [it["size_bytes"] for it in data["items"]]
    assert sizes == sorted(sizes, reverse=True)


def test_disk_hogs_json_rejects_bad_args(tmp_path: Path) -> None:
    script = _extract_to(tmp_path, "disk_hogs.sh", "DH")
    # bad count still rejected even with --json
    bad = subprocess.run(
        [str(script), str(tmp_path), "notanumber", "--json"],
        capture_output=True, text=True, check=False,
    )
    assert bad.returncode != 0
    # missing dir still rejected
    missing = subprocess.run(
        [str(script), str(tmp_path / "nope"), "--json"],
        capture_output=True, text=True, check=False,
    )
    assert missing.returncode != 0


# ─────────────────────────────────────────────────────────────────────────────
# git_status.sh --json tests (issue #7)
#
# These extract the script from the install.sh template (via _extract_to) so the
# embedded copy — the one users actually get — is what gets exercised.
# ─────────────────────────────────────────────────────────────────────────────


def _git(repo: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True, text=True)


def _init_repo(repo: Path) -> None:
    repo.mkdir(parents=True, exist_ok=True)
    _git(repo, "init", "-q", "-b", "main")
    _git(repo, "config", "user.email", "t@t.co")
    _git(repo, "config", "user.name", "t")
    (repo / "a.txt").write_text("a\n")
    _git(repo, "add", "a.txt")
    _git(repo, "commit", "-qm", "init")


def _run_git_status(script: Path, repo: Path, json_flag: bool) -> subprocess.CompletedProcess[str]:
    args = [str(script), str(repo)]
    if json_flag:
        args.append("--json")
    return subprocess.run(args, capture_output=True, text=True, check=False)


def test_git_status_text_mode_unchanged(tmp_path: Path) -> None:
    """Default (no --json) is the familiar porcelain text — branch header present."""
    script = _extract_to(tmp_path, "git_status.sh", "GS")
    repo = tmp_path / "repo"
    _init_repo(repo)
    res = _run_git_status(script, repo, json_flag=False)
    assert res.returncode == 0, res.stderr
    assert res.stdout.startswith("## main")
    assert "{" not in res.stdout  # not JSON


def test_git_status_json_clean_repo(tmp_path: Path) -> None:
    """--json on a clean repo: valid JSON, clean=true, empty files, branch set."""
    import json

    script = _extract_to(tmp_path, "git_status.sh", "GS")
    repo = tmp_path / "repo"
    _init_repo(repo)
    res = _run_git_status(script, repo, json_flag=True)
    assert res.returncode == 0, res.stderr
    data = json.loads(res.stdout)
    assert data["branch"] == "main"
    assert data["clean"] is True
    assert data["files"] == []
    assert data["ahead"] == 0 and data["behind"] == 0
    assert data["repo"].endswith("repo")


def test_git_status_json_required_keys(tmp_path: Path) -> None:
    import json

    script = _extract_to(tmp_path, "git_status.sh", "GS")
    repo = tmp_path / "repo"
    _init_repo(repo)
    data = json.loads(_run_git_status(script, repo, json_flag=True).stdout)
    for key in ("repo", "branch", "upstream", "ahead", "behind", "clean", "files"):
        assert key in data, f"missing key: {key}"


def test_git_status_json_dirty_and_staged(tmp_path: Path) -> None:
    """Unstaged modify + staged add are both reported with porcelain XY codes."""
    import json

    script = _extract_to(tmp_path, "git_status.sh", "GS")
    repo = tmp_path / "repo"
    _init_repo(repo)
    (repo / "a.txt").write_text("a\nmodified\n")  # unstaged modify
    (repo / "b.txt").write_text("new\n")
    _git(repo, "add", "b.txt")  # staged add
    data = json.loads(_run_git_status(script, repo, json_flag=True).stdout)
    assert data["clean"] is False
    paths = {f["path"]: (f["x"], f["y"]) for f in data["files"]}
    assert "a.txt" in paths and paths["a.txt"] == (".", "M")  # unstaged modify
    assert "b.txt" in paths and paths["b.txt"] == ("A", ".")  # staged add


def test_git_status_json_rename_reports_new_path(tmp_path: Path) -> None:
    """A staged rename must report the new path, not 'R100 newpath'."""
    import json

    script = _extract_to(tmp_path, "git_status.sh", "GS")
    repo = tmp_path / "repo"
    _init_repo(repo)
    _git(repo, "mv", "a.txt", "renamed.txt")
    data = json.loads(_run_git_status(script, repo, json_flag=True).stdout)
    paths = {f["path"]: f["x"] for f in data["files"]}
    assert "renamed.txt" in paths
    assert paths["renamed.txt"] == "R"
    # the porcelain score token must not leak into the path
    assert not any(p.startswith("R100 ") for p in paths)


def test_git_status_json_untracked_quoted_path_unwrapped(tmp_path: Path) -> None:
    """Untracked path with special chars is C-quoted by git; we unwrap it."""
    import json

    script = _extract_to(tmp_path, "git_status.sh", "GS")
    repo = tmp_path / "repo"
    _init_repo(repo)
    (repo / 'weird "name".txt').write_text("z\n")
    data = json.loads(_run_git_status(script, repo, json_flag=True).stdout)
    paths = [f["path"] for f in data["files"] if f["x"] == "?"]
    assert 'weird "name".txt' in paths, paths


def test_git_status_json_ahead_behind(tmp_path: Path) -> None:
    """ahead/behind reflect divergence from an upstream."""
    import json

    script = _extract_to(tmp_path, "git_status.sh", "GS")
    upstream = tmp_path / "upstream"
    _init_repo(upstream)
    clone = tmp_path / "clone"
    _git(tmp_path, "clone", "-q", str(upstream), str(clone))
    _git(clone, "config", "user.email", "t@t.co")
    _git(clone, "config", "user.name", "t")
    # one local commit ahead of origin
    (clone / "c.txt").write_text("c\n")
    _git(clone, "add", "c.txt")
    _git(clone, "commit", "-qm", "ahead")
    data = json.loads(_run_git_status(script, clone, json_flag=True).stdout)
    assert data["ahead"] == 1
    assert data["behind"] == 0
    assert data["upstream"]  # non-empty (e.g. origin/main)


# ─────────────────────────────────────────────────────────────────────────────
# JSON output mode for utility scripts (issue #7):
# env_check.sh, port_check.sh, pkg_outdated.sh, docker_ps.sh
# These run the canonical examples/allowed_scripts/ copies directly.
# ─────────────────────────────────────────────────────────────────────────────

EXAMPLES = REPO_ROOT / "examples" / "allowed_scripts"


def _run_example(name: str, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["bash", str(EXAMPLES / name), *args],
        capture_output=True, text=True, check=False,
        env={**os.environ, "LC_ALL": "C"},
    )


# ── env_check.sh --json ──────────────────────────────────────────────────────

def test_env_check_default_is_text_not_json() -> None:
    result = _run_example("env_check.sh")
    assert result.returncode == 0, result.stderr
    assert "=== BRIDGE ENVIRONMENT ===" in result.stdout
    assert not result.stdout.lstrip().startswith("{")


def test_env_check_json_valid_and_has_keys() -> None:
    import json

    result = _run_example("env_check.sh", "--json")
    assert result.returncode == 0, result.stderr
    data = json.loads(result.stdout)  # raises if invalid JSON
    for key in (
        "bridge_root", "bridge_root_exists", "bridge_token_set",
        "claude_flags", "shell", "home", "os", "claude_cli",
    ):
        assert key in data, f"missing {key}: {data}"
    assert isinstance(data["bridge_root_exists"], bool)
    assert isinstance(data["bridge_token_set"], bool)


def test_env_check_json_never_leaks_token_value() -> None:
    import json

    secret = "super-secret-token-value-xyz"
    result = subprocess.run(
        ["bash", str(EXAMPLES / "env_check.sh"), "--json"],
        capture_output=True, text=True, check=False,
        env={**os.environ, "LC_ALL": "C", "BRIDGE_TOKEN": secret},
    )
    assert result.returncode == 0, result.stderr
    assert secret not in result.stdout
    data = json.loads(result.stdout)
    assert data["bridge_token_set"] is True


# ── port_check.sh --json ─────────────────────────────────────────────────────

def test_port_check_json_no_listener() -> None:
    import json

    # Port 65000 is almost certainly free in CI.
    result = _run_example("port_check.sh", "65000", "--json")
    assert result.returncode == 0, result.stderr
    data = json.loads(result.stdout)
    assert data["port"] == 65000
    assert data["listening"] is False
    assert data["tool"] is None
    assert data["raw"] == ""


def test_port_check_json_flag_order_independent() -> None:
    import json

    a = _run_example("port_check.sh", "--json", "65000")
    b = _run_example("port_check.sh", "65000", "--json")
    assert json.loads(a.stdout)["port"] == 65000
    assert json.loads(b.stdout)["port"] == 65000


def test_port_check_invalid_port_still_errors() -> None:
    result = _run_example("port_check.sh", "notanumber", "--json")
    assert result.returncode == 2


# ── pkg_outdated.sh --json ───────────────────────────────────────────────────

def test_pkg_outdated_json_valid_shape() -> None:
    import json

    result = _run_example("pkg_outdated.sh", "--json")
    assert result.returncode == 0, result.stderr
    data = json.loads(result.stdout)
    for key in ("manager", "count", "packages", "raw"):
        assert key in data, f"missing {key}: {data}"
    assert isinstance(data["packages"], list)
    assert isinstance(data["count"], int)
    assert data["count"] == len(data["packages"])


# ── docker_ps.sh --json ──────────────────────────────────────────────────────

def test_docker_ps_json_always_valid() -> None:
    """--json yields valid JSON whether or not docker/daemon is present."""
    import json

    result = _run_example("docker_ps.sh", "--json")
    # rc is 0 in JSON mode even when docker is missing (error encoded in JSON).
    assert result.returncode == 0, result.stderr
    data = json.loads(result.stdout)
    assert "ok" in data and "error" in data and "containers" in data
    assert isinstance(data["containers"], list)
    if data["ok"]:
        assert data["error"] is None
        for c in data["containers"]:
            assert {"name", "image", "status", "ports"} <= set(c)
    else:
        assert isinstance(data["error"], str) and data["error"]
        assert data["containers"] == []
