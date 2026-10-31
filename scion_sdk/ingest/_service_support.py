"""Status validation, loop lookup and error normalization for ingest commits."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable

from epistemic_graph.generated.source_ingestion import SourceIngestStatus

from scion_sdk.ingest.errors import IngestConflictError, IngestError
from scion_sdk.ingest.model import ChangeSet, IngestBinding

_MESSAGE_LIMIT = 300


def _validate_status(binding: IngestBinding, status: SourceIngestStatus) -> None:
    if status.connector != binding.connector or status.stream != binding.stream:
        raise IngestError("source status does not match the requested stream")
    if (
        status.accepted_checkpoint is not None
        and status.accepted_checkpoint.stream != binding.stream
    ):
        raise IngestError("accepted checkpoint does not match the requested stream")


def _running_loop() -> asyncio.AbstractEventLoop | None:
    try:
        return asyncio.get_running_loop()
    except RuntimeError:
        return None


def _require_rebuildable(changes: ChangeSet, conflict: IngestConflictError) -> None:
    """Re-raise ``conflict`` unless the change set can be rebuilt and retried.

    Opaque source cursors cannot be ordered against the winner's checkpoint.
    The caller must re-read before retrying this page.
    """
    if changes.cursor is not None or changes.source_page:
        raise conflict


async def _guard[T](call: Awaitable[T]) -> T:
    try:
        return await call
    except IngestError:
        raise
    except Exception as exc:
        detail = (str(exc).splitlines() or [type(exc).__name__])[0]
        raise IngestError(
            "epistemic-graph did not commit the change set: " + detail[:_MESSAGE_LIMIT]
        ) from exc
