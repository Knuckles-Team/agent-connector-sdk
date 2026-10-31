"""Token persistence for browser OAuth: the store protocol and the file store."""

from __future__ import annotations

import hashlib
import os
import stat
from pathlib import Path
from typing import Protocol


def _flag(name: str) -> int:
    """An ``os.O_*`` flag, or ``0`` where the platform lacks it (Windows)."""
    return int(getattr(os, name, 0))


def _refuse_symlink(path: Path) -> bool:
    """Without ``O_NOFOLLOW`` the open cannot refuse a symlink, so check first."""
    return not hasattr(os, "O_NOFOLLOW") and os.path.islink(path)


def _read_regular(fd: int) -> str | None:
    """Read and close ``fd`` when it is a regular file, else ``None``."""
    with os.fdopen(fd, "r", encoding="utf-8") as handle:
        if not stat.S_ISREG(os.fstat(handle.fileno()).st_mode):
            return None
        return handle.read()


def _truncate_owner_only(fd: int, path: Path) -> None:
    if not stat.S_ISREG(os.fstat(fd).st_mode):
        raise ValueError("token path must be a regular file")
    if hasattr(os, "fchmod"):
        os.fchmod(fd, 0o600)
    else:
        os.chmod(path, stat.S_IREAD | stat.S_IWRITE)
    os.ftruncate(fd, 0)


class TokenStore(Protocol):
    """Where a manager keeps its serialized token set."""

    def get(self, key: str) -> str | None: ...

    def set(self, key: str, value: str) -> None: ...


class FileTokenStore:
    """Owner-only JSON files, one per key, under ``root``.

    ``root`` defaults to ``scion_sdk.paths.config_dir()/oauth-tokens``.
    Filenames use a digest of the complete key. Legacy sanitized filenames are
    not read because different keys could have shared one file; users must
    sign in again after upgrading.
    """

    def __init__(self, root: Path | None = None) -> None:
        if root is None:
            from scion_sdk.paths import config_dir

            root = config_dir() / "oauth-tokens"
        self.root = Path(root)

    def _path(self, key: str) -> Path:
        digest = hashlib.sha256(key.encode("utf-8")).hexdigest()
        return self.root / f"{digest}.json"

    def get(self, key: str) -> str | None:
        path = self._path(key)
        if _refuse_symlink(path):
            return None
        try:
            fd = os.open(path, os.O_RDONLY | _flag("O_NOFOLLOW") | _flag("O_NONBLOCK"))
        except OSError:
            return None
        try:
            return _read_regular(fd)
        except OSError:
            return None

    def set(self, key: str, value: str) -> None:
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
        path = self._path(key)
        if _refuse_symlink(path):
            raise ValueError("token path must not be a symlink")
        flags = os.O_WRONLY | os.O_CREAT | _flag("O_NOFOLLOW") | _flag("O_NONBLOCK")
        fd = os.open(path, flags, 0o600)
        try:
            _truncate_owner_only(fd, path)
        except BaseException:
            os.close(fd)
            raise
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(value)
