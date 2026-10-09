"""LeanIX Enterprise Architecture vendor extractor (SDK-SOURCE-INGEST-R006.24).

Ported from ``agent_utilities.knowledge_graph.enrichment.extractors.leanix``
onto this SDK's typed :mod:`~agent_connector_sdk.vendor_extractors.contract``:
mirrors the LeanIX fact-sheet graph via a well-known core EA type/relation
vocabulary. The LeanIX client is injected via ``config.client`` (duck-typed);
this module performs no network I/O.

Scope note: the agent-utilities source additionally *discovers* the type and
relation vocabulary from the live LeanIX metamodel (reusing
``agent_utilities.ontology.leanix_metamodel``, an agent-utilities-internal
compiler this SDK does not depend on) and falls back to the same core types
below when that discovery is unavailable. This port always uses that core
vocabulary; live-metamodel discovery is not carried over.

Mapping (LeanIX fact sheet -> Entity)::

    <FactSheetType>  ->  node_type == <FactSheetType>, id = <prefix>:<leanix id>

Every entity carries ``externalToolId`` (the LeanIX id) and ``domain="leanix"``.
Relationships are derived from every ``rel*`` field, typed from the known
relation map.

Contract: ``extract(config) -> ChangeSet`` where ``config.client`` exposes
``factsheets(type=..., since=..., ids=...)``. ``config.since``/``config.ids``
(optional) narrow the fetch for delta sync.
"""

from __future__ import annotations

from typing import Any

from agent_connector_sdk.ingest import ChangeSet, Entity, Relationship
from agent_connector_sdk.vendor_extractors.contract import register_vendor_extractor

CATEGORY = "leanix"

# The well-known core EA types (label, id-prefix) and their canonical
# relations (relationship type, target type).
_TYPE_MAP: dict[str, tuple[str, str]] = {
    "Application": ("Application", "app"),
    "ITComponent": ("ITComponent", "itcomponent"),
    "BusinessCapability": ("BusinessCapability", "capability"),
    "DataObject": ("DataObject", "dataobject"),
}
_RELATION_MAP: dict[str, tuple[str, str]] = {
    "relApplicationToBusinessCapability": ("SUPPORTS", "BusinessCapability"),
    "relApplicationToITComponent": ("DEPENDS_ON", "ITComponent"),
}


def _iter_related_targets(value: Any) -> list[tuple[str, str | None]]:
    """Pull ``(target_id, target_type)`` pairs from a tolerant relation field.

    Accepts a bare id, a dict (``factSheetId``/``id``/``factSheet{id,type}``/
    ``target{...}``), a list of any of those, or LeanIX-style
    ``{"edges":[{"node":{"factSheet":{...}}}]}``.
    """
    out: list[tuple[str, str | None]] = []

    def _one(item: Any) -> None:
        if item is None:
            return
        if isinstance(item, str):
            if item:
                out.append((item, None))
            return
        if isinstance(item, dict):
            edges = item.get("edges")
            if isinstance(edges, list):
                for edge in edges:
                    _one(edge)
                return
            if "node" in item:
                _one(item["node"])
                return
            fact_sheet = item.get("factSheet")
            if isinstance(fact_sheet, dict):
                fid = fact_sheet.get("id")
                if fid:
                    out.append((str(fid), fact_sheet.get("type")))
                return
            target = item.get("target")
            if isinstance(target, dict):
                _one(target)
                return
            for key in ("factSheetId", "id", "targetId"):
                val = item.get(key)
                if isinstance(val, str) and val:
                    out.append((val, item.get("type")))
                    return
            return
        if isinstance(item, list | tuple):
            for sub in item:
                _one(sub)

    _one(value)
    seen: set[str] = set()
    deduped: list[tuple[str, str | None]] = []
    for target_id, target_type in out:
        if target_id not in seen:
            seen.add(target_id)
            deduped.append((target_id, target_type))
    return deduped


def _collect_factsheets(
    client: Any, fs_types: list[str], since: str | None, ids: list[str] | None
) -> list[dict[str, Any]]:
    """Fetch fact sheets per type from the injected client, tolerantly."""
    sheets: list[dict[str, Any]] = []
    factsheets = getattr(client, "factsheets", None)
    if not callable(factsheets):
        return sheets
    try:
        for fs_type in fs_types:
            result = factsheets(type=fs_type, since=since, ids=ids)
            for item in result or []:
                if isinstance(item, dict):
                    item.setdefault("type", fs_type)
                    sheets.append(item)
        return sheets
    except TypeError:
        result = factsheets()
        return [item for item in (result or []) if isinstance(item, dict)]


def extract(config: Any) -> ChangeSet:
    """Extract the LeanIX EA fact-sheet graph into a uniform ``ChangeSet``."""
    client = getattr(config, "client", None)
    if client is None and isinstance(config, dict):
        client = config.get("client")
    if client is None:
        return ChangeSet()

    since = (
        getattr(config, "since", None)
        if not isinstance(config, dict)
        else config.get("since")
    )
    ids = (
        getattr(config, "ids", None)
        if not isinstance(config, dict)
        else config.get("ids")
    )

    entities: list[Entity] = []
    relationships: list[Relationship] = []

    def _node_id(fs_type: str, raw_id: str) -> str:
        prefix = _TYPE_MAP.get(fs_type, (fs_type, fs_type.lower()))[1]
        return f"{prefix}:{raw_id}"

    seen_entities: set[str] = set()
    for fact_sheet in _collect_factsheets(client, list(_TYPE_MAP), since, ids):
        raw_id = fact_sheet.get("id")
        fs_type = fact_sheet.get("type")
        if not raw_id or fs_type not in _TYPE_MAP:
            continue
        label = _TYPE_MAP[fs_type][0]
        node_id = _node_id(fs_type, raw_id)
        if node_id not in seen_entities:
            seen_entities.add(node_id)
            properties: dict[str, Any] = {
                "name": fact_sheet.get("name"),
                "externalToolId": raw_id,
                "domain": "leanix",
            }
            if fact_sheet.get("updatedAt"):
                properties["updatedAt"] = fact_sheet["updatedAt"]
            entities.append(Entity(id=node_id, node_type=label, properties=properties))

        for key, value in fact_sheet.items():
            if not isinstance(key, str) or not key.startswith("rel"):
                continue
            mapped = _RELATION_MAP.get(key)
            relationship_type = mapped[0] if mapped else key
            default_target_type = mapped[1] if mapped else None
            for target_id, target_type in _iter_related_targets(value):
                resolved_type = target_type or default_target_type
                if not resolved_type:
                    continue
                relationships.append(
                    Relationship(
                        source=node_id,
                        target=_node_id(resolved_type, target_id),
                        relationship=relationship_type,
                    )
                )

    return ChangeSet(entities=tuple(entities), relationships=tuple(relationships))


register_vendor_extractor(CATEGORY, extract, description="LeanIX EA factsheets -> KG")
