"""Apache Egeria open-metadata vendor extractor (SCION-SOURCE-INGEST-R006.30).

Ported from ``agent_utilities.knowledge_graph.enrichment.extractors.egeria``
onto this SDK's typed :mod:`~agent_connector_sdk.vendor_extractors.contract`:
Egeria's open-metadata/glossary/governance/lineage records map to the
canonical ArchiMate concepts so Egeria data reconciles with the
ServiceNow/ERPNext/Camunda/infra crosswalk by GUID:

    asset (DataStore/Database/FileFolder) -> ``DataConnector``  egeria_asset:{guid}
    asset (DataSet/Table/DataFile)        -> ``DataObject``     egeria_asset:{guid}  (PART_OF store)
    glossary term                         -> ``Concept``        egeria_term:{guid}
    glossary category                     -> ``GlossaryCategory`` egeria_category:{guid}
    governance policy / rule              -> ``Policy``         egeria_policy:{guid}
    governance principle                  -> ``Principle``      egeria_policy:{guid}
    governance strategy / imperative      -> ``Goal``           egeria_policy:{guid}
    software server / host                -> ``Server``         egeria_server:{guid}
    connection                            -> ``DataConnector``  egeria_connection:{guid}
    lineage process                       -> ``ProcessModel``   egeria_process:{guid}

Lineage ``DataFlow`` records become ``flowsTo``/``derivesFrom`` relationships
-- the unique payload Egeria contributes that the KG does not model natively.
Every entity carries ``externalToolId`` (the Egeria GUID) and
``domain="egeria"``. The client is injected (duck-typed) via
``config["client"]``; this module performs no network calls itself.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from agent_connector_sdk.ingest import ChangeSet, Entity, Relationship
from agent_connector_sdk.vendor_extractors._records import _as_list, _first, _get
from agent_connector_sdk.vendor_extractors.contract import register_vendor_extractor
from agent_connector_sdk.vendor_extractors.egeria_helpers import (
    _asset_type,
    _call,
    _classification_props,
    _flow_rel,
    _gov_type,
    _kg_type,
)

CATEGORY = "egeria"

_GUID_KEYS = ("guid", "GUID", "id")


@dataclass
class _State:
    entities: list[Entity] = field(default_factory=list)
    relationships: list[Relationship] = field(default_factory=list)
    seen: set[str] = field(default_factory=set)


def _base_props(record: Any) -> dict[str, Any]:
    return {
        "domain": "egeria",
        "externalToolId": _first(record, *_GUID_KEYS),
        "qualifiedName": _first(record, "qualifiedName", "qualified_name"),
    }


def _add(
    state: _State, node_id: str, node_type: str, *, properties: dict[str, Any]
) -> None:
    if node_id in state.seen:
        return
    state.seen.add(node_id)
    state.entities.append(
        Entity(id=node_id, node_type=node_type, properties=properties)
    )


def _rel(state: _State, source: str, target: str, *, relationship: str) -> None:
    state.relationships.append(
        Relationship(source=source, target=target, relationship=relationship)
    )


def _asset(state: _State, record: Any, guid: Any) -> None:
    node_id = f"egeria_asset:{guid}"
    node_type, role = _asset_type(record)
    properties = {
        **_base_props(record),
        "name": _first(record, "displayName", "name", "qualifiedName"),
        **_classification_props(record),
    }
    _add(state, node_id, node_type, properties=properties)
    host = _first(record, "hostGuid", "serverGuid", "hostedOnGuid")
    if role == "store" and host:
        _rel(state, node_id, f"egeria_server:{host}", relationship="HOSTED_ON")
    parent = _first(record, "storeGuid", "parentGuid", "assetGuid")
    if role == "object" and parent:
        _rel(state, node_id, f"egeria_asset:{parent}", relationship="PART_OF")
    for policy in _as_list(_first(record, "governedByGuids", "policyGuids")):
        _rel(state, node_id, f"egeria_policy:{policy}", relationship="governedBy")


def _name(*keys: str) -> Any:
    return lambda record: {"name": _first(record, *keys)}


# (client method, id prefix, type resolver, extra props, link keys, link prefix, link rel)
_SIMPLE: tuple[tuple[Any, ...], ...] = (
    (
        "list_glossary_categories",
        "egeria_category",
        lambda r: "GlossaryCategory",
        _name("displayName", "name"),
        ("parentCategoryGuid", "parentGuid"),
        "egeria_category",
        "PART_OF",
    ),
    (
        "list_glossary_terms",
        "egeria_term",
        lambda r: "Concept",
        lambda r: {
            "name": _first(r, "displayName", "name"),
            "summary": _first(r, "summary", "description"),
        },
        ("categoryGuid", "category"),
        "egeria_category",
        "IN_CATEGORY",
    ),
    (
        "list_governance_definitions",
        "egeria_policy",
        _gov_type,
        lambda r: {
            "name": _first(r, "title", "displayName", "name"),
            "governanceDomain": _first(r, "domain", "domainIdentifier"),
        },
        (),
        "",
        "",
    ),
    (
        "list_software_servers",
        "egeria_server",
        lambda r: "Server",
        _name("displayName", "name", "hostName"),
        (),
        "",
        "",
    ),
    (
        "list_connections",
        "egeria_connection",
        lambda r: "DataConnector",
        _name("displayName", "name"),
        ("assetGuid", "connectsToGuid"),
        "egeria_asset",
        "CONNECTS_TO",
    ),
)


def _simple(state: _State, client: Any, spec: tuple[Any, ...]) -> None:
    method, prefix, type_of, props_of, link_keys, link_prefix, link_rel = spec
    for record in _call(client, method):
        guid = _first(record, *_GUID_KEYS)
        if not guid:
            continue
        node_id = f"{prefix}:{guid}"
        _add(
            state,
            node_id,
            type_of(record),
            properties={**_base_props(record), **props_of(record)},
        )
        target = _first(record, *link_keys) if link_keys else None
        if target:
            _rel(state, node_id, f"{link_prefix}:{target}", relationship=link_rel)


def _flow_process(state: _State, record: Any, ends: tuple[Any, Any, Any]) -> None:
    process, source, target = ends
    process_id = f"egeria_process:{process}"
    _add(
        state,
        process_id,
        "ProcessModel",
        properties={
            "domain": "egeria",
            "externalToolId": process,
            "name": _first(record, "processName", "name"),
        },
    )
    if source:
        _rel(state, f"egeria_asset:{source}", process_id, relationship="flowsTo")
    if target:
        _rel(state, process_id, f"egeria_asset:{target}", relationship="derivesFrom")


def _flow_edge(state: _State, record: Any, ends: tuple[Any, Any]) -> None:
    source, target = ends
    for guid, name_key, type_key in (
        (source, "sourceName", "sourceType"),
        (target, "targetName", "targetType"),
    ):
        _add(
            state,
            f"egeria_asset:{guid}",
            _kg_type(_first(record, type_key)),
            properties={
                "domain": "egeria",
                "externalToolId": guid,
                "name": _first(record, name_key) or guid,
            },
        )
    _rel(
        state,
        f"egeria_asset:{source}",
        f"egeria_asset:{target}",
        relationship=_flow_rel(_first(record, "label")),
    )


def _flow(state: _State, record: Any) -> None:
    process = _first(record, "processGuid", "process", "transformationGuid")
    source = _first(record, "sourceGuid", "source", "fromGuid")
    target = _first(record, "targetGuid", "target", "toGuid")
    if process:
        _flow_process(state, record, (process, source, target))
    elif source and target:
        _flow_edge(state, record, (source, target))


def extract(config: Any) -> ChangeSet:
    """Extract Egeria open-metadata artifacts into a uniform ``ChangeSet``."""
    client = _get(config, "client")
    if client is None:
        return ChangeSet()
    state = _State()
    for record in _call(client, "list_assets"):
        guid = _first(record, *_GUID_KEYS)
        if guid:
            _asset(state, record, guid)
    for spec in _SIMPLE:
        _simple(state, client, spec)
    for record in _call(client, "list_data_flows"):
        _flow(state, record)
    return ChangeSet(
        entities=tuple(state.entities), relationships=tuple(state.relationships)
    )


register_vendor_extractor(
    CATEGORY,
    extract,
    description="Apache Egeria open metadata / glossary / governance / lineage -> KG",
)
