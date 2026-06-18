"""Shared pytest configuration for the bridge test-suite.

Guarantees that the *source* package (the one in this repository) is the one
imported under test, regardless of whether — or which version of —
``cowork-to-code-bridge`` happens to be pip-installed in the active
interpreter. Without this, a stale site-packages copy can silently shadow the
source tree and tests will exercise old code (e.g. an ``mcp_server`` that
predates ``cancel_operation``).
"""
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

# Prepend so the in-repo package wins over any installed copy.
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
else:
    sys.path.remove(str(REPO_ROOT))
    sys.path.insert(0, str(REPO_ROOT))
