"""Bounded path-safe bookmark file access."""

from __future__ import annotations

import os
import stat
from contextlib import ExitStack
from pathlib import Path

from scion_sdk.adapters.bookmark_models import BookmarkReadError
from scion_sdk.adapters.safe_dir import no_follow_flags, use_dir_fd


def _segments(path: str) -> tuple[str, ...]:
    parts = path.split("/")
    if not parts or any(part in {"", ".", ".."} or "\x00" in part for part in parts):
        raise BookmarkReadError("access_denied")
    return tuple(parts)


def _read_file(root: Path, relative_path: str, max_bytes: int) -> bytes:
    """Open each component without following symlinks, and bound the read."""
    try:
        parts = _segments(relative_path)
        if not use_dir_fd():
            return _read_resolved(root, parts, max_bytes)
        return _open_and_read(root, parts, max_bytes)
    except OSError:
        raise BookmarkReadError("access_denied") from None


def _read_resolved(root: Path, parts: tuple[str, ...], max_bytes: int) -> bytes:
    """Portable path: refuse symlinks, confine to the resolved root, then read."""
    if os.path.islink(root):
        raise BookmarkReadError("access_denied")
    base = Path(root).resolve(strict=True)
    current = base
    for part in parts:
        current = current / part
        if os.path.islink(current):
            raise BookmarkReadError("access_denied")
    if base not in current.resolve(strict=True).parents:
        raise BookmarkReadError("access_denied")
    fd = os.open(current, os.O_RDONLY | no_follow_flags(nonblock=True))
    try:
        return _read_bounded(fd, max_bytes)
    finally:
        os.close(fd)


def _open_and_read(root: Path, parts: tuple[str, ...], max_bytes: int) -> bytes:
    with ExitStack() as stack:
        current = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        stack.callback(os.close, current)
        for part in parts[:-1]:
            current = os.open(
                part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=current
            )
            stack.callback(os.close, current)
        fd = os.open(
            parts[-1], os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=current
        )
        stack.callback(os.close, fd)
        return _read_bounded(fd, max_bytes)


def _read_bounded(fd: int, max_bytes: int) -> bytes:
    before = os.fstat(fd)
    if not stat.S_ISREG(before.st_mode):
        raise BookmarkReadError("access_denied")
    if before.st_size > max_bytes:
        raise BookmarkReadError("limit_exceeded")
    chunks: list[bytes] = []
    size = 0
    while size <= max_bytes:
        block = os.read(fd, min(65_536, max_bytes + 1 - size))
        if not block:
            break
        size += len(block)
        chunks.append(block)
    if size > max_bytes:
        raise BookmarkReadError("limit_exceeded")
    after = os.fstat(fd)
    if (before.st_size, before.st_mtime_ns, before.st_ctime_ns) != (
        after.st_size,
        after.st_mtime_ns,
        after.st_ctime_ns,
    ):
        raise BookmarkReadError("invalid_content")
    return b"".join(chunks)
