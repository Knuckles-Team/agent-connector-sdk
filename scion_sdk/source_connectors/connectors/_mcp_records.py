"""Preset merging and cursor extraction for the MCP package connector."""

from __future__ import annotations

from typing import Any

from ._rest_support import _dig

#: Settings a preset fills only when the caller left them empty.
_PRESET_FILLS = (
    "server",
    "tool",
    "records_field",
    "updated_field",
    "cursor_field",
    "cursor_arg",
    "query_arg",
)
#: Settings a preset overrides outright (default: keep the caller's value).
_PRESET_OVERRIDES = ("id_field", "title_field", "text_field", "doc_type")


def _merge_preset(package: str, current: dict[str, Any]) -> dict[str, Any]:
    """Merge a parity-catalog preset into ``current``; unknown packages change nothing."""
    from .package_manifest import get_preset

    preset = get_preset(package)
    if not preset:
        return current
    merged = dict(current)
    for key in _PRESET_FILLS:
        merged[key] = current[key] or preset.get(key, "")
    for key in _PRESET_OVERRIDES:
        merged[key] = preset.get(key, current[key])
    merged["args"] = {**preset.get("args", {}), **(current["args"] or {})}
    return merged


def _next_cursor_of(result: Any, cursor_field: str) -> str | None:
    if not cursor_field or not isinstance(result, dict):
        return None
    top = _dig(result, cursor_field)
    return str(top) if top else None
