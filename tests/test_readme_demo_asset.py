"""Guard the README hero demo image (issue #15).

The recorded demo landed in `docs/demo.gif` on 2026-06-16, but the README hero
kept pointing at `docs/demo.svg` — the pre-recording placeholder — for six
weeks. The asset shipped; the one-line docs change that wires it up did not.
That is the recurring failure mode in this repo, so it gets a test.

These assertions are about the *file resolving on disk*, not about the README
containing a particular string: a hero that points at an uncommitted or
misspelled path is exactly the bug, and only a filesystem check catches it.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
README = REPO_ROOT / "README.md"

# The hero is a raw.githubusercontent URL so it renders on PyPI and in the
# skill catalog, where relative paths break. Capture the docs-relative tail.
HERO_RE = re.compile(
    r'<img\s+src="https://raw\.githubusercontent\.com/abhinaykrupa/'
    r'cowork-to-code-bridge/main/(docs/[^"]+)"'
)


def _hero_asset_path(readme_text: str) -> str:
    match = HERO_RE.search(readme_text)
    assert match is not None, (
        "README has no recognizable hero <img> pointing at a docs/ asset on "
        "raw.githubusercontent.com. If the hero moved, update HERO_RE here too."
    )
    return match.group(1)


def test_hero_image_asset_exists():
    """The README hero must reference a file that is actually in the repo."""
    asset = _hero_asset_path(README.read_text())
    assert (REPO_ROOT / asset).is_file(), (
        f"README hero points at {asset!r}, which does not exist in the repo. "
        "GitHub would render a broken image on the project's front page."
    )


def test_hero_image_asset_is_committed():
    """A hero asset present only in the working tree would 404 for everyone else."""
    import subprocess

    asset = _hero_asset_path(README.read_text())
    result = subprocess.run(
        ["git", "ls-files", "--error-unmatch", asset],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, (
        f"README hero asset {asset!r} is not tracked by git. The raw."
        "githubusercontent URL resolves against origin/main, so an untracked "
        "file renders as a broken image for every visitor."
    )


def test_hero_uses_the_recorded_demo_not_the_placeholder():
    """docs/demo.svg was the placeholder; the real recording is docs/demo.gif.

    Issue #15 is only closed when the hero shows the recording. If the hero is
    ever pointed back at the placeholder, that regression is the bug.
    """
    asset = _hero_asset_path(README.read_text())
    assert asset != "docs/demo.svg", (
        "README hero reverted to the pre-recording placeholder (docs/demo.svg). "
        "The recorded demo lives at docs/demo.gif — see docs/demo-recording-script.md."
    )


def test_guard_rejects_a_missing_asset():
    """Negative control: the existence check must actually fail on a bad path.

    Without this, a regex that silently stopped matching would leave every
    assertion above vacuously true and the guard would pass forever.
    """
    # Rewrite whatever the current hero is, so this control does not itself
    # depend on today's asset name.
    current = _hero_asset_path(README.read_text())
    broken = README.read_text().replace(current, "docs/does-not-exist.gif")
    asset = _hero_asset_path(broken)
    assert asset == "docs/does-not-exist.gif"
    assert not (REPO_ROOT / asset).is_file()


def test_guard_rejects_a_readme_with_no_hero():
    """Negative control: a stripped hero must raise, not pass silently."""
    with pytest.raises(AssertionError, match="no recognizable hero"):
        _hero_asset_path("# cowork-to-code-bridge\n\nNo image here.\n")
