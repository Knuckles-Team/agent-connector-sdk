"""Typed change sets a connector hands to the knowledge-ingest facade.

A change set names source observations only: entity records, text documents,
binary media and the relationships between them. Mapping, identity, raw
admission, tombstones and the durable checkpoint belong to epistemic-graph's
``SourceIngest`` contract; nothing here builds graph rows.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

from epistemic_graph.generated.source_ingestion import SourceIngestionMode

__all__ = [
    "ChangeSet",
    "Document",
    "Entity",
    "EntityRef",
    "IngestBinding",
    "MediaAsset",
    "Relationship",
    "Withdrawal",
]

_ADAPTER_KIND = "connector_push"


@dataclass(frozen=True)
class IngestBinding:
    """Where a connector's change sets land: its manifest identity and stream.

    Attributes:
        connector: The Connector Manifest ``connector`` id (for example
            ``"searxng-mcp"``); mapping references resolve against it.
        stream: The source partition; one durable checkpoint per stream.
        server: The serving MCP server named in provenance; ``connector``
            when omitted.
        tool: The producing operation named in provenance.
        document_type: The manifest resource documents are recorded as.
        media_type: The manifest resource media assets are recorded as.
        strict_schema: Reject fields the manifest mapping does not declare.
        sanitize: Pass record properties through the persistence privacy
            guard (:mod:`agent_connector_sdk.privacy`) before they leave the
            process.
    """

    connector: str
    stream: str
    server: str = ""
    tool: str = "knowledge-ingest"
    document_type: str = "Document"
    media_type: str = "MediaAsset"
    strict_schema: bool = False
    sanitize: bool = True

    def __post_init__(self) -> None:
        for name in ("connector", "stream", "tool", "document_type", "media_type"):
            if not str(getattr(self, name)).strip():
                raise ValueError(f"ingest binding {name} is required")

    @property
    def server_name(self) -> str:
        """The server named in provenance."""
        return self.server or self.connector

    @property
    def adapter_kind(self) -> str:
        """Provenance adapter kind for pushed observations."""
        return _ADAPTER_KIND

    def identity_digest(self) -> str:
        """SHA-256 of the canonical binding identity, used as the provenance pin.

        Pushed observations have no pinned MCP tool schema; the digest names the
        exact producer (connector, server, tool, adapter kind) instead.
        """
        identity = {
            "adapter_kind": _ADAPTER_KIND,
            "connector": self.connector,
            "server": self.server_name,
            "tool": self.tool,
        }
        encoded = json.dumps(identity, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class Entity:
    """One typed source record; ``node_type`` is its manifest resource."""

    id: str
    node_type: str
    properties: Mapping[str, Any] = field(default_factory=dict)
    updated_at: str | None = None
    source_uri: str | None = None


@dataclass(frozen=True)
class Document:
    """A text record for semantic search; epistemic-graph enriches it."""

    id: str
    text: str
    title: str | None = None
    source_uri: str | None = None
    properties: Mapping[str, Any] = field(default_factory=dict)
    updated_at: str | None = None


@dataclass(frozen=True)
class MediaAsset:
    """Binary content stored in epistemic-graph Blob CAS plus its asset record.

    ``id`` defaults to ``blob:<digest>`` once the bytes are stored.
    """

    data: bytes
    mime_type: str
    id: str | None = None
    name: str = ""
    properties: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class EntityRef:
    """A relationship endpoint; ``node_type`` is needed only for the source."""

    id: str
    node_type: str | None = None
    stream: str | None = None


@dataclass(frozen=True)
class Relationship:
    """A declared manifest relation from ``source`` to ``target``."""

    source: str | EntityRef
    target: str | EntityRef
    relationship: str
    properties: Mapping[str, Any] | None = None


@dataclass(frozen=True)
class Withdrawal:
    """A provider-declared removal of a previously ingested record."""

    id: str
    reason: str


@dataclass(frozen=True)
class ChangeSet:
    """One atomic submission for a binding's stream.

    ``mode`` is ``DELTA`` for pushed observations. ``RECONCILE`` requires the
    complete ``live_ids`` snapshot; an empty snapshot also needs
    ``empty_approval``. ``FULL`` never deletes.
    """

    entities: tuple[Entity, ...] = ()
    documents: tuple[Document, ...] = ()
    relationships: tuple[Relationship, ...] = ()
    media: tuple[MediaAsset, ...] = ()
    withdrawals: tuple[Withdrawal, ...] = ()
    mode: SourceIngestionMode = SourceIngestionMode.DELTA
    live_ids: tuple[str, ...] | None = None
    empty_approval: str | None = None

    def __post_init__(self) -> None:
        if self.mode is SourceIngestionMode.RECONCILE and self.live_ids is None:
            raise ValueError("a reconcile change set needs its complete live_ids")
        if self.mode is not SourceIngestionMode.RECONCILE and self.live_ids:
            raise ValueError("live_ids apply only to a reconcile change set")
