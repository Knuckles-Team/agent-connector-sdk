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

from typing import Any

from agent_connector_sdk.ingest import ChangeSet, Entity, Relationship
from agent_connector_sdk.vendor_extractors.contract import register_vendor_extractor

CATEGORY = "ciso_assistant"


def _get(record: Any, key: str, default: Any = None) -> Any:
    """Tolerant field access for dict records (or attr-style objects)."""
    if isinstance(record, dict):
        return record.get(key, default)
    return getattr(record, key, default)


def _first(record: Any, *keys: str) -> Any:
    """Return the first present, non-empty value among ``keys``."""
    for key in keys:
        value = _get(record, key)
        if value is not None and value != "":
            return value
    return None


def _list(client: Any, name: str) -> list[Any]:
    """Call a generated list-method if present, returning its ``.data`` list."""
    method = getattr(client, name, None)
    if not callable(method):
        return []
    try:
        result = method()
    except Exception:
        return []
    data = getattr(result, "data", result)
    if isinstance(data, dict):
        data = data.get("results") or data.get("items") or data.get("data") or []
    return list(data) if isinstance(data, list) else []


def _ref_id(record: Any) -> Any:
    """A record's stable cross-system key: urn first, then ref_id, then name."""
    return _first(record, "urn", "ref_id", "name")


def _id_of(value: Any) -> Any:
    """Resolve a related-object reference (uuid string, dict, or {'id': ...})."""
    if value is None or value == "":
        return None
    if isinstance(value, dict):
        return value.get("id") or value.get("uuid") or value.get("str")
    return value


def _as_list(value: Any) -> list[Any]:
    """Coerce a scalar/None/list relation field into a clean list."""
    if value is None or value == "":
        return []
    if isinstance(value, list | tuple | set):
        return [item for item in value if item]
    return [value]


def extract(config: Any) -> ChangeSet:
    """Extract CISO Assistant GRC artifacts into a uniform ``ChangeSet``."""
    client = _get(config, "client")
    if client is None:
        return ChangeSet()

    entities: list[Entity] = []
    relationships: list[Relationship] = []
    seen: set[str] = set()

    def _base_props(record: Any) -> dict[str, Any]:
        return {
            "domain": "ciso_assistant",
            "externalToolId": _first(record, "id", "uuid"),
            "qualifiedName": _ref_id(record),
            "name": _first(record, "name", "ref_id", "str") or _first(record, "urn"),
            "ref_id": _get(record, "ref_id"),
            "description": _get(record, "description"),
        }

    def _add(node_id: str, node_type: str, properties: dict[str, Any]) -> bool:
        if node_id in seen:
            return False
        seen.add(node_id)
        entities.append(Entity(id=node_id, node_type=node_type, properties=properties))
        return True

    def _crosswalk(record: Any, node_id: str) -> None:
        """ALIGNED_WITH equivalence relationships to Egeria / Camunda twins."""
        egeria_guid = _first(record, "egeria_guid", "egeria_id", "egeriaGuid")
        if egeria_guid:
            relationships.append(
                Relationship(
                    source=node_id,
                    target=f"egeria_policy:{egeria_guid}",
                    relationship="ALIGNED_WITH",
                )
            )
        bpmn_id = _first(record, "bpmn_process_id", "camunda_process_id", "process_id")
        if bpmn_id:
            relationships.append(
                Relationship(
                    source=node_id,
                    target=f"bpmn_process:{bpmn_id}",
                    relationship="ALIGNED_WITH",
                )
            )

    simple_kinds = [
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
    for method, prefix, node_type in simple_kinds:
        for record in _list(client, method):
            external_id = _first(record, "id", "uuid")
            if not external_id:
                continue
            node_id = f"{prefix}:{external_id}"
            if _add(node_id, node_type, _base_props(record)):
                _crosswalk(record, node_id)

    for record in _list(client, "api_risk_scenarios_list"):
        external_id = _first(record, "id", "uuid")
        if not external_id:
            continue
        node_id = f"ciso_assistant_risk:{external_id}"
        if not _add(node_id, "Risk", _base_props(record)):
            continue
        _crosswalk(record, node_id)
        for control in _as_list(_first(record, "applied_controls", "controls")):
            control_id = _id_of(control)
            if control_id:
                relationships.append(
                    Relationship(
                        source=node_id,
                        target=f"ciso_assistant_control:{control_id}",
                        relationship="MITIGATED_BY",
                    )
                )
        assessment = _id_of(_first(record, "risk_assessment"))
        if assessment:
            relationships.append(
                Relationship(
                    source=node_id,
                    target=f"ciso_assistant_risk_assessment:{assessment}",
                    relationship="PART_OF",
                )
            )

    for record in _list(client, "api_compliance_assessments_list"):
        external_id = _first(record, "id", "uuid")
        if not external_id:
            continue
        node_id = f"ciso_assistant_compliance_assessment:{external_id}"
        if not _add(node_id, "ComplianceAssessment", _base_props(record)):
            continue
        _crosswalk(record, node_id)
        framework = _id_of(_first(record, "framework"))
        if framework:
            relationships.append(
                Relationship(
                    source=node_id,
                    target=f"ciso_assistant_framework:{framework}",
                    relationship="CONFORMS_TO",
                )
            )

    return ChangeSet(entities=tuple(entities), relationships=tuple(relationships))


register_vendor_extractor(
    CATEGORY,
    extract,
    description="intuitem CISO Assistant GRC (policies/controls/risks/assessments) -> KG",
)
