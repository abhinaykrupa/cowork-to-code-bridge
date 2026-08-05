"""Guard tests for the model-tier and effort routing tables.

The routing knowledge is duplicated across four surfaces, by necessity:

  * ``cowork_to_code_bridge/model_router.py`` — ``TIER_TO_MODEL_ID``, which
    every comment in the shell copies calls "the canonical source".
  * ``install.sh`` — the ``run_claude.sh`` heredoc, which is what a fresh
    ``curl | bash`` install actually writes to disk.
  * ``bridge/scripts/run_claude.sh`` — the working copy on this machine.
  * ``examples/allowed_scripts/run_claude.sh`` — the copy contributors read.

Nothing enforced that they agree. That is the same drift class that has bitten
this repo twice before: ``--json`` silently dropped out of the ``install.sh``
copy of a script, and the single-file client silently lost two documented
functions because its parity guard only checked one direction.

Drift here is worse than cosmetic. If Python routes a task to the ``opus`` tier
and the shell case statement has a stale model ID, ``run_claude.sh`` falls into
its ``*)`` branch, logs "unknown tier", and silently runs the task on the CLI's
default model — the caller is billed for and gets a different model than the
router promised, with no error anywhere.

So these tests assert equality in BOTH directions: every tier Python knows must
appear in each shell copy with the same model ID, AND every tier a shell copy
declares must exist in Python. A one-directional check would pass while a shell
copy quietly carried an extra or missing arm.

The same applies to the effort set, which is duplicated between
``daemon.py`` (which validates a caller's ``effort`` before injecting
``CLAUDE_EFFORT``) and the ``run_claude.sh`` case statement that consumes it.
If those disagree, one side accepts a value the other discards.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

from cowork_to_code_bridge.model_router import TIER_TO_MODEL_ID

REPO_ROOT = Path(__file__).resolve().parents[1]
INSTALL_SH = REPO_ROOT / "install.sh"
DAEMON_PY = REPO_ROOT / "cowork_to_code_bridge" / "daemon.py"

# The two checked-in copies of run_claude.sh. The third copy lives inside the
# install.sh heredoc and is extracted below rather than read from disk.
STANDALONE_COPIES = [
    REPO_ROOT / "bridge" / "scripts" / "run_claude.sh",
    REPO_ROOT / "examples" / "allowed_scripts" / "run_claude.sh",
]

# `haiku)  echo "claude-haiku-4-5-20251001" ;;`
_TIER_ARM = re.compile(r'^\s*([a-z0-9_]+)\)\s*echo\s+"([^"]*)"\s*;;', re.M)

# The `low|medium|high|xhigh|max)` arm of run_claude.sh's effort case statement.
_EFFORT_ARM = re.compile(r"^\s*((?:low|medium|high|xhigh|max)(?:\|[a-z]+)*)\)\s*$", re.M)

# daemon.py's validation set: `if effort_norm in {"low", "medium", ...}:`
_DAEMON_EFFORT_SET = re.compile(r'effort_norm\s+in\s+\{([^}]*)\}')


def _extract_run_claude_from_install_sh() -> str:
    """Return the run_claude.sh body embedded in install.sh's heredoc."""
    lines = INSTALL_SH.read_text().splitlines()
    prefix = 'cat > "$BRIDGE_ROOT/scripts/run_claude.sh" <<\'RUNCLAUDE\''

    try:
        start = lines.index(prefix) + 1
    except ValueError as exc:  # pragma: no cover - only on a malformed install.sh
        raise AssertionError(
            "Could not find the run_claude.sh heredoc in install.sh"
        ) from exc

    body: list[str] = []
    for line in lines[start:]:
        if line == "RUNCLAUDE":
            return "\n".join(body) + "\n"
        body.append(line)

    raise AssertionError("Unterminated run_claude.sh heredoc in install.sh")


def _tier_map_from_shell(source: str) -> dict[str, str]:
    """Parse the `tier_to_model_id()` case statement out of a shell source."""
    marker = "tier_to_model_id()"
    assert marker in source, "shell copy has no tier_to_model_id() function"

    body = source.split(marker, 1)[1]
    # Stop at the closing `}` of the function so we never pick up arms from an
    # unrelated case statement further down the script.
    end = body.find("\n}")
    assert end != -1, "tier_to_model_id() is not closed by a `}` on its own line"
    body = body[:end]

    return {
        tier: model_id
        for tier, model_id in _TIER_ARM.findall(body)
        if tier != "*"  # the fallback arm echoes an empty string
    }


def _shell_sources() -> list[tuple[str, str]]:
    sources = [("install.sh (heredoc)", _extract_run_claude_from_install_sh())]
    for path in STANDALONE_COPIES:
        assert path.exists(), f"missing run_claude.sh copy: {path}"
        sources.append((str(path.relative_to(REPO_ROOT)), path.read_text()))
    return sources


SHELL_SOURCES = _shell_sources()


@pytest.mark.parametrize("label,source", SHELL_SOURCES, ids=[s[0] for s in SHELL_SOURCES])
def test_shell_tier_map_matches_python_exactly(label: str, source: str) -> None:
    """Both directions: no missing tier, no extra tier, no stale model ID.

    A one-directional check (only "every Python tier is in the shell") would
    still pass if a shell copy carried an extra arm for a tier Python no longer
    routes to.
    """
    shell_map = _tier_map_from_shell(source)
    python_map = {tier.value: model_id for tier, model_id in TIER_TO_MODEL_ID.items()}

    assert shell_map == python_map, (
        f"{label} has drifted from model_router.TIER_TO_MODEL_ID.\n"
        f"  shell:  {shell_map}\n"
        f"  python: {python_map}"
    )


def test_every_shell_copy_agrees_with_every_other() -> None:
    """The three shell copies must be byte-identical in their tier tables."""
    maps = {label: _tier_map_from_shell(source) for label, source in SHELL_SOURCES}
    distinct = {tuple(sorted(m.items())) for m in maps.values()}
    assert len(distinct) == 1, f"run_claude.sh copies disagree on the tier map: {maps}"


def _daemon_effort_set() -> set[str]:
    match = _DAEMON_EFFORT_SET.search(DAEMON_PY.read_text())
    assert match, "could not find the effort validation set in daemon.py"
    return set(re.findall(r'"([a-z]+)"', match.group(1)))


def _shell_effort_set(source: str) -> set[str]:
    marker = "EFFORT_FLAGS=()"
    assert marker in source, "shell copy has no effort handling"
    body = source.split(marker, 1)[1]
    match = _EFFORT_ARM.search(body)
    assert match, "could not find the effort case arm in the shell copy"
    return set(match.group(1).split("|"))


@pytest.mark.parametrize("label,source", SHELL_SOURCES, ids=[s[0] for s in SHELL_SOURCES])
def test_shell_effort_set_matches_daemon(label: str, source: str) -> None:
    """The daemon validates the caller's effort; run_claude.sh consumes it.

    If the daemon accepts a value the shell then rejects, the task silently runs
    at the CLI's default effort instead of the one the caller asked for.
    """
    assert _shell_effort_set(source) == _daemon_effort_set(), (
        f"{label} effort set has drifted from daemon.py's validation set.\n"
        f"  shell:  {sorted(_shell_effort_set(source))}\n"
        f"  daemon: {sorted(_daemon_effort_set())}"
    )
