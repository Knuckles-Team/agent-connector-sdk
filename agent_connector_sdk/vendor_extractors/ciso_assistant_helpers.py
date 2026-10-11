"""Primitive record helpers for the CISO Assistant extractor."""

from __future__ import annotations

from typing import Any

from agent_connector_sdk.ingest import Relationship
from agent_connector_sdk.vendor_extractors._records import _first, _get


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


def _base_props(record: Any) -> dict[str, Any]:
    """Canonical properties shared by every CISO Assistant entity."""
    return {
        "domain": "ciso_assistant",
        "externalToolId": _first(record, "id", "uuid"),
        "qualifiedName": _ref_id(record),
        "name": _first(record, "name", "ref_id", "str") or _first(record, "urn"),
        "ref_id": _get(record, "ref_id"),
        "description": _get(record, "description"),
    }


def _crosswalk(record: Any, node_id: str) -> list[Relationship]:
    """ALIGNED_WITH equivalence relationships to Egeria / Camunda twins."""
    rels: list[Relationship] = []
    egeria_guid = _first(record, "egeria_guid", "egeria_id", "egeriaGuid")
    if egeria_guid:
        rels.append(
            Relationship(
                source=node_id,
                target=f"egeria_policy:{egeria_guid}",
                relationship="ALIGNED_WITH",
            )
        )
    bpmn_id = _first(record, "bpmn_process_id", "camunda_process_id", "process_id")
    if bpmn_id:
        rels.append(
            Relationship(
                source=node_id,
                target=f"bpmn_process:{bpmn_id}",
                relationship="ALIGNED_WITH",
            )
        )
    return rels
