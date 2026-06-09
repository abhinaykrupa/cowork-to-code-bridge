"""cowork-to-code-bridge — async file-based RPC between Cowork sandbox and your Mac shell.

Run commands on your local Mac from inside a Cowork session, via a small daemon
that polls a shared bind-mounted directory. MIT licensed.
"""
from __future__ import annotations

from .client import call_remote, call_remote_streaming, daemon_alive

__version__ = "0.5.1"
__all__ = ["call_remote", "call_remote_streaming", "daemon_alive", "__version__"]
