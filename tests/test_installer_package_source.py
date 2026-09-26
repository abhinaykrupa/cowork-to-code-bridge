"""install.sh must install the package from the tree it ships in, when it has one.

When PyPI had nothing (always, so far), the installer fell back to
`git+https://…@main` unconditionally — including when it was running from a
release tarball or a Homebrew formula. A "v0.6.1" install therefore got
whatever was on main that day. The selection now lives in `package_source()`,
and these tests run the real function text extracted from install.sh, so they
cannot drift from what ships.
"""
from __future__ import annotations

import re
import subprocess
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent


def _fn() -> str:
    text = (REPO / "install.sh").read_text()
    m = re.search(r"^package_source\(\) \{.*?^\}\n", text, re.S | re.M)
    assert m, "install.sh lost package_source()"
    return m.group(0)


def _select(install_dir: str) -> str:
    out = subprocess.run(["bash", "-c", _fn() + 'package_source "$1"', "bash", install_dir],
                         capture_output=True, text=True, check=True)
    return out.stdout.strip()


def test_source_tree_is_installed_locally():
    """The repo itself is a source tree — exactly what a tarball/formula unpacks."""
    assert _select(str(REPO)) == f"local:{REPO}"


def test_piped_install_with_no_tree_goes_remote(tmp_path):
    """curl | bash has no directory of its own; it must keep the remote path."""
    assert _select("") == "remote"
    assert _select(str(tmp_path)) == "remote"


def test_a_stray_pyproject_is_not_enough(tmp_path):
    """Negative control: only a tree that actually contains the package counts."""
    (tmp_path / "pyproject.toml").write_text("[project]\nname='something-else'\n")
    assert _select(str(tmp_path)) == "remote"


def test_local_branch_is_tried_before_pypi_and_main():
    """Order matters: a bundled tree must win over both network sources."""
    text = (REPO / "install.sh").read_text()
    i_local = text.index('if [[ "$_PKG_SRC" == local:* ]]')
    i_pypi = text.index('elif pip_install_user "$PACKAGE_SPEC"')
    i_main = text.index('pip_install_user "git+https://github.com/$REPO.git@main"')
    assert i_local < i_pypi < i_main
