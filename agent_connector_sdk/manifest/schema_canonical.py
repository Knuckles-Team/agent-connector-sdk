"""JSON-schema canonicalization shared by the tool-contract digests.

Internal to :mod:`agent_connector_sdk.manifest.tool_schema`: values become
plain JSON, presentation/runtime-default keys can be dropped, and keys plus
string lists are sorted so semantically equal schemas serialize identically.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

__all__: list[str] = []

_PRESENTATION_KEYS = frozenset({"$comment", "description", "examples", "title"})
_RUNTIME_CONFIGURATION_KEYS = frozenset({"default"})


def to_jsonable(value: Any) -> Any:
    """Plain JSON values: models dumped by alias, containers recursed, others ``str``."""
    if hasattr(value, "model_dump"):
        value = value.model_dump(by_alias=True, exclude_none=True)
    if isinstance(value, Mapping):
        return {str(key): to_jsonable(item) for key, item in value.items()}
    if isinstance(value, list | tuple | set | frozenset):
        return [to_jsonable(item) for item in value]
    if value is None or isinstance(value, str | int | float | bool):
        return value
    return str(value)


def _keep_key(key: str, include_presentation: bool) -> bool:
    if key in _RUNTIME_CONFIGURATION_KEYS:
        return False
    return include_presentation or key not in _PRESENTATION_KEYS


def normalize_schema(value: Any, include_presentation: bool) -> Any:
    """Sort keys and string lists; drop runtime defaults (and presentation keys)."""
    if isinstance(value, dict):
        return {
            key: normalize_schema(value[key], include_presentation)
            for key in sorted(value)
            if _keep_key(key, include_presentation)
        }
    if not isinstance(value, list):
        return value
    items = [normalize_schema(item, include_presentation) for item in value]
    # JSON Schema ``required`` and ``enum`` order is not semantic.
    return sorted(items) if all(isinstance(item, str) for item in items) else items
