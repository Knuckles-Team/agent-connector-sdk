"""Shared on-disk library/state file path resolution and cross-process locking.

A connector that persists local state or library data outside the graph
(SDK-CONNECTOR-CONTROL-R034) resolves one path from configuration with
:func:`get_library_file_path` and guards a read-modify-write of it with
:func:`file_lock`, instead of each connector hand-rolling its own path
convention and locking primitive.
"""

from __future__ import annotations

import fcntl
import time
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from agent_connector_sdk.config import setting

__all__ = ["file_lock", "get_library_file_path"]

_DEFAULT_STATE_SETTING = "AGENT_STATE_DIR"


def get_library_file_path(
    connector: str, filename: str, *, base_setting: str = _DEFAULT_STATE_SETTING
) -> Path:
    """Resolve ``connector``'s on-disk library/state file path.

    Reads ``base_setting`` (default ``AGENT_STATE_DIR``) from configuration,
    falling back to ``XDG_STATE_HOME``, then ``~/.local/state``, and returns
    ``<base>/<connector>/<filename>``. The directory is not created; callers
    that write create it.
    """
    base = (
        setting(base_setting)
        or setting("XDG_STATE_HOME")
        or str(Path.home() / ".local" / "state")
    )
    return Path(str(base)) / connector / filename


@contextmanager
def file_lock(path: Path, *, timeout: float = 10.0) -> Iterator[None]:
    """Serialize a read-modify-write of ``path`` across processes.

    Holds an exclusive advisory lock on a sibling ``<path>.lock`` file for the
    duration of the ``with`` block, polling up to ``timeout`` seconds.

    Raises:
        TimeoutError: the lock was not acquired within ``timeout`` seconds.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    lock_path = path.with_name(path.name + ".lock")
    deadline = time.monotonic() + timeout
    with lock_path.open("w") as handle:
        while True:
            try:
                fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError:
                if time.monotonic() >= deadline:
                    raise TimeoutError(f"could not acquire lock for {path}") from None
                time.sleep(0.02)
        try:
            yield
        finally:
            fcntl.flock(handle, fcntl.LOCK_UN)
