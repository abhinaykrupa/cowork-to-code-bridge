from __future__ import annotations

import os
import shutil
import sys
from collections.abc import Mapping
from pathlib import Path


def detect_sandbox_backend(
    env: Mapping[str, str] | None = None,
    platform: str | None = None,
) -> str:
    """Detect the configured/supported sandboxing backend on Linux.

    Probes the BRIDGE_SANDBOX environment variable:
      - 'off': Sandboxing disabled (unconfined execution, default).
      - 'vetto': Run tasks supervised by Vetto (Landlock LSM, cgroups v2 process extinction).
      - 'bwrap': Run tasks supervised by Bubblewrap (mount namespaces, secret masking).
      - 'auto': On Linux, detect 'vetto' on PATH first; fall back to 'bwrap' if present;
                otherwise fall back gracefully to 'off'.

    On non-Linux platforms (e.g. macOS, Windows), returns 'off' since kernel
    isolation primitives (Landlock, mount/pid namespaces, cgroups v2) are Linux-only.

    Returns:
        One of 'off', 'vetto', 'bwrap'.
    """
    if env is None:
        env = os.environ
    if platform is None:
        platform = sys.platform

    raw = env.get("BRIDGE_SANDBOX", "off").strip().lower()

    if raw in ("", "off", "0", "false", "no", "none"):
        return "off"

    # Sandboxing backends require Linux kernel features (Landlock, namespaces, cgroups v2).
    # On macOS or Windows, gracefully fall back to "off".
    if not platform.startswith("linux"):
        return "off"

    if raw == "auto":
        if shutil.which("vetto"):
            return "vetto"
        if shutil.which("bwrap"):
            return "bwrap"
        return "off"

    if raw in ("vetto", "bwrap"):
        return raw

    # Unknown value; safe fallback
    return "off"


def wrap_argv(
    argv: list[str],
    script: str,
    cwd: str,
    bridge_root: Path | str,
    backend: str | None = None,
) -> list[str]:
    """Wrap command argv with the specified sandboxing backend.

    Arguments:
        argv: Original command argv vector (e.g. ['bash', '/path/script.sh', ...]).
        script: Relative or absolute script identifier (used to determine agent profile).
        cwd: Target working directory for task execution.
        bridge_root: Root path of the bridge (~/.cowork-to-code-bridge).
        backend: Sandbox backend ('off', 'auto', 'vetto', 'bwrap'). If None,
                 auto-detected via detect_sandbox_backend().

    Returns:
        New argv vector wrapped with sandbox supervisor, or original argv if 'off'.
    """
    if backend is None or backend == "auto":
        backend = detect_sandbox_backend()

    if backend == "off":
        return list(argv)

    if backend == "vetto":
        # For Claude Code scripts (run_claude.sh or escalate_to_claude.sh),
        # use Vetto's 'claude' profile which preserves ANTHROPIC_API_KEY and CLAUDE_*
        # environment variables and allows access to Claude configs and Anthropic API.
        # Other scripts run under the 'default' profile.
        script_name = Path(script).name
        profile = (
            "claude"
            if script_name in ("run_claude.sh", "escalate_to_claude.sh")
            else "default"
        )
        return ["vetto", "--profile", profile, "run", "--", *argv]

    if backend == "bwrap":
        cwd_path = Path(cwd).resolve()
        bridge_path = Path(bridge_root).resolve()
        home = Path.home()

        wrapped = [
            "bwrap",
            "--ro-bind", "/", "/",
            "--dev", "/dev",
            "--proc", "/proc",
            "--tmpfs", "/tmp",
            "--bind", str(cwd_path), str(cwd_path),
        ]

        if bridge_path != cwd_path:
            wrapped.extend(["--bind", str(bridge_path), str(bridge_path)])

        # Isolate ~/.ssh with empty tmpfs
        ssh_path = home / ".ssh"
        if ssh_path.exists():
            wrapped.extend(["--tmpfs", str(ssh_path)])
        else:
            try:
                ssh_path.mkdir(mode=0o700, parents=True, exist_ok=True)
                wrapped.extend(["--tmpfs", str(ssh_path)])
            except OSError:
                wrapped.extend(["--tmpfs", str(ssh_path)])

        # Mask .env in cwd (read-only empty /dev/null mount point)
        cwd_env = cwd_path / ".env"
        wrapped.extend(["--ro-bind-try", "/dev/null", str(cwd_env)])

        # Mask ~/.env if present
        home_env = home / ".env"
        if home_env.exists() and home_env != cwd_env:
            wrapped.extend(["--ro-bind-try", "/dev/null", str(home_env)])

        # Isolate ~/.aws if present
        aws_path = home / ".aws"
        if aws_path.exists():
            wrapped.extend(["--tmpfs", str(aws_path)])

        wrapped.extend(["--die-with-parent", "--", *argv])
        return wrapped

    # Unknown backend: return unchanged
    return list(argv)
