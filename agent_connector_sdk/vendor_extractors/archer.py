"""RSA Archer GRC vendor extractor (SDK-SOURCE-INGEST-R006.20).

Ported from ``agent_utilities.knowledge_graph.enrichment.extractors.archer``
onto this SDK's typed :mod:`~agent_connector_sdk.vendor_extractors.contract`:
risks become ``Risk`` entities, controls become ``ComplianceControl``
entities (``MITIGATES`` their risk), and findings become ``Finding`` entities
(``AFFECTS`` their control). The Archer client is injected (duck-typed) via
``config["client"]``, expected to expose ``list_risks()`` / ``list_controls()``
/ ``list_findings()``. All field access is tolerant and this module performs
no network calls itself.
"""

from __future__ import annotations

from typing import Any

from agent_connector_sdk.ingest import ChangeSet, Entity, Relationship
from agent_connector_sdk.vendor_extractors.contract import register_vendor_extractor

CATEGORY = "archer"


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


def _call(client: Any, name: str) -> list[Any]:
    """Call a client method if present, returning a list (tolerant)."""
    method = getattr(client, name, None)
    if not callable(method):
        return []
    try:
        result = method()
    except TypeError:
        try:
            result = method({})
        except Exception:
            return []
    except Exception:
        return []
    if isinstance(result, dict):
        result = result.get("value") or result.get("items") or result.get("data") or []
    return list(result) if result else []


def extract(config: Any) -> ChangeSet:
    """Extract Archer GRC records into a uniform ``ChangeSet``.

    Risks/controls/findings become typed governance entities; controls link
    ``MITIGATES`` their risk and findings link ``AFFECTS`` their control.
    """
    client = _get(config, "client")
    if client is None:
        return ChangeSet()

    entities: list[Entity] = []
    relationships: list[Relationship] = []

    for record in _call(client, "list_risks"):
        risk_id = _first(record, "id", "Id", "name", "Name")
        if not risk_id:
            continue
        entities.append(
            Entity(
                id=f"archer_risk:{risk_id}",
                node_type="Risk",
                properties={
                    "name": _first(record, "name", "Name", "Title"),
                    "capability": "grc",
                },
            )
        )

    for record in _call(client, "list_controls"):
        control_id = _first(record, "id", "Id", "name", "Name")
        if not control_id:
            continue
        node_id = f"archer_control:{control_id}"
        entities.append(
            Entity(
                id=node_id,
                node_type="ComplianceControl",
                properties={
                    "name": _first(record, "name", "Name", "Title"),
                    "capability": "grc",
                },
            )
        )
        risk_ref = _first(record, "riskId", "RiskId", "risk_id")
        if risk_ref:
            relationships.append(
                Relationship(
                    source=node_id,
                    target=f"archer_risk:{risk_ref}",
                    relationship="MITIGATES",
                )
            )

    for record in _call(client, "list_findings"):
        finding_id = _first(record, "id", "Id", "name", "Name")
        if not finding_id:
            continue
        node_id = f"archer_finding:{finding_id}"
        entities.append(
            Entity(
                id=node_id,
                node_type="Finding",
                properties={
                    "name": _first(record, "name", "Name", "Title"),
                    "capability": "grc",
                },
            )
        )
        control_ref = _first(record, "controlId", "ControlId", "control_id")
        if control_ref:
            relationships.append(
                Relationship(
                    source=node_id,
                    target=f"archer_control:{control_ref}",
                    relationship="AFFECTS",
                )
            )

    return ChangeSet(entities=tuple(entities), relationships=tuple(relationships))


register_vendor_extractor(
    CATEGORY,
    extract,
    description="RSA Archer GRC (risks/controls/findings) -> KG",
)
