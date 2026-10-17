"""Environment and event-loop helpers for the write-back sinks.

Replaces the host application's settings object with plain environment reads
so the sinks carry no dependency on any agent harness.
"""

from __future__ import annotations

import asyncio
import concurrent.futures
import os
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

_TRUE = {"1", "true", "yes", "on"}


def setting(name: str, default: Any = None, *, cast: Any = None) -> Any:
    """Read ``name`` from the environment; ``cast=bool`` parses truthy strings."""
    raw = os.environ.get(name)
    if raw is None:
        return default
    if cast is bool:
        return raw.strip().lower() in _TRUE
    if cast is not None:
        try:
            return cast(raw)
        except (TypeError, ValueError):
            return default
    return raw


def runtime_dir() -> Path:
    """State directory for the write-back ledger (``AGENT_CONNECTOR_STATE_DIR``)."""
    base = setting("AGENT_CONNECTOR_STATE_DIR") or os.path.join(
        setting("XDG_STATE_HOME") or os.path.expanduser("~/.local/state"),
        "agent-connector-sdk",
    )
    path = Path(base)
    path.mkdir(parents=True, exist_ok=True)
    return path


def run_sync_isolated[T](fn: Callable[[], T]) -> T:
    """Run a blocking ``asyncio.run`` based callable, on a worker thread when a loop runs."""
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return fn()
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
        return pool.submit(fn).result()


def stamp_bitemporal(
    props: dict[str, Any], *, event_time: str | None = None, now: str | None = None
) -> dict[str, Any]:
    """Inject storage/event/valid time onto ``props`` (idempotent, in place)."""
    stamp = now or datetime.now(UTC).isoformat()
    props.setdefault("storage_time", stamp)
    resolved = event_time or props.get("event_time") or props["storage_time"]
    props["event_time"] = resolved
    props.setdefault("valid_from", resolved)
    props.setdefault("valid_to", None)
    return props
