"""Field-mapping helpers for the Egeria vendor extractor.

Split out of :mod:`agent_connector_sdk.vendor_extractors.egeria` (and its
entity builders in :mod:`agent_connector_sdk.vendor_extractors.egeria_entities`)
to keep each module under the KISS file-size / function-count caps. Not a
public module: imported only by the egeria extractor's own modules.
"""

from __future__ import annotations

from typing import Any

_STORE_HINTS = ("datastore", "database", "filefolder", "filesystem", "datasource")
_OBJECT_HINTS = ("dataset", "datafile", "table", "relationaltable", "datafield")

_KG_TYPES = {
    "SoftwareServer": "Server",
    "DeployedSoftwareComponent": "Tool",
    "RelationalDatabase": "DataObject",
    "DeployedDatabaseSchema": "DataObject",
    "Process": "ProcessModel",
    "Collection": "Concept",
}
_STRUCTURAL = {
    "hosts",
    "realizes",
    "secures",
    "same-as",
    "means",
    "deploys",
    "monitors",
    "reads",
    "groups",
}


def _first(record: Any, *keys: str) -> Any:
    """Return the first present, non-empty value among ``keys`` (tolerant)."""
    for key in keys:
        value = (
            record.get(key, None)
            if isinstance(record, dict)
            else getattr(record, key, None)
        )
        if value is not None and value != "":
            return value
    return None


def _classification_props(record: Any) -> dict[str, Any]:
    """Lift Egeria classifications into flat entity properties."""
    properties: dict[str, Any] = {}
    confidentiality = _first(record, "confidentiality", "confidentialityLevel")
    if confidentiality is not None:
        properties["confidentialityLevel"] = confidentiality
    retention = _first(record, "retention", "retentionPeriod")
    if retention is not None:
        properties["retentionPeriod"] = retention
    return properties


def _asset_type(record: Any) -> tuple[str, str]:
    """Resolve an Egeria asset record to (KG node type, role: store|object|other)."""
    type_name = str(_first(record, "typeName", "type", "category") or "").lower()
    if any(hint in type_name for hint in _OBJECT_HINTS):
        return "DataObject", "object"
    if any(hint in type_name for hint in _STORE_HINTS):
        return "DataConnector", "store"
    return "EAFactSheet", "other"


def _gov_type(record: Any) -> str:
    """Map an Egeria governance-definition typeName to a KG class."""
    type_name = str(_first(record, "typeName", "type") or "").lower()
    if "principle" in type_name:
        return "Principle"
    if "strategy" in type_name or "imperative" in type_name:
        return "Goal"
    return "Policy"


def _kg_type(type_name: Any) -> str:
    return _KG_TYPES.get(str(type_name or ""), "DataConnector")


def _flow_rel(label: Any) -> str:
    """Map a reconciliation/lineage edge label to a KG relationship type."""
    return "dependsOn" if str(label or "").lower() in _STRUCTURAL else "flowsTo"


def _as_list(value: Any) -> list[Any]:
    """Coerce a scalar/None/list relation field into a clean list."""
    if value is None or value == "":
        return []
    if isinstance(value, list | tuple | set):
        return [item for item in value if item]
    return [value]
