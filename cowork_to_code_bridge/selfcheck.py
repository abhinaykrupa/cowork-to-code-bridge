"""
selfcheck.py — verify a cowork-to-code-bridge install end-to-end.

Exposed as the `cowork-to-code-bridge-selfcheck` console script after pip install.
Run this on your machine any time to confirm the bridge is healthy:

    cowork-to-code-bridge-selfcheck

Checks performed:
  1. BRIDGE_ROOT directory exists
  2. BRIDGE_TOKEN present and non-empty in .env
  3. Daemon registered with the OS service manager (launchd / systemd --user)
  4. Skill installed at ~/.claude/skills/cowork-to-code-bridge/
  5. Ping round-trip (write to queue/, daemon picks it up, result comes back)
  6. claude CLI resolves on PATH or common install locations

Exits 0 if all checks pass, 1 if any check fails.
"""
from __future__ import annotations

import os
import platform
import shutil
import subprocess
import sys
from pathlib import Path

BRIDGE_ROOT = Path(os.environ.get("BRIDGE_ROOT", Path.home() / ".cowork-to-code-bridge"))
SKILL_DIR = Path.home() / ".claude" / "skills" / "cowork-to-code-bridge"
PLIST_LABEL = "dev.cowork-to-code-bridge.daemon"
SYSTEMD_UNIT = "cowork-to-code-bridge.service"

# ANSI colours (suppressed when not a TTY)
_TTY = sys.stdout.isatty()


def _green(s: str) -> str:
    return f"\033[0;32m{s}\033[0m" if _TTY else s


def _red(s: str) -> str:
    return f"\033[0;31m{s}\033[0m" if _TTY else s


def _yellow(s: str) -> str:
    return f"\033[0;33m{s}\033[0m" if _TTY else s


def _bold(s: str) -> str:
    return f"\033[1m{s}\033[0m" if _TTY else s


# ── individual checks ────────────────────────────────────────────────────────

def check_bridge_root() -> tuple[bool, str]:
    """1. BRIDGE_ROOT directory exists."""
    if BRIDGE_ROOT.is_dir():
        return True, str(BRIDGE_ROOT)
    return False, f"{BRIDGE_ROOT} not found — run the installer first"


def check_token() -> tuple[bool, str]:
    """2. BRIDGE_TOKEN present and non-empty."""
    # Prefer env var
    tok = os.environ.get("BRIDGE_TOKEN", "").strip()
    if tok:
        return True, "set via BRIDGE_TOKEN env var"

    env_file = BRIDGE_ROOT / ".env"
    if not env_file.exists():
        return False, f"{env_file} not found"

    for line in env_file.read_text().splitlines():
        if line.strip().startswith("BRIDGE_TOKEN"):
            _, _, v = line.partition("=")
            v = v.strip().strip('"').strip("'")
            if v:
                return True, f"set in {env_file}"
            return False, "BRIDGE_TOKEN line present but empty — re-run installer"

    return False, f"BRIDGE_TOKEN not found in {env_file}"


def check_daemon_registered() -> tuple[bool, str]:
    """3. Daemon registered with launchd (macOS) or systemd --user (Linux)."""
    system = platform.system()

    if system == "Darwin":
        try:
            # `launchctl list` (no label) gives columnar PID / Status / Label output.
            # `launchctl list <label>` gives a plist dict — use the former for PID.
            result = subprocess.run(
                ["launchctl", "list"],
                capture_output=True,
                text=True,
            )
            for line in result.stdout.splitlines():
                if PLIST_LABEL in line:
                    cols = line.split()
                    pid = cols[0] if cols else "-"
                    if pid != "-":
                        return True, f"launchd: running (pid {pid})"
                    return False, (
                        f"launchd: registered but not running — "
                        f"try: launchctl start {PLIST_LABEL}"
                    )
            return False, f"launchd: not registered ({PLIST_LABEL}) — re-run installer"
        except FileNotFoundError:
            return False, "launchctl not found"

    if system == "Linux":
        try:
            result = subprocess.run(
                ["systemctl", "--user", "is-active", SYSTEMD_UNIT],
                capture_output=True,
                text=True,
            )
            status = result.stdout.strip()
            if status == "active":
                return True, "systemd --user: active"
            hint = f"try: systemctl --user start {SYSTEMD_UNIT}"
            return False, f"systemd --user: {status or 'unknown'} — {hint}"
        except FileNotFoundError:
            return False, "systemctl not found"

    return False, f"unsupported OS: {system}"


