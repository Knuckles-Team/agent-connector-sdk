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


def _risk_props(record: Any) -> dict[str, Any]:
    """Lifecycle/risk attributes (vendor-neutral TRM props), field-tolerant."""
    out: dict[str, Any] = {}
    stage = _first(
        record, "lifecycle_stage", "lifecycle", "install_status", "life_cycle_stage"
    )
    if stage:
        out["lifecycleStage"] = stage
    eol = _first(
        record, "end_of_life", "eol_date", "end_of_support", "decommission_date"
    )
    if eol:
        out["endOfLifeDate"] = eol
    rating = _first(record, "risk_rating", "risk", "risk_score")
    if rating:
        out["riskRating"] = rating
    return out


def extract(config: Any) -> ChangeSet:
    """Extract ServiceNow ITSM + CMDB + TRM into a uniform ``ChangeSet``."""
    client = _get(config, "client")
    if client is None:
        return ChangeSet()

    entities: list[Entity] = []
    relationships: list[Relationship] = []

    def _emit_risk_entity(owner_id: str, record: Any, risk: dict[str, Any]) -> None:
        """A TechnologyRisk entity + HAS_RISK relationship on risk/EOL signal."""
        if not (risk.get("riskRating") or risk.get("endOfLifeDate")):
            return
        risk_id = f"snrisk:{owner_id}"
        entities.append(
            Entity(
                id=risk_id,
                node_type="TechnologyRisk",
                properties=_federation(
                    owner_id,
                    name=f"Risk: {_get(record, 'name') or owner_id}",
                    **risk,
                ),
            )
        )
        relationships.append(
            Relationship(source=owner_id, target=risk_id, relationship="HAS_RISK")
        )

    for method, label, prefix in (
        ("incidents", "Incident", "incident"),
        ("changes", "Change", "change"),
    ):
        for record in _call(client, method):
            key = _key(record)
            if not key:
                continue
            node_id = f"{prefix}:{key}"
            entities.append(
                Entity(
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
            )
            ci = _ref(_get(record, "cmdb_ci"))
            if ci:
                relationships.append(
                    Relationship(
                        source=node_id, target=f"ci:{ci}", relationship="AFFECTS"
                    )
                )
            assignee = _ref(_get(record, "assigned_to"))
            if assignee:
                relationships.append(
                    Relationship(
                        source=node_id,
                        target=f"person:{assignee}",
                        relationship="ASSIGNED_TO",
                    )
                )

    for record in _call(client, "cmdb_cis"):
        key = _key(record)
        if not key:
            continue
        node_id = f"ci:{key}"
        risk = _risk_props(record)
        entities.append(
            Entity(
                id=node_id,
                node_type="ConfigurationItem",
                properties=_federation(
                    key,
                    name=_get(record, "name"),
                    short_description=_get(record, "short_description"),
                    ci_class=_ref(_get(record, "ci_class")),
                    state=_ref(_get(record, "state")),
                    **risk,
                ),
            )
        )
        _emit_risk_entity(node_id, record, risk)
        model = _first(record, "model_id", "model")
        if model:
            relationships.append(
                Relationship(
                    source=node_id,
                    target=f"snproduct:{model}",
                    relationship="INSTANCE_OF",
                )
            )

    for record in _call(client, "cmdb_models"):
        key = _key(record)
        if not key:
            continue
        node_id = f"snproduct:{key}"
        risk = _risk_props(record)
        entities.append(
            Entity(
                id=node_id,
                node_type="TechnologyProduct",
                properties=_federation(
                    key,
                    name=_first(record, "display_name", "name"),
                    manufacturer=_first(record, "manufacturer", "vendor"),
                    **risk,
                ),
            )
        )
        _emit_risk_entity(node_id, record, risk)

    for record in _call(client, "assets"):
        key = _key(record)
        if not key:
            continue
        node_id = f"asset:{key}"
        risk = _risk_props(record)
        entities.append(
            Entity(
                id=node_id,
                node_type="AssetInstance",
                properties=_federation(
                    key,
                    name=_first(record, "display_name", "name", "asset_tag"),
                    **risk,
                ),
            )
        )
        _emit_risk_entity(node_id, record, risk)
        model = _first(record, "model", "model_id", "model_category")
        if model:
            relationships.append(
                Relationship(
                    source=node_id,
                    target=f"snproduct:{model}",
                    relationship="INSTANCE_OF",
                )
            )

    return ChangeSet(entities=tuple(entities), relationships=tuple(relationships))


register_vendor_extractor(
    CATEGORY,
    extract,
    description="ServiceNow ITSM + CMDB + Technology Reference Model -> KG",
)
