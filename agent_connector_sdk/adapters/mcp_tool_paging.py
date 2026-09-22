"""Argument assembly, pagination and cursor advance for ``mcp_tool`` presets."""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from typing import Any

from epistemic_graph.generated.source_ingestion import SourceCheckpoint, SourceRecord
from pydantic import JsonValue

from agent_connector_sdk.manifest.presets import ToolPreset

__all__ = [
    "checkpoint_after_page",
    "dig_path",
    "next_position",
    "page_params",
    "set_path",
    "tool_arguments",
]

_NUMBERED_MODES = frozenset({"page", "offset"})


def dig_path(value: Any, dotted: str) -> Any:
    """Follow a dotted path through mappings and list indices; ``None`` if absent."""
    current = value
    for part in dotted.split("."):
        if isinstance(current, Mapping):
            current = current.get(part)
        elif isinstance(current, list) and part.isdigit() and int(part) < len(current):
            current = current[int(part)]
        else:
            return None
    return current


def set_path(target: dict[str, Any], dotted: str, value: Any) -> None:
    """Set a dotted path in a nested dict, creating intermediate dicts."""
    *parents, leaf = dotted.split(".")
    node = target
    for part in parents:
        child = node.get(part)
        node[part] = child if isinstance(child, dict) else {}
        node = node[part]
    node[leaf] = value


def tool_arguments(preset: ToolPreset, params: dict[str, Any]) -> dict[str, Any]:
    """The ``tools/call`` arguments: extras, action routing and encoded params."""
    arguments: dict[str, Any] = dict(preset.arguments)
    if preset.action:
        arguments[preset.action_param] = preset.action
    if preset.params_style == "json":
        arguments[preset.params_arg] = json.dumps(params, sort_keys=True)
        return arguments
    arguments.update(params)
    return arguments


def page_params(
    preset: ToolPreset,
    position: JsonValue,
    since: JsonValue,
    *,
    mode: str | None = None,
) -> dict[str, Any]:
    """Preset params plus the since-watermark and the pagination position."""
    params: dict[str, Any] = json.loads(json.dumps(preset.params))
    if mode is not None:
        set_path(params, preset.mode_param, mode)
    if since not in (None, {}, "") and preset.updated_since_param:
        set_path(params, preset.updated_since_param, since)
    _apply_page_position(
        preset, position if isinstance(position, Mapping) else {}, params
    )
    return params


def _apply_page_position(
    preset: ToolPreset, position: Mapping[str, Any], params: dict[str, Any]
) -> None:
    if preset.pagination == "cursor" and position.get("cursor") is not None:
        set_path(params, preset.cursor_param, position["cursor"])
    if preset.pagination in _NUMBERED_MODES:
        set_path(params, preset.page_param, _page_value(preset, position))
        if preset.page_size_param:
            set_path(params, preset.page_size_param, preset.page_size)


def _page_value(preset: ToolPreset, position: Mapping[str, Any]) -> int:
    if preset.pagination == "offset":
        return int(position.get("offset", 0))
    return int(position.get("page", preset.start_page))


def _next_cursor(
    preset: ToolPreset,
    position: Mapping[str, Any],
    *,
    result: Any,
    raw: Sequence[dict[str, Any]],
) -> dict[str, Any] | None:
    if preset.more_path and not dig_path(result, preset.more_path):
        return None
    token = dig_path(result, preset.cursor_path) if preset.cursor_path else None
    if token is None and preset.cursor_record_field:
        token = dig_path(raw[-1], preset.cursor_record_field)
    if token is None or token == position.get("cursor"):
        return None
    return {"cursor": token}


def next_position(
    preset: ToolPreset,
    position: Mapping[str, Any],
    *,
    result: Any,
    raw: Sequence[dict[str, Any]],
) -> dict[str, Any] | None:
    """The position of the next page, or ``None`` when the sweep is exhausted."""
    if preset.pagination == "none" or not raw:
        return None
    if preset.pagination == "cursor":
        return _next_cursor(preset, position, result=result, raw=raw)
    return _next_numbered(preset, position, raw)


def _next_numbered(
    preset: ToolPreset, position: Mapping[str, Any], raw: Sequence[dict[str, Any]]
) -> dict[str, Any] | None:
    if len(raw) < preset.page_size:
        return None
    if preset.pagination == "offset":
        return {"offset": int(position.get("offset", 0)) + len(raw)}
    return {"page": int(position.get("page", preset.start_page)) + 1}


def checkpoint_after_page(
    current: SourceCheckpoint,
    records: Sequence[SourceRecord],
    position: JsonValue,
    *,
    content_hash: str | None = None,
) -> SourceCheckpoint:
    """The checkpoint that resumes after a page.

    Mid-sweep the watermark stays at the last completed sweep's value and the
    page high-water mark accumulates in ``pending_watermark``; when the sweep
    is exhausted (``position`` is ``None``) the watermark advances.
    """
    marks = [
        mark
        for mark in (current.pending_watermark, *(r.updated_at for r in records))
        if mark
    ]
    high_water = max(marks) if marks else None
    if position is not None:
        return SourceCheckpoint(
            stream=current.stream,
            position=position,
            content_hash=content_hash,
            watermark=current.watermark,
            pending_watermark=high_water,
        )
    final = [mark for mark in (high_water, current.watermark) if mark]
    return SourceCheckpoint(
        stream=current.stream,
        position={},
        content_hash=content_hash,
        watermark=max(final) if final else None,
    )
