"""The version string lives in seven places and must never disagree.

pyproject, the package, both single-file clients, the MCP server, the MCP
operations handshake, and install.sh's package floor all carry it. A stale copy
is invisible: the wheel builds, the daemon starts, and the MCP handshake simply
reports a version that shipped two releases ago — so a user filing a bug names
the wrong version and nobody can reproduce it.

Same silent-drift class as the routing tables (#80) and the install.sh heredocs
(#81): duplicated constants with no mechanical check between them.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
PYPROJECT = REPO / "pyproject.toml"

# file -> regex capturing the version
SOURCES = {
    "cowork_to_code_bridge/__init__.py": r'__version__\s*=\s*"([^"]+)"',
    "cowork_to_code_bridge/mcp_server.py": r'__version__\s*=\s*"([^"]+)"',
    "cowork_to_code_bridge/mcp_operations.py": r'"version":\s*"([^"]+)"',
    "bridge_client.py": r'__version__\s*=\s*"([^"]+)"',
    "skill/cowork-to-code-bridge/bridge_client.py": r'__version__\s*=\s*"([^"]+)"',
}


def _canonical() -> str:
    m = re.search(r'^version\s*=\s*"([^"]+)"', PYPROJECT.read_text(), re.M)
    assert m, "pyproject.toml has no version"
    return m.group(1)


def test_canonical_version_is_semver():
    assert re.fullmatch(r"\d+\.\d+\.\d+", _canonical()), \
        f"version {_canonical()!r} is not MAJOR.MINOR.PATCH"


@pytest.mark.parametrize("rel", sorted(SOURCES))
def test_source_matches_pyproject(rel: str):
    """Every copy of the version must equal pyproject's."""
    path = REPO / rel
    assert path.is_file(), f"{rel} is missing — update SOURCES if it moved"
    m = re.search(SOURCES[rel], path.read_text())
    assert m, f"{rel} no longer matches its version pattern"
    assert m.group(1) == _canonical(), (
        f"{rel} declares {m.group(1)}, pyproject declares {_canonical()}"
    )


def test_installer_floor_matches_version():
    """install.sh pins a minimum package version; a stale floor installs an old wheel."""
    text = (REPO / "install.sh").read_text()
    m = re.search(r'PACKAGE_SPEC="cowork-to-code-bridge>=([^"]+)"', text)
    assert m, "install.sh lost its PACKAGE_SPEC floor"
    assert m.group(1) == _canonical(), (
        f"install.sh floors at {m.group(1)}, pyproject declares {_canonical()}"
    )


def test_changelog_documents_the_current_version():
    """A release with no changelog entry is undocumented for every downstream reader."""
    changelog = (REPO / "CHANGELOG.md").read_text()
    assert f"[{_canonical()}]" in changelog, \
        f"CHANGELOG.md has no entry for {_canonical()}"
