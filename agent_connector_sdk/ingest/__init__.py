"""Knowledge ingest: connectors push typed change sets into epistemic-graph.

A connector describes what it observed as a :class:`ChangeSet` and submits it
with its :class:`IngestBinding`::

    from agent_connector_sdk.ingest import ChangeSet, Entity, IngestBinding, ingest_changes

    BINDING = IngestBinding(connector="demo-mcp", stream="demo")
    receipt = ingest_changes(BINDING, ChangeSet(entities=(Entity("demo:1", "Item"),)))

The SDK maps the change set to one generated epistemic-graph ``SourceIngest``
request against the stream's durable checkpoint and returns the generated
receipt. epistemic-graph resolves every record and relation against the
connector's published Connector Manifest, so each ``node_type`` and
relationship must be declared there.

The process's service is the one :func:`install_ingest` set, else one built
from ``EPISTEMIC_GRAPH_*`` settings on first use
(:mod:`agent_connector_sdk.ingest.engine`), else ingest is unavailable and
raises :class:`IngestUnavailableError`.
"""

from __future__ import annotations

import threading

import anyio
from epistemic_graph.generated.source_ingestion import SourceIngestionReceipt

from agent_connector_sdk.ingest.engine import EngineSettings, connect_ingest
from agent_connector_sdk.ingest.errors import (
    IngestConflictError,
    IngestError,
    IngestUnavailableError,
)
from agent_connector_sdk.ingest.model import (
    ChangeSet,
    Document,
    Entity,
    EntityRef,
    IngestBinding,
    MediaAsset,
    Relationship,
    Withdrawal,
)
from agent_connector_sdk.ingest.service import KnowledgeIngest

__all__ = [
    "ChangeSet",
    "Document",
    "Entity",
    "EntityRef",
    "IngestBinding",
    "IngestConflictError",
    "IngestError",
    "IngestUnavailableError",
    "KnowledgeIngest",
    "MediaAsset",
    "Relationship",
    "Withdrawal",
    "aingest_changes",
    "current_ingest",
    "ingest_changes",
    "install_ingest",
]

_PROCESS: list[KnowledgeIngest | None] = [None]
_LOCK = threading.Lock()


def install_ingest(ingest: KnowledgeIngest | None) -> None:
    """Install ``ingest`` for the whole process (``None`` uninstalls)."""
    with _LOCK:
        _PROCESS[0] = ingest


def current_ingest() -> KnowledgeIngest:
    """The installed service, else one connected from settings (cached).

    Raises:
        IngestUnavailableError: nothing is installed and no endpoint is
            configured, or the configured engine is unreachable.
    """
    with _LOCK:
        installed = _PROCESS[0]
        if installed is None:
            settings = EngineSettings.from_settings()
            if settings is None:
                raise IngestUnavailableError(
                    "knowledge ingest is not configured: set EPISTEMIC_GRAPH_ENDPOINT"
                )
            installed = _PROCESS[0] = connect_ingest(settings)
        return installed


def ingest_changes(
    binding: IngestBinding, changes: ChangeSet
) -> SourceIngestionReceipt:
    """Commit ``changes`` from synchronous code; see :class:`KnowledgeIngest`."""
    return current_ingest().submit_blocking(binding, changes)


async def aingest_changes(
    binding: IngestBinding, changes: ChangeSet
) -> SourceIngestionReceipt:
    """Commit ``changes`` from asynchronous code; see :class:`KnowledgeIngest`.

    A first use that has to connect does so in a worker thread.
    """
    ingest = await anyio.to_thread.run_sync(current_ingest)
    return await ingest.submit(binding, changes)
