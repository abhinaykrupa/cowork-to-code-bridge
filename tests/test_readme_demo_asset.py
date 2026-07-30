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


# ── Issue #12: the same wiring guarantee for CONTRIBUTING ──────────────────
#
# #15 was "the asset exists but no doc points at it" for the README. #12 is the
# same shape for CONTRIBUTING: the recording landed, but the contributor-facing
# page that asks people to record one never showed it. Wiring without a guard is
# how #15 stayed broken for six weeks, so #12 gets the identical treatment.

CONTRIBUTING = REPO_ROOT / "CONTRIBUTING.md"


def test_contributing_shows_the_recorded_demo():
    """CONTRIBUTING must embed the recording, not just describe recording one."""
    text = CONTRIBUTING.read_text()
    match = HERO_RE.search(text)
    assert match is not None, (
        "CONTRIBUTING.md has no demo <img> pointing at a docs/ asset. Issue #12 "
        "asked for a quickstart demo on the contributor page; docs/demo.gif "
        "exists, so the page should show it."
    )
    asset = match.group(1)
    assert (REPO_ROOT / asset).is_file(), (
        f"CONTRIBUTING.md embeds {asset!r}, which is not in the repo."
    )


def test_contributing_links_the_recording_shot_list():
    """The 'how to re-cut this' path must stay discoverable from CONTRIBUTING."""
    assert "docs/demo-recording-script.md" in CONTRIBUTING.read_text(), (
        "CONTRIBUTING.md no longer links docs/demo-recording-script.md. That "
        "shot list is the entry point for the docs/media contribution in #12."
    )


def test_no_orphaned_media_assets_in_docs():
    """Every committed docs/ image must have at least one inbound reference.

    The recurring bug class in this repo is an asset and its wiring landing
    separately. An orphan is the early warning: either a doc meant to show it
    and does not, or it is dead weight that should have been deleted.

    Sources are grandfathered explicitly — an .svg/.mp4 kept as the editable
    source or fallback for a shipped asset is intentionally unreferenced.
    """
    import subprocess

    # Known-intentional orphans, with the reason they are allowed to be one.
    ALLOWED_ORPHANS = {
        # Editable vector source for the rendered social-card.png.
        "docs/social-card.svg",
        # Full-length take; docs/demo.gif is the trimmed clip that ships.
        "docs/demo_full.mp4",
        # Same recording as demo.gif, kept for re-encoding if the GIF is re-cut.
        "docs/demo.mp4",
    }

    tracked = subprocess.run(
        ["git", "ls-files", "docs/"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.split()
    media = [
        p for p in tracked
        if p.lower().endswith((".gif", ".png", ".svg", ".mp4", ".cast"))
    ]
    assert media, "expected some media under docs/ — has the layout changed?"

    # Search every text file in the repo for the asset's basename. Basename
    # rather than full path, because the README references assets via absolute
    # raw.githubusercontent URLs while CONTRIBUTING may use relative paths.
    searchable = subprocess.run(
        ["git", "ls-files", "*.md", "*.py", "*.sh", "*.json", "*.yml", "*.toml"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.split()
    corpus = "\n".join(
        (REPO_ROOT / f).read_text(errors="ignore")
        for f in searchable
        if (REPO_ROOT / f).is_file()
    )

    orphans = []
    for asset in media:
        if asset in ALLOWED_ORPHANS:
            continue
        if Path(asset).name not in corpus:
            orphans.append(asset)

    assert not orphans, (
        f"docs/ media with no inbound reference anywhere: {orphans}. Either "
        "wire each into the doc it was made for, delete it, or add it to "
        "ALLOWED_ORPHANS with the reason it is intentionally unreferenced."
    )


def test_orphan_guard_would_catch_an_unreferenced_asset():
    """Negative control: the orphan check must flag a name nothing mentions.

    Guards that only ever assert 'no problems found' can rot into always-true.
    This pins the actual mechanism: a basename absent from the corpus is an
    orphan, and one present is not.
    """
    corpus = "see docs/demo.gif for the clip"
    assert Path("docs/demo.gif").name in corpus
    assert Path("docs/never-referenced-anywhere.png").name not in corpus
