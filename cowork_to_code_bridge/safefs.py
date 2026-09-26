"""Symlink-safe file I/O inside a directory an untrusted party can write to.

BRIDGE_ROOT is shared with the sandbox, which can create, delete and replace
anything under it — including swapping a file or a whole subdirectory for a
symlink that points outside the bridge. Plain path I/O follows those links, so
every daemon write became "write wherever the sandbox says".

Every helper here anchors on a directory file descriptor opened with
O_NOFOLLOW and then operates on a single path component relative to it. That
is race-free: once the directory fd is open, swapping the directory for a link
cannot redirect the operation, and a symlink at the final component is refused
by the kernel (ELOOP) rather than followed.

Only the *final* component of the directory path is checked. BRIDGE_ROOT
itself is configured by the machine owner and is the sandbox's mount point, so
the sandbox cannot replace it.
"""
from __future__ import annotations

import os
import secrets
import stat
from collections.abc import Iterator
from contextlib import contextmanager, suppress
from pathlib import Path

_NOFOLLOW = getattr(os, "O_NOFOLLOW", 0)
_CLOEXEC = getattr(os, "O_CLOEXEC", 0)
_DIRECTORY = getattr(os, "O_DIRECTORY", 0)
_NONBLOCK = getattr(os, "O_NONBLOCK", 0)


class UnsafePath(OSError):
    """A path inside the bridge was a symlink, special file, or multiply linked."""


class TooLarge(OSError):
    """A file exceeded the caller's size limit."""


@contextmanager
def open_dir(path: Path | str) -> Iterator[int]:
    """Yield an fd for directory `path`, refusing if it is a symlink."""
    try:
        fd = os.open(os.fspath(path), os.O_RDONLY | _DIRECTORY | _NOFOLLOW | _CLOEXEC)
    except OSError as e:
        if os.path.islink(path):
            raise UnsafePath(f"refusing symlinked directory: {path}") from e
        raise
    try:
        if not stat.S_ISDIR(os.fstat(fd).st_mode):
            raise UnsafePath(f"not a directory: {path}")
        yield fd
    finally:
        os.close(fd)


def _check_regular(fd: int, where: str) -> os.stat_result:
    st = os.fstat(fd)
    if not stat.S_ISREG(st.st_mode):
        raise UnsafePath(f"not a regular file: {where}")
    # A hard link to a file outside the bridge would let a write land there.
    if st.st_nlink > 1:
        raise UnsafePath(f"refusing multiply-linked file: {where}")
    return st


def _open_leaf(dfd: int, name: str, flags: int, where: str, mode: int = 0o600) -> int:
    if not name or "/" in name or name in (".", ".."):
        raise UnsafePath(f"invalid path component: {name!r}")
    try:
        return os.open(name, flags | _NOFOLLOW | _CLOEXEC, mode, dir_fd=dfd)
    except OSError as e:
        # Distinguish "a link was planted here" from ordinary errors. The lstat
        # is outside any suppress(): UnsafePath is itself an OSError and must
        # not be swallowed by the handler meant for the lstat.
        try:
            is_link = stat.S_ISLNK(os.stat(name, dir_fd=dfd, follow_symlinks=False).st_mode)
        except OSError:
            is_link = False
        if is_link:
            raise UnsafePath(f"refusing symlink: {where}") from e
        raise


def write_atomic(directory: Path | str, name: str, data: bytes, *,
                 mode: int = 0o600, fsync: bool = False) -> None:
    """Write `data` to directory/name atomically without following links.

    The temp file gets an unpredictable name and is created with O_EXCL, so it
    cannot be pre-planted. rename(2) replaces a pre-planted link at `name`
    instead of following it.
    """
    with open_dir(directory) as dfd:
        tmp = f".{name}.{secrets.token_hex(8)}.tmp"
        fd = _open_leaf(dfd, tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL,
                        f"{directory}/{tmp}", mode)
        try:
            try:
                view = memoryview(data)
                while view:
                    view = view[os.write(fd, view):]
                if fsync:
                    os.fsync(fd)
            finally:
                os.close(fd)
            os.rename(tmp, name, src_dir_fd=dfd, dst_dir_fd=dfd)
        except BaseException:
            with suppress(OSError):
                os.unlink(tmp, dir_fd=dfd)
            raise


def open_append(directory: Path | str, name: str, *, truncate: bool = False,
                mode: int = 0o600) -> int:
    """Return a writable, appending fd for directory/name. Caller closes it.

    Truncation happens only after the file is verified to be a regular,
    singly-linked file inside the bridge — O_TRUNC at open time would already
    have destroyed whatever a planted link pointed at.
    """
    with open_dir(directory) as dfd:
        fd = _open_leaf(dfd, name, os.O_WRONLY | os.O_APPEND | os.O_CREAT,
                        f"{directory}/{name}", mode)
    try:
        _check_regular(fd, f"{directory}/{name}")
        if truncate:
            os.ftruncate(fd, 0)
        return fd
    except BaseException:
        os.close(fd)
        raise


def read_regular(directory: Path | str, name: str, max_bytes: int | None = None) -> bytes:
    """Read directory/name, refusing links, FIFOs, devices and oversize files.

    Opened O_NONBLOCK so a FIFO planted in a watched directory cannot block the
    reader forever; it is then rejected as non-regular.
    """
    with open_dir(directory) as dfd:
        fd = _open_leaf(dfd, name, os.O_RDONLY | _NONBLOCK, f"{directory}/{name}")
    try:
        st = os.fstat(fd)
        if not stat.S_ISREG(st.st_mode):
            raise UnsafePath(f"not a regular file: {directory}/{name}")
        if max_bytes is not None and st.st_size > max_bytes:
            raise TooLarge(f"{directory}/{name} is {st.st_size} bytes (> {max_bytes})")
        chunks, total = [], 0
        while True:
            chunk = os.read(fd, 1 << 16)
            if not chunk:
                break
            chunks.append(chunk)
            total += len(chunk)
            if max_bytes is not None and total > max_bytes:
                raise TooLarge(f"{directory}/{name} grew past {max_bytes} bytes")
        return b"".join(chunks)
    finally:
        os.close(fd)


def move(src_dir: Path | str, dst_dir: Path | str, name: str,
         dst_name: str | None = None) -> None:
    """rename src_dir/name -> dst_dir/dst_name. Moves a link itself, never its target."""
    with open_dir(src_dir) as sfd, open_dir(dst_dir) as dfd:
        os.rename(name, dst_name or name, src_dir_fd=sfd, dst_dir_fd=dfd)


def unlink(directory: Path | str, name: str) -> None:
    """Remove directory/name if present. Removes a link itself, never its target."""
    with open_dir(directory) as dfd, suppress(FileNotFoundError):
        os.unlink(name, dir_fd=dfd)


def is_regular(directory: Path | str, name: str) -> bool:
    """True if directory/name exists and is a regular file (not a link)."""
    try:
        with open_dir(directory) as dfd:
            st = os.stat(name, dir_fd=dfd, follow_symlinks=False)
    except OSError:
        return False
    return stat.S_ISREG(st.st_mode)


def heal_dir(path: Path, mode: int = 0o700) -> bool:
    """Ensure `path` is a real directory; replace a planted symlink with one.

    Returns True if something had to be repaired, so the caller can log it.
    """
    try:
        st = os.lstat(path)
    except FileNotFoundError:
        path.mkdir(parents=True, exist_ok=True, mode=mode)
        return False
    if stat.S_ISDIR(st.st_mode):
        return False
    # A symlink or stray file where a state directory belongs.
    os.unlink(path)
    path.mkdir(mode=mode)
    return True
