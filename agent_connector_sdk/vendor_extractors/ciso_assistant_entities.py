"""Record-to-entity builders for the CISO Assistant vendor extractor.

Split out of :mod:`agent_connector_sdk.vendor_extractors.ciso_assistant` to
keep that module under the KISS file-size / function-count caps. Not a public
module: imported only by ``ciso_assistant.py``, which owns ``extract()`` and
registration.
"""

from __future__ import annotations

from typing import Any

from agent_connector_sdk.ingest import Entity, Relationship
from agent_connector_sdk.vendor_extractors.ciso_assistant_mappers import (
    _as_list,
    _first,
    _get,
    _id_of,
    _list,
)


def _base_props(record: Any) -> dict[str, Any]:
    return {
        "domain": "ciso_assistant",
        "externalToolId": _first(record, "id", "uuid"),
        "qualifiedName": _first(record, "urn", "ref_id", "name"),
        "name": _first(record, "name", "ref_id", "str") or _first(record, "urn"),
        "ref_id": _get(record, "ref_id"),
        "description": _get(record, "description"),
    }


class _ChangeSetBuilder:
    """Accumulates entities/relationships while de-duplicating node ids."""

    def __init__(self) -> None:
        self.entities: list[Entity] = []
        self.relationships: list[Relationship] = []
        self._seen: set[str] = set()

    def add(self, node_id: str, node_type: str, properties: dict[str, Any]) -> bool:
        if node_id in self._seen:
            return False
        self._seen.add(node_id)
        self.entities.append(
            Entity(id=node_id, node_type=node_type, properties=properties)
        )
        return True

    def crosswalk(self, record: Any, node_id: str) -> None:
        """ALIGNED_WITH equivalence relationships to Egeria / Camunda twins."""
        egeria_guid = _first(record, "egeria_guid", "egeria_id", "egeriaGuid")
        if egeria_guid:
            self.relationships.append(
                Relationship(
                    source=node_id,
                    target=f"egeria_policy:{egeria_guid}",
                    relationship="ALIGNED_WITH",
                )
            )
        bpmn_id = _first(record, "bpmn_process_id", "camunda_process_id", "process_id")
        if bpmn_id:
            self.relationships.append(
                Relationship(
                    source=node_id,
                    target=f"bpmn_process:{bpmn_id}",
                    relationship="ALIGNED_WITH",
                )
            )


_SIMPLE_KINDS = [
    ("api_policies_list", "ciso_assistant_policy", "Policy"),
    ("api_applied_controls_list", "ciso_assistant_control", "Control"),
    ("api_reference_controls_list", "ciso_assistant_refcontrol", "Control"),
    ("api_threats_list", "ciso_assistant_threat", "Threat"),
    ("api_risk_assessments_list", "ciso_assistant_risk_assessment", "RiskAssessment"),
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


def _add_simple_kinds(client: Any, builder: _ChangeSetBuilder) -> None:
    """Add every single-record-shape kind (no extra relationships)."""
    for method, prefix, node_type in _SIMPLE_KINDS:
        for record in _list(client, method):
            external_id = _first(record, "id", "uuid")
            if not external_id:
                continue
            node_id = f"{prefix}:{external_id}"
            if builder.add(node_id, node_type, _base_props(record)):
                builder.crosswalk(record, node_id)


def _risk_scenario_relationships(
    record: Any, node_id: str, builder: _ChangeSetBuilder
) -> None:
    for control in _as_list(_first(record, "applied_controls", "controls")):
        control_id = _id_of(control)
        if control_id:
            builder.relationships.append(
                Relationship(
                    source=node_id,
                    target=f"ciso_assistant_control:{control_id}",
                    relationship="MITIGATED_BY",
                )
            )
    assessment = _id_of(_first(record, "risk_assessment"))
    if assessment:
        builder.relationships.append(
            Relationship(
                source=node_id,
                target=f"ciso_assistant_risk_assessment:{assessment}",
                relationship="PART_OF",
            )
        )


def _add_risk_scenarios(client: Any, builder: _ChangeSetBuilder) -> None:
    """Add risk-scenario records as ``Risk`` entities."""
    for record in _list(client, "api_risk_scenarios_list"):
        external_id = _first(record, "id", "uuid")
        if not external_id:
            continue
        node_id = f"ciso_assistant_risk:{external_id}"
        if not builder.add(node_id, "Risk", _base_props(record)):
            continue
        builder.crosswalk(record, node_id)
        _risk_scenario_relationships(record, node_id, builder)


def _add_compliance_assessments(client: Any, builder: _ChangeSetBuilder) -> None:
    """Add compliance-assessment records as ``ComplianceAssessment`` entities."""
    for record in _list(client, "api_compliance_assessments_list"):
        external_id = _first(record, "id", "uuid")
        if not external_id:
            continue
        node_id = f"ciso_assistant_compliance_assessment:{external_id}"
        if not builder.add(node_id, "ComplianceAssessment", _base_props(record)):
            continue
        builder.crosswalk(record, node_id)
        framework = _id_of(_first(record, "framework"))
        if framework:
            builder.relationships.append(
                Relationship(
                    source=node_id,
                    target=f"ciso_assistant_framework:{framework}",
                    relationship="CONFORMS_TO",
                )
            )
