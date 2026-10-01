"""Map a typed change set to one generated ``SourceIngestionRequest``.

Pure: no I/O. The previous checkpoint comes from epistemic-graph's durable
``SourceIngestStatus``; the next one advances its sequence and names the batch
content, so every submission differs from the checkpoint it replaces.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable, Mapping
from typing import Any
from urllib.parse import quote

from epistemic_graph.generated.source_ingestion import (
    SourceCheckpoint,
    SourceEntityRef,
    SourceIngestionMode,
    SourceIngestionRequest,
    SourceRecord,
    SourceRecordProvenance,
    SourceRelationship,
    SourceWithdrawal,
)
from pydantic import JsonValue, TypeAdapter, ValidationError

from agent_connector_sdk.ingest.errors import IngestError
from agent_connector_sdk.ingest.model import (
    ChangeSet,
    Entity,
    EntityRef,
    IngestBinding,
    Relationship,
)
from agent_connector_sdk.ingest.records import document_entity
from agent_connector_sdk.privacy import PersistencePrivacyGuard

__all__ = ["build_request"]

_JSON_OBJECT = TypeAdapter(dict[str, JsonValue])


def _json_object(
    value: Mapping[str, Any], *, what: str, guard: PersistencePrivacyGuard | None
) -> dict[str, JsonValue]:
    present = {key: item for key, item in value.items() if item is not None}
    if guard is not None:
        present, _ = guard.sanitize(present)
    try:
        return _JSON_OBJECT.validate_python(present)
    except ValidationError as exc:
        raise IngestError(f"{what} is not JSON data") from exc


def _uri(binding: IngestBinding, *parts: str) -> str:
    path = "/".join(quote(part, safe="") for part in parts)
    return f"connector://{quote(binding.connector, safe='')}/{path}"


def _provenance(binding: IngestBinding, source_uri: str) -> SourceRecordProvenance:
    return SourceRecordProvenance(
        connector=binding.connector,
        adapter_kind=binding.adapter_kind,
        server=binding.server_name,
        tool=binding.tool,
        tool_schema_sha256=binding.identity_digest(),
        source_uri=source_uri,
    )


def _record(
    binding: IngestBinding, entity: Entity, guard: PersistencePrivacyGuard | None
) -> SourceRecord:
    if not entity.id or not entity.node_type:
        raise IngestError("every entity needs an id and a node_type")
    uri = entity.source_uri or _uri(binding, binding.stream, entity.id)
    return SourceRecord(
        stream=binding.stream,
        record_id=entity.id,
        mapping_reference=(
            f"manifest:{binding.connector}#schema_mappings/{entity.node_type}"
        ),
        payload=_json_object(
            entity.properties, what=f"entity {entity.id!r}", guard=guard
        ),
        updated_at=entity.updated_at,
        provenance=_provenance(binding, uri),
    )


def _endpoint(
    binding: IngestBinding, value: str | EntityRef, types: Mapping[str, str]
) -> tuple[SourceEntityRef, str | None]:
    ref = value if isinstance(value, EntityRef) else EntityRef(value)
    node_type = ref.node_type or types.get(ref.id)
    return SourceEntityRef(stream=ref.stream or binding.stream, record_id=ref.id), (
        node_type
    )


def _relationship(
    binding: IngestBinding,
    relationship: Relationship,
    *,
    types: Mapping[str, str],
    guard: PersistencePrivacyGuard | None,
) -> SourceRelationship:
    source, source_type = _endpoint(binding, relationship.source, types)
    target, _ = _endpoint(binding, relationship.target, types)
    if not source_type:
        raise IngestError(
            f"relationship source {source.record_id!r} has no node_type; "
            "pass an EntityRef or include the source in the change set"
        )
    uri = _uri(
        binding,
        source.stream,
        source.record_id,
        relationship.relationship,
        target.record_id,
    )
    properties = relationship.properties
    return SourceRelationship(
        source=source,
        target=target,
        relation_reference=(
            f"manifest:{binding.connector}#resources/{source_type}"
            f"/relations/{relationship.relationship}"
        ),
        properties=(
            None
            if properties is None
            else _json_object(properties, what="relationship properties", guard=guard)
        ),
        provenance=_provenance(binding, uri),
    )


def _checkpoint(
    binding: IngestBinding,
    previous: SourceCheckpoint | None,
    content: Iterable[Any],
) -> SourceCheckpoint:
    position = previous.position if previous is not None else None
    sequence = position.get("sequence") if isinstance(position, dict) else None
    encoded = json.dumps(
        [item.model_dump(mode="json") for item in content],
        sort_keys=True,
        separators=(",", ":"),
    )
    return SourceCheckpoint(
        stream=binding.stream,
        position={
            "sequence": (sequence if isinstance(sequence, int) else 0) + 1,
            "batch": hashlib.sha256(encoded.encode("utf-8")).hexdigest(),
        },
    )


def _live_ids(
    binding: IngestBinding, changes: ChangeSet
) -> list[SourceEntityRef] | None:
    if changes.mode is not SourceIngestionMode.RECONCILE:
        return None
    return [
        SourceEntityRef(stream=binding.stream, record_id=record_id)
        for record_id in changes.live_ids or ()
    ]


def build_request(
    binding: IngestBinding,
    changes: ChangeSet,
    *,
    previous: SourceCheckpoint | None,
    extra_entities: tuple[Entity, ...] = (),
) -> SourceIngestionRequest:
    """The exact generated request for ``changes`` after ``previous``.

    ``extra_entities`` carries records derived outside the change set (stored
    media). Record and relationship properties pass through
    :class:`~agent_connector_sdk.privacy.PersistencePrivacyGuard` unless the
    binding sets ``sanitize=False``; identifiers are never rewritten. Raises :class:`IngestError` for anything epistemic-graph would
    refuse structurally: missing identity, non-JSON data, an untyped
    relationship source, or a batch over the contract's bounds.
    """
    entities = (
        *changes.entities,
        *(document_entity(binding, item) for item in changes.documents),
        *extra_entities,
    )
    types = {entity.id: entity.node_type for entity in entities}
    guard = PersistencePrivacyGuard() if binding.sanitize else None
    try:
        records = [_record(binding, entity, guard) for entity in entities]
        relationships = [
            _relationship(binding, item, types=types, guard=guard)
            for item in changes.relationships
        ]
        return SourceIngestionRequest(
            connector=binding.connector,
            mode=changes.mode,
            strict_schema=binding.strict_schema,
            records=records,
            relationships=relationships,
            provider_checkpoint=_checkpoint(
                binding, previous, (*records, *relationships)
            ),
            expected_previous_checkpoint=previous,
            authoritative_live_ids=_live_ids(binding, changes),
            empty_authoritative_approval=changes.empty_approval,
            withdrawals=[
                SourceWithdrawal(
                    entity=SourceEntityRef(stream=binding.stream, record_id=item.id),
                    reason=item.reason,
                )
                for item in changes.withdrawals
            ],
        )
    except ValidationError as exc:
        raise IngestError("change set violates the SourceIngest contract") from exc
