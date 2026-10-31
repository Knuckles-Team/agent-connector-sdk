"""Create and clean temporary files under an authorized directory."""

from __future__ import annotations

import os
import uuid
from collections.abc import Iterator
from contextlib import contextmanager, suppress
from pathlib import Path

from scion_sdk.adapters.paper_document_errors import DocumentRefusal
from scion_sdk.adapters.safe_dir import SafeDir


def _open_validation(directory: SafeDir, name: str) -> int:
    try:
        return directory.open_file(name, os.O_RDONLY)
    except OSError:
        raise DocumentRefusal("storage_denied") from None


@contextmanager
def _temporary(root: Path) -> Iterator[tuple[SafeDir, str, int]]:
    try:
        directory = SafeDir.open(root)
    except OSError:
        raise DocumentRefusal("storage_denied") from None
    try:
        yield from _open_temporary(directory)
    finally:
        directory.close()


def _open_temporary(directory: SafeDir) -> Iterator[tuple[SafeDir, str, int]]:
    name = ".paper-" + uuid.uuid4().hex
    try:
        fd = directory.open_file(name, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    except OSError:
        raise DocumentRefusal("storage_denied") from None
    try:
        yield directory, name, fd
    finally:
        os.close(fd)
        with suppress(FileNotFoundError):
            directory.unlink(name)
