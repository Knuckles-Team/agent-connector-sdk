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
from agent_connector_sdk.vendor_extractors.servicenow_helpers import (
    _asset_properties,
    _ci_properties,
    _federation,
    _first,
    _get,
    _key,
    _model_properties,
    _ref,
    _rel,
    _risk_entities,
    _risk_props,
)

CATEGORY = "servicenow"
_DOMAIN = "servicenow"


def _call(client: Any, name: str) -> list[Any]:
    method = getattr(client, name, None)
    if not callable(method):
        return []
    result = method()
    return list(result) if result else []


def _itsm(client: Any) -> tuple[list[Entity], list[Relationship]]:
    entities: list[Entity] = []
    relationships: list[Relationship] = []
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
                relationships.append(_rel(node_id, f"ci:{ci}", "AFFECTS"))
            assignee = _ref(_get(record, "assigned_to"))
            if assignee:
                relationships.append(_rel(node_id, f"person:{assignee}", "ASSIGNED_TO"))
    return entities, relationships


def _inventory(
    client: Any,
    *,
    method: str,
    prefix: str,
    node_type: str,
    props: Any,
    model_keys: tuple[str, ...],
) -> tuple[list[Entity], list[Relationship]]:
    """CI / model / asset records, each with risk entity and optional model link."""
    entities: list[Entity] = []
    relationships: list[Relationship] = []
    for record in _call(client, method):
        key = _key(record)
        if not key:
            continue
        node_id = f"{prefix}:{key}"
        risk = _risk_props(record)
        entities.append(
            Entity(id=node_id, node_type=node_type, properties=props(key, record, risk))
        )
        risk_entities, risk_rels = _risk_entities(node_id, record, risk)
        entities.extend(risk_entities)
        relationships.extend(risk_rels)
        model = _first(record, *model_keys) if model_keys else None
        if model:
            relationships.append(_rel(node_id, f"snproduct:{model}", "INSTANCE_OF"))
    return entities, relationships


def extract(config: Any) -> ChangeSet:
    """Extract ServiceNow ITSM + CMDB + TRM into a uniform ``ChangeSet``."""
    client = _get(config, "client")
    if client is None:
        return ChangeSet()

    entities: list[Entity] = []
    relationships: list[Relationship] = []
    for ents, rels in (
        _itsm(client),
        _inventory(
            client,
            method="cmdb_cis",
            prefix="ci",
            node_type="ConfigurationItem",
            props=_ci_properties,
            model_keys=("model_id", "model"),
        ),
        _inventory(
            client,
            method="cmdb_models",
            prefix="snproduct",
            node_type="TechnologyProduct",
            props=_model_properties,
            model_keys=(),
        ),
        _inventory(
            client,
            method="assets",
            prefix="asset",
            node_type="AssetInstance",
            props=_asset_properties,
            model_keys=("model", "model_id", "model_category"),
        ),
    ):
        entities.extend(ents)
        relationships.extend(rels)
    return ChangeSet(entities=tuple(entities), relationships=tuple(relationships))


register_vendor_extractor(
    CATEGORY,
    extract,
    description="ServiceNow ITSM + CMDB + Technology Reference Model -> KG",
)
