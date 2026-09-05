"""The 'Featured in' section must only claim wins that actually exist.

Self-submitted list PRs sitting open in someone's review queue are not coverage.
This section is the project's social proof, so every row has to be a merged,
live, third-party listing — anything weaker belongs in a PR description, not the
README.

These tests are offline: they pin the claims to specific URLs and assert the
section does not drift into listing pending submissions. Link liveness is
checked separately by the repo-wide link guard.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

README = Path(__file__).resolve().parent.parent / "README.md"


@pytest.fixture(scope="module")
def featured() -> str:
    t = README.read_text()
    assert "## Featured in" in t, "README lost its 'Featured in' section"
    start = t.index("## Featured in")
    end = t.index("## Community", start)
    return t[start:end]


def test_lists_the_merged_pattern_page(featured: str):
    """The agentic-patterns entry is a merged pattern page, verified live."""
    assert "agentic-patterns.com/patterns/filesystem-mediated-host-delegation" in featured


def test_lists_the_merged_skill_listing(featured: str):
    assert "sickn33/agentic-awesome-skills" in featured


def test_no_pending_submissions_presented_as_coverage(featured: str):
    """Negative control: open PRs must never be listed as if they landed.

    These are the repos with self-submitted PRs still awaiting review. Listing
    any of them here would misrepresent a pending submission as a feature.
    """
    pending = [
        "500-AI-Agents-Projects", "e2b-dev/awesome-ai-agents",
        "awesome-claude-skills", "awesome-mcp-clients",
        "awesome-ai-agents-2026", "awesome-ai-devtools",
        "awesome-ralph", "awesome-opencode", "awesome-harness-engineering",
    ]
    found = [r for r in pending if r in featured]
    assert not found, f"'Featured in' lists un-merged submissions: {found}"


def test_star_counts_are_plausible(featured: str):
    """Star claims should be round approximations, not invented precision."""
    for count in re.findall(r"\((\d+(?:\.\d+)?)k★\)", featured):
        assert 0.5 <= float(count) <= 500, f"implausible star claim: {count}k"
