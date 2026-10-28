"""Create and clean temporary files under an authorized directory."""

from __future__ import annotations

import os
import uuid
from collections.abc import Iterator
from contextlib import contextmanager, suppress
from pathlib import Path

from agent_connector_sdk.adapters.paper_document_errors import DocumentRefusal


@contextmanager
def _temporary(root: Path) -> Iterator[tuple[int, str, int]]:
    try:
        directory = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    except OSError:
        raise DocumentRefusal("storage_denied") from None
    try:
        yield from _open_temporary(directory)
    finally:
        os.close(directory)


def _open_temporary(directory: int) -> Iterator[tuple[int, str, int]]:
    name = ".paper-" + uuid.uuid4().hex
    try:
        fd = os.open(
            name,
            os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW,
            0o600,
            dir_fd=directory,
        )
    except OSError:
        raise DocumentRefusal("storage_denied") from None
    try:
        yield directory, name, fd
    finally:
        os.close(fd)
        with suppress(FileNotFoundError):
            os.unlink(name, dir_fd=directory)
