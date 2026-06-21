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
