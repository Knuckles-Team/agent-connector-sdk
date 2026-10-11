"""CISO Assistant GRC vendor extractor (SDK-SOURCE-INGEST-R006.27).

Ported from
``agent_utilities.knowledge_graph.enrichment.extractors.ciso_assistant`` onto
this SDK's typed :mod:`~agent_connector_sdk.vendor_extractors.contract`:
intuitem CISO Assistant GRC records (policies, controls, risks, threats,
assessments, frameworks, assets, incidents, third-party entities) become the
same canonical governance entity types the Egeria extractor emits, so CISO
Assistant data reconciles with the Egeria/Camunda crosswalk:

    policy                         -> ``Policy``               ciso_assistant_policy:{id}
    applied / reference control    -> ``Control``              ciso_assistant_control:{id}
    risk scenario                  -> ``Risk``                 ciso_assistant_risk:{id}
    threat                         -> ``Threat``                ciso_assistant_threat:{id}
    risk assessment                -> ``RiskAssessment``        ciso_assistant_risk_assessment:{id}
    compliance assessment / audit  -> ``ComplianceAssessment``  ciso_assistant_compliance_assessment:{id}
    framework                      -> ``Framework``             ciso_assistant_framework:{id}
    asset                          -> ``Asset``                 ciso_assistant_asset:{id}
    incident                       -> ``Incident``              ciso_assistant_incident:{id}
    security exception / finding   -> ``SecurityException`` / ``Finding``
    third-party entity             -> ``Entity``                ciso_assistant_entity:{id}

Every entity carries ``domain="ciso_assistant"`` + ``externalToolId`` (the
CISO uuid) + ``qualifiedName`` (the CISO ``urn``/``ref_id``). A record
carrying an explicit Egeria GUID or Camunda/BPMN process id emits an
``ALIGNED_WITH`` equivalence relationship, exactly as the Camunda extractor
does. The client is injected (duck-typed) via ``config["client"]``; this
module performs no network calls itself.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from agent_connector_sdk.ingest import ChangeSet, Entity, Relationship
from agent_connector_sdk.vendor_extractors.ciso_assistant_helpers import (
    _as_list,
    _base_props,
    _crosswalk,
    _first,
    _get,
    _id_of,
    _list,
)
from agent_connector_sdk.vendor_extractors.contract import register_vendor_extractor

CATEGORY = "ciso_assistant"

__all__ = [
    "CATEGORY",
    "extract",
]

_Spec = tuple[str, str, str]
_Extra = Callable[[Any, str], list[Relationship]]

_SIMPLE_KINDS: list[_Spec] = [
    ("api_policies_list", "ciso_assistant_policy", "Policy"),
    ("api_applied_controls_list", "ciso_assistant_control", "Control"),
    ("api_reference_controls_list", "ciso_assistant_refcontrol", "Control"),
    ("api_threats_list", "ciso_assistant_threat", "Threat"),
    (
        "api_risk_assessments_list",
        "ciso_assistant_risk_assessment",
        "RiskAssessment",
    ),
    ("api_frameworks_list", "ciso_assistant_framework", "Framework"),
    ("api_assets_list", "ciso_assistant_asset", "Asset"),
    ("api_incidents_list", "ciso_assistant_incident", "Incident"),
    (
        "api_security_exceptions_list",
        "ciso_assistant_exception",
        "SecurityException",
    ),
    ("api_findings_list", "ciso_assistant_finding", "Finding"),
    ("api_entities_list", "ciso_assistant_entity", "Entity"),
    ("api_perimeters_list", "ciso_assistant_perimeter", "Perimeter"),
]


def _link(source: str, target: str, relationship: str) -> Relationship:
    return Relationship(source=source, target=target, relationship=relationship)


def _risk_links(record: Any, node_id: str) -> list[Relationship]:
    """MITIGATED_BY / PART_OF links for a risk scenario."""
    rels: list[Relationship] = []
    for control in _as_list(_first(record, "applied_controls", "controls")):
        control_id = _id_of(control)
        if control_id:
            rels.append(
                _link(node_id, f"ciso_assistant_control:{control_id}", "MITIGATED_BY")
            )
    assessment = _id_of(_first(record, "risk_assessment"))
    if assessment:
        rels.append(
            _link(node_id, f"ciso_assistant_risk_assessment:{assessment}", "PART_OF")
        )
    return rels


def _compliance_links(record: Any, node_id: str) -> list[Relationship]:
    """CONFORMS_TO link for a compliance assessment."""
    framework = _id_of(_first(record, "framework"))
    if not framework:
        return []
    return [_link(node_id, f"ciso_assistant_framework:{framework}", "CONFORMS_TO")]


def _collect(
    client: Any, spec: _Spec, *, seen: set[str], related: _Extra | None
) -> tuple[list[Entity], list[Relationship]]:
    """Entities + relationships for one record kind, deduplicated via ``seen``."""
    method, prefix, node_type = spec
    entities: list[Entity] = []
    rels: list[Relationship] = []
    for record in _list(client, method):
        external_id = _first(record, "id", "uuid")
        if not external_id:
            continue
        node_id = f"{prefix}:{external_id}"
        if node_id in seen:
            continue
        seen.add(node_id)
        entities.append(
            Entity(id=node_id, node_type=node_type, properties=_base_props(record))
        )
        rels.extend(_crosswalk(record, node_id))
        if related is not None:
            rels.extend(related(record, node_id))
    return entities, rels


def extract(config: Any) -> ChangeSet:
    """Extract CISO Assistant GRC artifacts into a uniform ``ChangeSet``."""
    client = _get(config, "client")
    if client is None:
        return ChangeSet()

    plan: list[tuple[_Spec, _Extra | None]] = [(s, None) for s in _SIMPLE_KINDS]
    plan.append(
        (("api_risk_scenarios_list", "ciso_assistant_risk", "Risk"), _risk_links)
    )
    plan.append(
        (
            (
                "api_compliance_assessments_list",
                "ciso_assistant_compliance_assessment",
                "ComplianceAssessment",
            ),
            _compliance_links,
        )
    )
    entities: list[Entity] = []
    relationships: list[Relationship] = []
    seen: set[str] = set()
    for spec, related in plan:
        ents, rels = _collect(client, spec, seen=seen, related=related)
        entities.extend(ents)
        relationships.extend(rels)
    return ChangeSet(entities=tuple(entities), relationships=tuple(relationships))


register_vendor_extractor(
    CATEGORY,
    extract,
    description="intuitem CISO Assistant GRC (policies/controls/risks/assessments) -> KG",
)
