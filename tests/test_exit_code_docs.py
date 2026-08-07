"""Guard test: every negative exit code the daemon can emit must be documented.

The daemon signals "your task did not run, or did not finish normally" with
negative ``exit_code`` values, because a real process exit is always >= 0. Those
codes are the *entire* machine-readable failure vocabulary a caller gets — the
accompanying ``error`` string is prose meant for humans, and matching on it is
exactly the brittle thing the codes exist to avoid.

So an undocumented code is a real defect, not a cosmetic one: a caller writing
``if res["exit_code"] == -6: retry_later()`` has no way to learn that ``-1``
means "rejected before dispatch, retrying is pointless" unless something tells
them. This bit the repo before — ``-1`` was the daemon's most-used failure code
(nine distinct rejection paths) while CLAUDE.md's exit-code table listed only
``-2`` through ``-6``, and ``get_bridge_context()`` mentioned ``-1`` exactly once
in passing, inside an unrelated paragraph about plan hooks.

This test derives the truth from ``daemon.py`` rather than from a hand-kept list,
which is the same approach that guards the routing tables (see
``test_routing_parity.py``) and the install.sh heredocs. A new failure path with
a new code fails this test until it is documented on every surface a caller
actually reads:

  * ``CLAUDE.md`` — what an agent working in this repo loads.
  * ``get_bridge_context()`` — what a *caller* loads over the bridge, where
    ``docs/`` may not even be mounted. This is the one that matters most for
    someone consuming the bridge from a sandbox.

The check runs in both directions. Every code the daemon emits must be
documented, AND every code the docs claim must actually exist in the daemon —
a one-directional check would happily pass while the docs described a ``-7``
that was removed two refactors ago.
"""
from __future__ import annotations

import re
from pathlib import Path

from cowork_to_code_bridge.bridge_init import get_bridge_context

REPO_ROOT = Path(__file__).resolve().parents[1]
DAEMON_PY = REPO_ROOT / "cowork_to_code_bridge" / "daemon.py"
CLAUDE_MD = REPO_ROOT / "CLAUDE.md"

# Matches the daemon's own result-writing idiom, e.g.  "exit_code": -4
# Only literal negative values are collected; ``proc.returncode`` is the real
# process exit and is never a bridge-assigned sentinel.
_EMITTED = re.compile(r'"exit_code":\s*(-\d+)')

# How a code is documented: `-4` in backticks (CLAUDE.md / markdown tables) or
# exit_code=-4 (the prose form used in get_bridge_context()).
def _documented_codes(text: str) -> set[int]:
    codes = {int(m) for m in re.findall(r"`(-\d+)`", text)}
    codes |= {int(m) for m in re.findall(r"exit_code=(-\d+)", text)}
    return codes


def _emitted_codes() -> set[int]:
    return {int(m) for m in _EMITTED.findall(DAEMON_PY.read_text())}


def test_daemon_emits_the_codes_we_think_it_does() -> None:
    """Pin the known set, so a NEW failure path is a visible, deliberate change.

    Without this, adding a code and documenting it everywhere would pass
    silently — fine — but so would adding one and documenting it in a single
    place. This is the tripwire that forces the author to look at the list.
    """
    assert _emitted_codes() == {-1, -2, -3, -4, -5, -6}


def test_every_emitted_code_is_documented_in_claude_md() -> None:
    documented = _documented_codes(CLAUDE_MD.read_text())
    missing = _emitted_codes() - documented
    assert not missing, (
        f"daemon.py emits {sorted(missing)} but CLAUDE.md's exit-code table "
        f"does not document it. A caller cannot branch on a code it has never "
        f"been told about."
    )


def test_every_emitted_code_is_documented_in_bridge_context() -> None:
    """get_bridge_context() is the copy a sandboxed caller actually receives.

    docs/ is frequently not mounted into the sandbox, so this string is the only
    reference some callers will ever see. It drifting is worse than CLAUDE.md
    drifting.
    """
    documented = _documented_codes(get_bridge_context())
    missing = _emitted_codes() - documented
    assert not missing, (
        f"daemon.py emits {sorted(missing)} but get_bridge_context() does not "
        f"document it — a caller reading only the bridge context cannot know "
        f"what the code means."
    )


def test_docs_do_not_describe_codes_the_daemon_cannot_emit() -> None:
    """The reverse direction: no phantom codes left behind by a refactor."""
    emitted = _emitted_codes()
    for name, text in (
        ("CLAUDE.md", CLAUDE_MD.read_text()),
        ("get_bridge_context()", get_bridge_context()),
    ):
        # Restrict to the sentinel range the daemon actually uses. Unrelated
        # negative numbers in prose (a -1 index, a CLI flag) are not claims
        # about exit codes; only codes inside the known band are checked.
        claimed = {c for c in _documented_codes(text) if -9 <= c <= -1}
        phantom = claimed - emitted
        assert not phantom, (
            f"{name} documents exit code(s) {sorted(phantom)} that daemon.py "
            f"never emits — stale documentation from a removed failure path."
        )