def check_skill() -> tuple[bool, str]:
    """4. Skill installed at ~/.claude/skills/cowork-to-code-bridge/."""
    skill_md = SKILL_DIR / "SKILL.md"
    client_py = SKILL_DIR / "bridge_client.py"

    missing = [f for f in (skill_md, client_py) if not f.exists()]
    if not missing:
        return True, str(SKILL_DIR)
    return False, f"missing: {', '.join(str(m) for m in missing)} — re-run installer"


def check_ping() -> tuple[bool, str]:
    """5. Ping round-trip through the queue/results cycle."""
    # Import here so the check still reports a clear error if the package
    # is partially installed rather than crashing at module level.
    try:
        from cowork_to_code_bridge.client import daemon_alive as _daemon_alive
    except ImportError as exc:
        return False, f"could not import bridge client: {exc}"

    try:
        alive = _daemon_alive(bridge_root=BRIDGE_ROOT, ping_timeout=10)
    except Exception as exc:  # noqa: BLE001
        return False, f"ping raised an error: {exc}"

    if alive:
        return True, "ping round-trip OK"
    return False, (
        "no response within 10 s — daemon may not be running. "
        "Check with: cowork-to-code-bridge-selfcheck (after starting the daemon)"
    )


def check_claude_cli() -> tuple[bool, str]:
    """6. claude CLI resolves on PATH or known install locations."""
    # Check PATH first
    found = shutil.which("claude")
    if found:
        return True, found

    # Common install locations
    candidates = [
        Path.home() / ".local" / "bin" / "claude",
        Path.home() / ".claude" / "bin" / "claude",
        Path("/opt/homebrew/bin/claude"),
        Path("/usr/local/bin/claude"),
    ]
    # Desktop app bundle (macOS)
    app_support = Path.home() / "Library" / "Application Support" / "Claude" / "claude-code"
    if app_support.is_dir():
        for p in sorted(app_support.rglob("claude")):
            if p.is_file() and os.access(p, os.X_OK):
                candidates.append(p)
                break

    for p in candidates:
        if p.exists() and os.access(p, os.X_OK):
            return True, f"{p} (not on PATH — add it to ~/.zshrc or ~/.bashrc)"

    return False, (
        "claude CLI not found. Install it: curl -fsSL https://claude.ai/install.sh | bash"
        "\n         (The Claude Desktop app alone is not enough — the CLI is separate.)"
    )


# ── runner ───────────────────────────────────────────────────────────────────

CHECKS = [
    ("Bridge root",       check_bridge_root),
    ("Bridge token",      check_token),
    ("Daemon registered", check_daemon_registered),
    ("Skill installed",   check_skill),
    ("Ping round-trip",   check_ping),
    ("claude CLI",        check_claude_cli),
]


def main() -> None:
    print(_bold("\ncowork-to-code-bridge selfcheck"))
    print(f"  bridge root : {BRIDGE_ROOT}")
    print(f"  platform    : {platform.system()} {platform.machine()}\n")

    width = max(len(label) for label, _ in CHECKS)
    failures = 0

    for label, fn in CHECKS:
        try:
            ok, detail = fn()
        except Exception as exc:  # noqa: BLE001
            ok, detail = False, f"unexpected error: {exc}"

        status = _green("PASS") if ok else _red("FAIL")
        print(f"  {label:<{width}}  [{status}]  {detail}")
        if not ok:
            failures += 1

    print()
    if failures == 0:
        print(_green("  All checks passed. Bridge is healthy."))
    else:
        print(_red(f"  {failures} check(s) failed."))
        print(_yellow("  Re-run the installer to fix most issues:"))
        print("    curl -fsSL https://raw.githubusercontent.com/abhinaykrupa/"
              "cowork-to-code-bridge/main/install.sh | bash")
    print()

    sys.exit(0 if failures == 0 else 1)


if __name__ == "__main__":
    main()
