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
