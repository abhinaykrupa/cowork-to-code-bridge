"""
uninstall.py — one-command teardown for cowork-to-code-bridge.

Exposed as the `cowork-to-code-bridge-uninstall` console script after pip install.
Reverts everything install.sh did:
  1. Unloads + removes the launchd plist
  2. Removes ~/.cowork-to-code-bridge/ (with prompt, --yes to skip)
  3. pip uninstalls the cowork-to-code-bridge package itself

Usage:
    cowork-to-code-bridge-uninstall          # prompts before each destructive step
    cowork-to-code-bridge-uninstall --yes    # no prompts (CI / scripted use)
    cowork-to-code-bridge-uninstall --keep-data    # leave ~/.cowork-to-code-bridge/
    cowork-to-code-bridge-uninstall --keep-package # leave the pip package
"""
from __future__ import annotations

import argparse
import os
import platform
import shutil
import subprocess
import sys
from pathlib import Path

PLIST_LABEL = "dev.cowork-to-code-bridge.daemon"
PLIST_PATH = Path.home() / "Library" / "LaunchAgents" / f"{PLIST_LABEL}.plist"
DEFAULT_BRIDGE_ROOT = Path.home() / ".cowork-to-code-bridge"
SKILL_DIR = Path.home() / ".claude" / "skills" / "cowork-to-code-bridge"
PACKAGE_NAME = "cowork-to-code-bridge"


def _color(s: str, code: str) -> str:
    if not sys.stdout.isatty():
        return s
    return f"\033[{code}m{s}\033[0m"


def green(s: str) -> str:
    return _color(s, "0;32")


def yellow(s: str) -> str:
    return _color(s, "0;33")


def red(s: str) -> str:
    return _color(s, "0;31")


def cyan(s: str) -> str:
    return _color(s, "1;36")


def step(msg: str) -> None:
    print(f"\n{cyan('==>')} {msg}")


def confirm(prompt: str, assume_yes: bool) -> bool:
    if assume_yes:
        return True
    try:
        resp = input(f"  {prompt} [y/N] ").strip().lower()
    except EOFError:
        return False
    return resp in ("y", "yes")


def unload_launchd() -> bool:
    """Returns True if a daemon was loaded and got unloaded, False if nothing to do."""
    try:
        listing = subprocess.run(
            ["launchctl", "list"], capture_output=True, text=True, check=False,
        )
        if PLIST_LABEL not in listing.stdout:
            return False
    except FileNotFoundError:
        print(yellow("  ! launchctl not found — skipping (are you on macOS?)"))
        return False

    if not PLIST_PATH.exists():
        # Loaded but plist gone — bootout by label instead
        print(yellow(f"  ! daemon loaded but {PLIST_PATH.name} missing; attempting bootout"))
        subprocess.run(
            ["launchctl", "bootout", f"gui/{os.getuid()}/{PLIST_LABEL}"],
            capture_output=True, check=False,
        )
        return True

    result = subprocess.run(
        ["launchctl", "unload", str(PLIST_PATH)],
        capture_output=True, text=True, check=False,
    )
    if result.returncode != 0:
        print(yellow(f"  ! unload returned {result.returncode}: {result.stderr.strip()}"))
    return True


def remove_plist() -> bool:
    if PLIST_PATH.exists():
        PLIST_PATH.unlink()
        return True
    return False


SYSTEMD_UNIT = Path.home() / ".config" / "systemd" / "user" / "cowork-to-code-bridge.service"


def stop_systemd() -> bool:
    """Linux: stop + disable + remove the systemd --user unit. True if anything done."""
    import shutil as _sh
    if not _sh.which("systemctl"):
        return False
    did = False
    subprocess.run(
        ["systemctl", "--user", "disable", "--now", "cowork-to-code-bridge.service"],
        capture_output=True, check=False,
    )
    if SYSTEMD_UNIT.exists():
        SYSTEMD_UNIT.unlink()
        subprocess.run(["systemctl", "--user", "daemon-reload"], capture_output=True, check=False)
        did = True
    return did


def remove_bridge_root(bridge_root: Path, assume_yes: bool) -> bool:
    if not bridge_root.exists():
        return False
    if not confirm(
        f"Delete {bridge_root}? (contains your token, logs, and processed-command history)",
        assume_yes,
    ):
        print(f"  kept {bridge_root}")
        return False
    shutil.rmtree(bridge_root)
    return True


def remove_skill() -> bool:
    """Remove the global Cowork skill so it stops auto-loading into sessions."""
    if SKILL_DIR.exists():
        shutil.rmtree(SKILL_DIR)
        return True
    return False


def _is_installed() -> bool:
    """True if the package is importable under this interpreter."""
    r = subprocess.run(
        [sys.executable, "-c", "import cowork_to_code_bridge"],
        capture_output=True, check=False,
    )
    return r.returncode == 0


