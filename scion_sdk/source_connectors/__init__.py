"""Document-source connector framework (CONCEPT:AU-ECO.connector.document-source-framework-4.29).

Onyx-parity document ingestion bolted onto agent-utilities' semantic core: a
``load`` / ``poll`` / ``slim`` connector abstraction (:mod:`base`), resumable
checkpoints (:mod:`checkpoint`, ECO-4.26), a self-registering factory
(:mod:`registry`, ECO-4.27), access descriptors rendered as record
properties (:func:`access_properties`), and reference connectors under
:mod:`connectors` (web/filesystem/rest + the agent-package fleet adapter, ECO-4.29).

Documents enter the Knowledge Graph through the ``CONNECTOR`` ingestion adaptor,
which runs each :class:`SourceDocument` through the KG-2.48 ``DocumentProcessor``
so it becomes first-class ``Document`` + ``Chunk`` ontology objects with OWL
semantics, bitemporal slicing, and entailment-aware ACLs.
"""

from typing import Any

from .base import (
    BaseSourceConnector,
    ExternalAccess,
    LoadConnector,
    PermSyncConnector,
    PollConnector,
    SlimConnector,
    SlimDocument,
    SourceDocument,
)
from .checkpoint import CheckpointedBatch, ConnectorCheckpoint
from .registry import (
    ConnectorGovernanceError,
    build_connector,
    discover,
    get_connector_class,
    list_sources,
    register_source,
)

__all__ = [
    "BaseSourceConnector",
    "CheckpointedBatch",
    "ConnectorCheckpoint",
    "ConnectorGovernanceError",
    "ExternalAccess",
    "LoadConnector",
    "PermSyncConnector",
    "PollConnector",
    "SlimConnector",
    "SlimDocument",
    "SourceDocument",
    "access_properties",
    "build_connector",
    "discover",
    "get_connector_class",
    "list_sources",
    "register_source",
]


def __getattr__(name: str) -> Any:
    """Resolve :func:`access_properties` lazily.

    A connector reports each document's :class:`ExternalAccess`;
    :func:`~scion_sdk.adapters.document_sources.access_properties`
    renders it as the record properties epistemic-graph enforces. The ACL
    itself is written by the graph service, not by this package.
    """
    if name == "access_properties":
        from scion_sdk.adapters.document_sources import access_properties

        return access_properties
    raise AttributeError(name)
