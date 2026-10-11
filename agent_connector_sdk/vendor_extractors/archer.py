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


def _invoke(method: Any) -> Any:
    """Call ``method()``; on ``TypeError`` retry with an empty params dict."""
    try:
        return method()
    except TypeError:
        return method({})


def _call(client: Any, name: str) -> list[Any]:
    """Call a client method if present, returning a list (tolerant)."""
    method = getattr(client, name, None)
    if not callable(method):
        return []
    try:
        result = _invoke(method)
    except Exception:
        return []
    if isinstance(result, dict):
        result = result.get("value") or result.get("items") or result.get("data") or []
    return list(result) if result else []


def _extract_kind(
    client: Any,
    method: str,
    *,
    prefix: str,
    node_type: str,
    entities: list[Entity],
    relationships: list[Relationship] | None = None,
    ref_keys: tuple[str, ...] = (),
    link: tuple[str, str] = ("", ""),
) -> None:
    """Append one GRC record kind, optionally linking it to a parent kind."""
    for record in _call(client, method):
        record_id = _first(record, "id", "Id", "name", "Name")
        if not record_id:
            continue
        node_id = f"{prefix}:{record_id}"
        entities.append(
            Entity(
                id=node_id,
                node_type=node_type,
                properties={
                    "name": _first(record, "name", "Name", "Title"),
                    "capability": "grc",
                },
            )
        )
        ref = _first(record, *ref_keys) if ref_keys else None
        if ref and relationships is not None:
            relationships.append(
                Relationship(
                    source=node_id,
                    target=f"{link[0]}:{ref}",
                    relationship=link[1],
                )
            )


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
    _extract_kind(
        client,
        "list_risks",
        prefix="archer_risk",
        node_type="Risk",
        entities=entities,
    )
    _extract_kind(
        client,
        "list_controls",
        prefix="archer_control",
        node_type="ComplianceControl",
        entities=entities,
        relationships=relationships,
        ref_keys=("riskId", "RiskId", "risk_id"),
        link=("archer_risk", "MITIGATES"),
    )
    _extract_kind(
        client,
        "list_findings",
        prefix="archer_finding",
        node_type="Finding",
        entities=entities,
        relationships=relationships,
        ref_keys=("controlId", "ControlId", "control_id"),
        link=("archer_control", "AFFECTS"),
    )

    return ChangeSet(entities=tuple(entities), relationships=tuple(relationships))


register_vendor_extractor(
    CATEGORY,
    extract,
    description="RSA Archer GRC (risks/controls/findings) -> KG",
)