def pip_uninstall(assume_yes: bool) -> bool:
    """Uninstall the package, handling --user / PEP 668 (externally-managed).

    Tries a plain `pip uninstall`; if pip refuses because the environment is
    externally managed (Homebrew/system Python), retries with
    --break-system-packages. Verifies the package is actually gone afterward and
    reports honestly. Uses the SAME interpreter this script runs under.
    """
    if not confirm(f"Uninstall the {PACKAGE_NAME} Python package?", assume_yes):
        print(f"  kept {PACKAGE_NAME} package")
        return False

    if not _is_installed():
        print(f"  ({PACKAGE_NAME} not importable here — nothing to uninstall under this Python)")
        return True

    base = [sys.executable, "-m", "pip", "uninstall", "-y", PACKAGE_NAME]
    print(f"  running: {' '.join(base)}")
    result = subprocess.run(base, capture_output=True, text=True, check=False)
    out = (result.stdout or "") + (result.stderr or "")

    # PEP 668: externally-managed environment refuses the uninstall.
    if result.returncode != 0 and "externally-managed-environment" in out:
        retry = [*base, "--break-system-packages"]
        print("  ! externally-managed Python — retrying with --break-system-packages")
        result = subprocess.run(retry, capture_output=True, text=True, check=False)
        out = (result.stdout or "") + (result.stderr or "")

    if not _is_installed():
        return True  # gone — success regardless of pip's exit nuance

    # Still importable: surface why so the user can finish manually.
    print(yellow("  ! could not fully remove the package automatically."))
    tail = out.strip().splitlines()[-3:] if out.strip() else []
    for line in tail:
        print(f"    {line}")
    print(f"    Finish manually with: {sys.executable} -m pip uninstall -y {PACKAGE_NAME}")
    return False


def main() -> int:
    parser = argparse.ArgumentParser(
        prog="cowork-to-code-bridge-uninstall",
        description="Remove cowork-to-code-bridge daemon, data, and Python package.",
    )
    parser.add_argument(
        "--yes", "-y", action="store_true",
        help="Don't prompt — assume yes to every destructive step.",
    )
    parser.add_argument(
        "--keep-data", action="store_true",
        help="Leave ~/.cowork-to-code-bridge/ in place (preserves your token + script whitelist).",
    )
    parser.add_argument(
        "--keep-package", action="store_true",
        help="Leave the Python package installed.",
    )
    parser.add_argument(
        "--bridge-root", default=None,
        help="Override the bridge root dir (default: ~/.cowork-to-code-bridge or $BRIDGE_ROOT).",
    )
    args = parser.parse_args()

    bridge_root = Path(
        args.bridge_root or os.environ.get("BRIDGE_ROOT") or DEFAULT_BRIDGE_ROOT
    ).expanduser()

    print(cyan("cowork-to-code-bridge uninstaller"))
    print(f"  bridge root : {bridge_root}")
    print(f"  plist       : {PLIST_PATH}")
    print(f"  package     : {PACKAGE_NAME}")
    print(f"  interpreter : {sys.executable}")

    # ─── 1. Stop + remove the background service (launchd or systemd) ──────────
    if platform.system() == "Linux":
        step("Stopping systemd --user service")
        if stop_systemd():
            print(green("  ✓ systemd service stopped + unit removed"))
        else:
            print("  (no systemd service found)")
    else:
        step("Stopping launchd agent")
        if unload_launchd():
            print(green("  ✓ daemon unloaded"))
        else:
            print(f"  (no loaded daemon labelled {PLIST_LABEL})")
        if remove_plist():
            print(green(f"  ✓ removed {PLIST_PATH}"))
        else:
            print(f"  (no plist at {PLIST_PATH})")

    # ─── 2. Remove bridge data ────────────────────────────────────────────────
    if args.keep_data:
        step("Skipping bridge data removal (--keep-data)")
    else:
        step(f"Removing bridge data at {bridge_root}")
        if remove_bridge_root(bridge_root, args.yes):
            print(green(f"  ✓ removed {bridge_root}"))
        else:
            print(f"  ({bridge_root} not removed)")

    # ─── 2.5 Remove the global Cowork skill ───────────────────────────────────
    step(f"Removing global Cowork skill at {SKILL_DIR}")
    if remove_skill():
        print(green(f"  ✓ removed {SKILL_DIR} (it will stop loading in Cowork sessions)"))
    else:
        print(f"  (no skill at {SKILL_DIR})")

    # ─── 3. Uninstall Python package ──────────────────────────────────────────
    if args.keep_package:
        step("Skipping Python package uninstall (--keep-package)")
        print(yellow(
            "  ! Note: leaving the package keeps this uninstaller available "
            "but no daemon will be running."
        ))
    else:
        step(f"Uninstalling Python package {PACKAGE_NAME}")
        if pip_uninstall(args.yes):
            print(green(f"  ✓ {PACKAGE_NAME} uninstalled"))
        else:
            print(yellow("  ! pip uninstall did not complete cleanly"))

    print(green("\nDone."))
    print(
        "To verify: `launchctl list | grep cowork-to-code-bridge` (empty), "
        "`ls ~/.cowork-to-code-bridge` (gone if data removed), and "
        "`ls ~/.claude/skills/cowork-to-code-bridge` (gone — no longer loads in Cowork)."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
