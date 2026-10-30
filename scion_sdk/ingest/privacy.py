"""Keyed pseudonymous projection applied to a change set before it is submitted.

A :class:`Pseudonymizer` replaces each provider id with a keyed, domain-separated
identifier and drops named properties, so the graph never holds the source id.
Install it as ``SourceStream(projection=pseudonymizer.project)``; the stream's
one ``submit`` path applies it.
"""

from __future__ import annotations

import hashlib
import hmac
from collections.abc import Collection
from dataclasses import dataclass, replace
from typing import Any

from scion_sdk.ingest.errors import IngestError
from scion_sdk.ingest.model import ChangeSet, EntityRef

__all__ = ["Pseudonymizer"]

MIN_KEY_BYTES = 32


@dataclass(frozen=True)
class Pseudonymizer:
    """Keyed opaque ids for one connector.

    Attributes:
        connector: Domain-separates the digest (usually the fleet name).
        prefix: Leading segment of an opaque id (``<prefix>:<type>:<digest>``).
        key: The deployment-owned secret; at least 32 bytes.
        redact: Property names removed from every entity and relationship.
    """

    connector: str
    prefix: str
    key: bytes
    redact: frozenset[str] = frozenset()

    def __post_init__(self) -> None:
        if len(self.key) < MIN_KEY_BYTES:
            raise IngestError(
                f"{self.connector} ingestion needs a pseudonymization key of "
                f"at least {MIN_KEY_BYTES} bytes"
            )

    @classmethod
    def from_setting(
        cls,
        connector: str,
        prefix: str,
        setting_name: str,
        *,
        redact: Collection[str] = (),
    ) -> Pseudonymizer:
        """Read the key from the connector setting ``setting_name``."""
        from scion_sdk.config import setting

        key = str(setting(setting_name, "") or "").encode()
        return cls(connector, prefix, key, frozenset(redact))

    def opaque_id(self, node_type: str, provider_id: Any) -> str:
        """The keyed identifier of ``provider_id`` as a ``node_type``."""
        if provider_id in (None, ""):
            raise IngestError(f"{self.connector} record has no identifier")
        digest = hmac.new(
            self.key,
            f"{self.connector}\x00{node_type}\x00{provider_id}".encode(),
            hashlib.sha256,
        ).hexdigest()
        return f"{self.prefix}:{node_type}:{digest}"

    def project(self, changes: ChangeSet) -> ChangeSet:
        """``changes`` with opaque ids and redacted properties.

        Relationship endpoints that name a record of the same change set are
        rewritten to its opaque id; any other endpoint is left as given.
        """
        renamed: dict[str, str] = {}
        entities = []
        for entity in changes.entities:
            new_id = self.opaque_id(entity.node_type, entity.id)
            renamed[entity.id] = new_id
            entities.append(
                replace(entity, id=new_id, properties=self._clean(entity.properties))
            )
        documents = []
        for document in changes.documents:
            new_id = self.opaque_id("Document", document.id)
            renamed[document.id] = new_id
            documents.append(
                replace(
                    document, id=new_id, properties=self._clean(document.properties)
                )
            )

        def endpoint(value: str | EntityRef) -> str | EntityRef:
            if isinstance(value, EntityRef):
                return replace(value, id=renamed.get(value.id, value.id))
            return renamed.get(value, value)

        relationships = tuple(
            replace(
                edge,
                source=endpoint(edge.source),
                target=endpoint(edge.target),
                properties=self._clean(edge.properties) or None
                if edge.properties
                else None,
            )
            for edge in changes.relationships
        )
        return replace(
            changes,
            entities=tuple(entities),
            documents=tuple(documents),
            relationships=relationships,
        )

    def _clean(self, properties: Any) -> dict[str, Any]:
        return {k: v for k, v in dict(properties or {}).items() if k not in self.redact}
