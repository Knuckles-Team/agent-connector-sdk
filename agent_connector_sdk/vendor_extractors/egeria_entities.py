"""Record-to-entity builders for the Egeria vendor extractor.

Split out of :mod:`agent_connector_sdk.vendor_extractors.egeria` to keep that
module under the KISS file-size / function-count caps. Not a public module:
imported only by ``egeria.py``, which owns ``extract()`` and registration.
"""

from __future__ import annotations

from typing import Any

from agent_connector_sdk.ingest import Entity, Relationship
from agent_connector_sdk.vendor_extractors.egeria_mappers import (
    _as_list,
    _asset_type,
    _classification_props,
    _first,
    _flow_rel,
    _gov_type,
    _kg_type,
)


class _ChangeSetBuilder:
    """Accumulates entities/relationships while de-duplicating node ids."""

    def __init__(self) -> None:
        self.entities: list[Entity] = []
        self.relationships: list[Relationship] = []
        self._seen: set[str] = set()

    def base_props(self, record: Any) -> dict[str, Any]:
        return {
            "domain": "egeria",
            "externalToolId": _first(record, "guid", "GUID", "id"),
            "qualifiedName": _first(record, "qualifiedName", "qualified_name"),
        }

    def add(self, node_id: str, node_type: str, properties: dict[str, Any]) -> bool:
        if node_id in self._seen:
            return False
        self._seen.add(node_id)
        self.entities.append(
            Entity(id=node_id, node_type=node_type, properties=properties)
        )
        return True


def _add_assets(records: Any, builder: _ChangeSetBuilder) -> None:
    """Add asset records as ``DataConnector``/``DataObject``/other entities."""
    for record in records:
        guid = _first(record, "guid", "GUID", "id")
        if not guid:
            continue
        node_id = f"egeria_asset:{guid}"
        node_type, role = _asset_type(record)
        properties = {
            **builder.base_props(record),
            "name": _first(record, "displayName", "name", "qualifiedName"),
            **_classification_props(record),
        }
        builder.add(node_id, node_type, properties)
        host = _first(record, "hostGuid", "serverGuid", "hostedOnGuid")
        if role == "store" and host:
            builder.relationships.append(
                Relationship(
                    source=node_id,
                    target=f"egeria_server:{host}",
                    relationship="HOSTED_ON",
                )
            )
        parent = _first(record, "storeGuid", "parentGuid", "assetGuid")
        if role == "object" and parent:
            builder.relationships.append(
                Relationship(
                    source=node_id,
                    target=f"egeria_asset:{parent}",
                    relationship="PART_OF",
                )
            )
        for policy in _as_list(_first(record, "governedByGuids", "policyGuids")):
            builder.relationships.append(
                Relationship(
                    source=node_id,
                    target=f"egeria_policy:{policy}",
                    relationship="governedBy",
                )
            )


def _add_single_relation(
    records: Any,
    builder: _ChangeSetBuilder,
    *,
    id_prefix: str,
    node_type: str,
    extra_props_keys: tuple[tuple[str, tuple[str, ...]], ...],
    relation_keys: tuple[str, ...],
    relation_prefix: str,
    relation_type: str,
) -> None:
    """Add records as entities with at most one outgoing relationship each.

    Covers glossary categories (``PART_OF`` parent), glossary terms
    (``IN_CATEGORY``), and connections (``CONNECTS_TO`` an asset): one guid'd
    entity plus zero-or-one relationship driven by a single related-guid field.
    """
    for record in records:
        guid = _first(record, "guid", "GUID", "id")
        if not guid:
            continue
        node_id = f"{id_prefix}:{guid}"
        extra = {key: _first(record, *keys) for key, keys in extra_props_keys}
        builder.add(node_id, node_type, {**builder.base_props(record), **extra})
        related = _first(record, *relation_keys)
        if related:
            builder.relationships.append(
                Relationship(
                    source=node_id,
                    target=f"{relation_prefix}:{related}",
                    relationship=relation_type,
                )
            )


def _add_governance_definitions(records: Any, builder: _ChangeSetBuilder) -> None:
    """Add governance-definition records as Policy/Principle/Goal entities."""
    for record in records:
        guid = _first(record, "guid", "GUID", "id")
        if not guid:
            continue
        builder.add(
            f"egeria_policy:{guid}",
            _gov_type(record),
            {
                **builder.base_props(record),
                "name": _first(record, "title", "displayName", "name"),
                "governanceDomain": _first(record, "domain", "domainIdentifier"),
            },
        )


def _add_software_servers(records: Any, builder: _ChangeSetBuilder) -> None:
    """Add software-server/host records as ``Server`` entities."""
    for record in records:
        guid = _first(record, "guid", "GUID", "id")
        if not guid:
            continue
        builder.add(
            f"egeria_server:{guid}",
            "Server",
            {
                **builder.base_props(record),
                "name": _first(record, "displayName", "name", "hostName"),
            },
        )


def _add_data_flow_with_process(
    record: Any, process: Any, builder: _ChangeSetBuilder
) -> None:
    """Handle a data-flow record that names an explicit transformation process."""
    process_id = f"egeria_process:{process}"
    builder.add(
        process_id,
        "ProcessModel",
        {
            "domain": "egeria",
            "externalToolId": process,
            "name": _first(record, "processName", "name"),
        },
    )
    source = _first(record, "sourceGuid", "source", "fromGuid")
    target = _first(record, "targetGuid", "target", "toGuid")
    if source:
        builder.relationships.append(
            Relationship(
                source=f"egeria_asset:{source}",
                target=process_id,
                relationship="flowsTo",
            )
        )
    if target:
        builder.relationships.append(
            Relationship(
                source=process_id,
                target=f"egeria_asset:{target}",
                relationship="derivesFrom",
            )
        )


def _add_data_flow_direct(record: Any, builder: _ChangeSetBuilder) -> None:
    """Handle a direct source->target data-flow record (no named process)."""
    source = _first(record, "sourceGuid", "source", "fromGuid")
    target = _first(record, "targetGuid", "target", "toGuid")
    if not (source and target):
        return
    for guid, name_key, type_key in (
        (source, "sourceName", "sourceType"),
        (target, "targetName", "targetType"),
    ):
        builder.add(
            f"egeria_asset:{guid}",
            _kg_type(_first(record, type_key)),
            {
                "domain": "egeria",
                "externalToolId": guid,
                "name": _first(record, name_key) or guid,
            },
        )
    builder.relationships.append(
        Relationship(
            source=f"egeria_asset:{source}",
            target=f"egeria_asset:{target}",
            relationship=_flow_rel(_first(record, "label")),
        )
    )


def _add_data_flows(records: Any, builder: _ChangeSetBuilder) -> None:
    """Add lineage ``DataFlow`` records as ``flowsTo``/``derivesFrom`` edges."""
    for record in records:
        process = _first(record, "processGuid", "process", "transformationGuid")
        if process:
            _add_data_flow_with_process(record, process, builder)
        else:
            _add_data_flow_direct(record, builder)
