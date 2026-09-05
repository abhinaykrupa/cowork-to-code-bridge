"""Guard the README's install instructions against advertising things that don't exist.

The README is the highest-traffic page in the project — GitHub's own traffic data
puts `/abhinaykrupa/cowork-to-code-bridge` far ahead of every other path. A broken
badge or a `pip install` that 404s there reads as an abandoned project to exactly
the people evaluating whether to use it.

Two failures shipped and sat for weeks before these tests existed:

1. Three PyPI badges rendered "pypi: package or version not found" in the top
   badge row, because the package was never published.
2. `pip install cowork-to-code-bridge` was documented as the developer install
   while that name resolves to a 404 on PyPI.

These tests are offline and deterministic: they assert the README does not make a
claim that depends on an unpublished artifact. When PyPI publication actually
happens (issue #41), flip PACKAGE_ON_PYPI to True and the expectations invert.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

README = Path(__file__).resolve().parent.parent / "README.md"

# Flip to True in the same commit that publishes to PyPI (issue #41).
PACKAGE_ON_PYPI = False


@pytest.fixture(scope="module")
def readme() -> str:
    return README.read_text()


def test_no_pypi_badges_until_published(readme: str):
    """shields.io PyPI badges render an error string while the package is absent."""
    if PACKAGE_ON_PYPI:
        pytest.skip("package is published; PyPI badges are expected")
    offenders = re.findall(r"img\.shields\.io/pypi/\w+/[^\s)]+", readme)
    assert not offenders, (
        "README shows PyPI badge(s) but the package is not on PyPI — these render "
        f"as 'package or version not found': {offenders}"
    )


def test_no_bare_pip_install_until_published(readme: str):
    """`pip install cowork-to-code-bridge` fails until the name exists on PyPI."""
    if PACKAGE_ON_PYPI:
        pytest.skip("package is published; the bare pip install is valid")
    # A bare install of the distribution name, not the git+https form.
    bare = re.search(r"pip install\s+(?!git\+)(?:-\S+\s+)*cowork-to-code-bridge\b", readme)
    assert bare is None, (
        "README documents `pip install cowork-to-code-bridge`, which 404s until the "
        "package is published. Use the git+https form, or flip PACKAGE_ON_PYPI."
    )


def test_documents_a_working_pip_install(readme: str):
    """Whatever the state, the developer install path must be runnable as written."""
    assert "pip install git+https://github.com/abhinaykrupa/cowork-to-code-bridge" in readme \
        or PACKAGE_ON_PYPI, "README must document an install command that actually resolves"


def test_no_link_to_the_pypi_project_page(readme: str):
    """Linking a badge to a 404 project page is the same failure, one click later."""
    if PACKAGE_ON_PYPI:
        pytest.skip("package is published; the project page exists")
    assert "pypi.org/project/cowork-to-code-bridge" not in readme, (
        "README links to the PyPI project page, which 404s until publication"
    )


def test_unpublished_artifacts_are_marked_conditional(readme: str):
    """Homebrew is not published either — it must read as conditional, not available.

    Negative control for the tests above: the guard is about *claiming* something
    works, not about mentioning it. Mentioning a planned tap is fine; telling the
    reader to run it as though it exists is not.
    """
    if "brew install abhinaykrupa/tap" in readme:
        idx = readme.index("brew install abhinaykrupa/tap")
        context = readme[max(0, idx - 200):idx]
        assert re.search(r"once\b|planned|not yet|when .*published", context, re.I), (
            "README presents the Homebrew tap as available, but "
            "github.com/abhinaykrupa/homebrew-tap does not exist"
        )
