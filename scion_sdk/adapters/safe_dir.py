"""A confined directory handle that works with and without ``dir_fd`` support.

POSIX opens the root once and resolves every name against that descriptor with
``O_NOFOLLOW``. Windows has no ``O_DIRECTORY``, ``O_NOFOLLOW``, ``O_NONBLOCK``
or ``dir_fd`` (``os.supports_dir_fd``), so the fallback resolves the path,
verifies it stays under the resolved root and refuses symlinks before opening.
"""

from __future__ import annotations

import os
from pathlib import Path

__all__ = ["SafeDir", "SafeDirError", "no_follow_flags", "use_dir_fd"]


class SafeDirError(OSError):
    """The requested path is outside the root, a symlink, or unopenable."""


def use_dir_fd() -> bool:
    """True when directory-relative, no-follow opens are available."""
    return (
        hasattr(os, "O_DIRECTORY")
        and hasattr(os, "O_NOFOLLOW")
        and os.open in os.supports_dir_fd
    )


def no_follow_flags(*, nonblock: bool = False) -> int:
    """Open flags that exist on this platform (``0`` where unsupported)."""
    flags = getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_BINARY", 0)
    if nonblock:
        flags |= getattr(os, "O_NONBLOCK", 0)
    return flags


class SafeDir:
    """An open directory that names may be opened, linked and removed under."""

    def __init__(self, path: Path, fd: int | None) -> None:
        self.path = path
        self.fd = fd

    @classmethod
    def open(cls, root: Path | str) -> SafeDir:
        if use_dir_fd():
            fd = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
            return cls(Path(root), fd)
        if os.path.islink(root):
            raise SafeDirError("root is a symlink")
        resolved = Path(root).resolve(strict=True)
        if not resolved.is_dir():
            raise SafeDirError("root is not a directory")
        return cls(resolved, None)

    def dup(self) -> SafeDir:
        return SafeDir(self.path, None if self.fd is None else os.dup(self.fd))

    def close(self) -> None:
        if self.fd is not None:
            os.close(self.fd)
            self.fd = None

    def _target(self, name: str) -> Path:
        if not name or name in {".", ".."} or "/" in name or "\\" in name:
            raise SafeDirError("invalid name")
        target = self.path / name
        if os.path.islink(target):
            raise SafeDirError("symlink refused")
        if target.parent.resolve() != self.path:
            raise SafeDirError("path escapes root")
        return target

    def open_file(
        self, name: str, flags: int, mode: int = 0o777, *, nonblock: bool = False
    ) -> int:
        flags |= no_follow_flags(nonblock=nonblock)
        if self.fd is not None:
            return os.open(name, flags, mode, dir_fd=self.fd)
        return os.open(self._target(name), flags, mode)

    def link(self, src: str, dst: str) -> None:
        if self.fd is not None:
            os.link(
                src, dst, src_dir_fd=self.fd, dst_dir_fd=self.fd, follow_symlinks=False
            )
        else:
            os.link(self._target(src), self.path / self._target_name(dst))

    def _target_name(self, name: str) -> str:
        if not name or "/" in name or "\\" in name or name in {".", ".."}:
            raise SafeDirError("invalid name")
        return name

    def unlink(self, name: str) -> None:
        if self.fd is not None:
            os.unlink(name, dir_fd=self.fd)
        else:
            os.unlink(self.path / self._target_name(name))
