"""ServiceNow ITSM + CMDB + TRM vendor extractor (SDK-SOURCE-INGEST-R006.26).

Ported from
``agent_utilities.knowledge_graph.enrichment.extractors.servicenow`` onto
this SDK's typed :mod:`~agent_connector_sdk.vendor_extractors.contract`:

* ITSM -- ``incident``/``change_request`` -> ``Incident``/``Change``
  (``AFFECTS`` a CI, ``ASSIGNED_TO`` a person).
* CMDB inventory -- ``cmdb_ci_*`` -> ``ConfigurationItem`` (an
  ``AssetInstance``).
* Technology Reference Model -- ``cmdb_model`` -> ``TechnologyProduct``;
  ``alm_hardware``/``alm_asset`` -> ``AssetInstance`` (``INSTANCE_OF`` its
  product), with lifecycle/risk attributes and a ``TechnologyRisk`` entity
  (``HAS_RISK``) when a record carries risk/EOL signal.

Every entity carries ``externalToolId`` (sys_id) + ``domain="servicenow"``.
The client is injected; this module performs no network I/O itself.
"""

from __future__ import annotations

from typing import Any

from agent_connector_sdk.ingest import ChangeSet, Entity, Relationship
from agent_connector_sdk.vendor_extractors.contract import register_vendor_extractor

CATEGORY = "servicenow"
_DOMAIN = "servicenow"


def _get(record: Any, key: str, default: Any = None) -> Any:
    if isinstance(record, dict):
        return record.get(key, default)
    return getattr(record, key, default)


def _ref(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, dict):
        value = value.get("value") or value.get("display_value")
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _first(record: Any, *keys: str) -> str | None:
    for key in keys:
        value = _ref(_get(record, key))
        if value:
            return value
    return None


def _key(record: Any) -> str | None:
    return _ref(_get(record, "sys_id")) or _ref(_get(record, "number"))


def _call(client: Any, name: str) -> list[Any]:
    method = getattr(client, name, None)
    if not callable(method):
        return []
    result = method()
    return list(result) if result else []


def _federation(raw_id: str, **extra: Any) -> dict[str, Any]:
    properties: dict[str, Any] = {"externalToolId": raw_id, "domain": _DOMAIN}
    properties.update({key: value for key, value in extra.items() if value is not None})
    return properties


_RISK_FIELDS = (
    (
        "lifecycleStage",
        ("lifecycle_stage", "lifecycle", "install_status", "life_cycle_stage"),
    ),
    (
        "endOfLifeDate",
        ("end_of_life", "eol_date", "end_of_support", "decommission_date"),
    ),
    ("riskRating", ("risk_rating", "risk", "risk_score")),
)


def _itsm_record(
    label: str, prefix: str, record: Any
) -> tuple[Entity, list[Relationship]] | None:
    key = _key(record)
    if not key:
        return None
    node_id = f"{prefix}:{key}"
    entity = Entity(
        id=node_id,
        node_type=label,
        properties=_federation(
            key,
            number=_ref(_get(record, "number")),
            short_description=_get(record, "short_description"),
            state=_ref(_get(record, "state")),
            priority=_ref(_get(record, "priority")),
        ),
    )
    relationships: list[Relationship] = []
    ci = _ref(_get(record, "cmdb_ci"))
    if ci:
        relationships.append(
            Relationship(source=node_id, target=f"ci:{ci}", relationship="AFFECTS")
        )
    assignee = _ref(_get(record, "assigned_to"))
    if assignee:
        relationships.append(
            Relationship(
                source=node_id, target=f"person:{assignee}", relationship="ASSIGNED_TO"
            )
        )
    return entity, relationships


def _trm_properties(node_type: str, record: Any) -> dict[str, Any]:
    """Type-specific display properties for one TRM record, before risk props."""
    if node_type == "ConfigurationItem":
        return {
            "name": _get(record, "name"),
            "short_description": _get(record, "short_description"),
            "ci_class": _ref(_get(record, "ci_class")),
            "state": _ref(_get(record, "state")),
        }
    if node_type == "TechnologyProduct":
        return {
            "name": _first(record, "display_name", "name"),
            "manufacturer": _first(record, "manufacturer", "vendor"),
        }
    return {"name": _first(record, "display_name", "name", "asset_tag")}


def _trm_record(
    record: Any, *, prefix: str, node_type: str, model_keys: tuple[str, ...]
) -> tuple[list[Entity], list[Relationship]] | None:
    """A CMDB/TRM record (CI, product, or asset instance) -- all share the same
    key/risk/INSTANCE_OF shape, differing only in prefix, label, and which
    fields become display properties."""
    key = _key(record)
    if not key:
        return None
    node_id = f"{prefix}:{key}"
    risk = {
        name: value for name, keys in _RISK_FIELDS if (value := _first(record, *keys))
    }
    entities = [
        Entity(
            id=node_id,
            node_type=node_type,
            properties=_federation(key, **_trm_properties(node_type, record), **risk),
        )
    ]
    relationships: list[Relationship] = []
    if risk.get("riskRating") or risk.get("endOfLifeDate"):
        risk_id = f"snrisk:{node_id}"
        entities.append(
            Entity(
                id=risk_id,
                node_type="TechnologyRisk",
                properties=_federation(
                    node_id, name=f"Risk: {_get(record, 'name') or node_id}", **risk
                ),
            )
        )
        relationships.append(
            Relationship(source=node_id, target=risk_id, relationship="HAS_RISK")
        )
    model = _first(record, *model_keys) if model_keys else None
    if model:
        relationships.append(
            Relationship(
                source=node_id, target=f"snproduct:{model}", relationship="INSTANCE_OF"
            )
        )
    return entities, relationships


_TRM_GROUPS = (
    ("cmdb_cis", "ci", "ConfigurationItem", ("model_id", "model")),
    ("cmdb_models", "snproduct", "TechnologyProduct", ()),
    ("assets", "asset", "AssetInstance", ("model", "model_id", "model_category")),
)


def extract(config: Any) -> ChangeSet:
    """Extract ServiceNow ITSM + CMDB + TRM into a uniform ``ChangeSet``."""
    client = _get(config, "client")
    if client is None:
        return ChangeSet()

    entities: list[Entity] = []
    relationships: list[Relationship] = []
    for method, label, prefix in (
        ("incidents", "Incident", "incident"),
        ("changes", "Change", "change"),
    ):
        for record in _call(client, method):
            built = _itsm_record(label, prefix, record)
            if built is None:
                continue
            entity, rels = built
            entities.append(entity)
            relationships.extend(rels)

    for method, prefix, node_type, model_keys in _TRM_GROUPS:
        for record in _call(client, method):
            built = _trm_record(
                record, prefix=prefix, node_type=node_type, model_keys=model_keys
            )
            if built is None:
                continue
            built_entities, built_relationships = built
            entities.extend(built_entities)
            relationships.extend(built_relationships)

    return ChangeSet(entities=tuple(entities), relationships=tuple(relationships))


register_vendor_extractor(
    CATEGORY,
    extract,
    description="ServiceNow ITSM + CMDB + Technology Reference Model -> KG",
)
