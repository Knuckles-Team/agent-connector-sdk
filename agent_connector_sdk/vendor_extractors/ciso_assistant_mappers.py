"""Field-mapping helpers for the CISO Assistant vendor extractor.

Split out of :mod:`agent_connector_sdk.vendor_extractors.ciso_assistant` (and
its entity builders in
:mod:`agent_connector_sdk.vendor_extractors.ciso_assistant_entities`) to keep
each module under the KISS file-size / function-count caps. Not a public
module: imported only by the CISO Assistant extractor's own modules.
"""

from __future__ import annotations

from typing import Any


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
