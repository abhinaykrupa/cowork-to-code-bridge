"""Keep docs/WITHOUT_CLAUDE.md honest and reachable.

Written after a curator closed a submission with: "its principal workflow
delegates execution to the proprietary Claude Code runtime … does not provide
sufficient standalone OSS value." The mechanism is provider-neutral — the daemon
runs any allowlisted script — but nothing in the docs demonstrated that, so the
critique was accurate about the *presentation*.

The doc states a specific ratio of neutral to Claude-coupled bundled scripts.
That number drifts the moment someone adds a script, and a wrong count in the
answer to a credibility objection is worse than no answer.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
DOC = REPO / "docs" / "WITHOUT_CLAUDE.md"
README = REPO / "README.md"
SCRIPTS = REPO / "examples" / "allowed_scripts"


def _counts() -> tuple[int, int]:
    """(total bundled scripts, count that are Claude-coupled)."""
    scripts = sorted(SCRIPTS.glob("*.sh"))
    claude = [s for s in scripts if "claude" in s.name.lower()]
    return len(scripts), len(claude)


def test_doc_exists_and_is_linked_from_readme():
    """An unlinked doc is an orphan — the objection it answers stays unanswered."""
    assert DOC.is_file(), "docs/WITHOUT_CLAUDE.md is missing"
    assert "WITHOUT_CLAUDE.md" in README.read_text(), \
        "docs/WITHOUT_CLAUDE.md exists but nothing in the README links to it"


def test_script_ratio_claims_match_reality():
    """Every 'N of the M scripts' claim must match what actually ships."""
    total, claude = _counts()
    neutral = total - claude
    for text, where in ((DOC.read_text(), "WITHOUT_CLAUDE.md"), (README.read_text(), "README.md")):
        for n, m in re.findall(r"(\d+)\s+of the\s+(\d+)\s+bundled", text):
            assert (int(n), int(m)) == (neutral, total), (
                f"{where} claims {n} of {m} bundled scripts are neutral, "
                f"but the tree has {neutral} of {total}"
            )


def test_doc_names_only_scripts_that_exist():
    """Examples must reference real bundled scripts, not aspirational ones."""
    referenced = set(re.findall(r"scripts/([a-z0-9_]+\.sh)", DOC.read_text()))
    # deploy_staging.sh is the worked example of adding your own — not bundled.
    referenced.discard("deploy_staging.sh")
    missing = sorted(r for r in referenced if not (SCRIPTS / r).is_file())
    assert not missing, f"WITHOUT_CLAUDE.md references non-existent scripts: {missing}"


def test_doc_links_resolve_to_real_files():
    """Relative links in the See-also section must point at files that exist."""
    for target in re.findall(r"\]\((?!https?:)([^)#]+)\)", DOC.read_text()):
        resolved = (DOC.parent / target).resolve()
        assert resolved.exists(), f"WITHOUT_CLAUDE.md links to missing file: {target}"


@pytest.mark.parametrize("claim", ["run_claude.sh"])
def test_claude_script_actually_exists(claim):
    """Negative control: the doc's framing depends on run_claude.sh being one script."""
    assert (SCRIPTS / claim).is_file()
