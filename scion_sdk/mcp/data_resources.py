"""Live descriptor resources derived from the registered connector tools."""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any

from fastmcp.resources import FunctionResource, Resource, ResourceResult
from fastmcp.server.providers import Provider


async def _surface_summary(
    mcp: Any, root: Path, descriptors: list[dict[str, Any]]
) -> dict[str, dict[str, object]]:
    """Hash the actual listed members and resource bodies for each surface."""
    members: dict[str, list[tuple[str, bytes]]] = {
        name: []
        for name in ("tools", "prompts", "skills", "ontology", "shapes", "data")
    }
    for tool in await mcp.list_tools():
        body = tool.to_mcp_tool().model_dump(mode="json")
        members["tools"].append(
            (str(tool.name), json.dumps(body, sort_keys=True).encode())
        )
    members["prompts"] = [
        _prompt_member(prompt, root) for prompt in await mcp.list_prompts()
    ]
    members.update(await _resource_members(mcp, descriptors))
    return {kind: _summarize(items) for kind, items in members.items()}


def _prompt_member(prompt: Any, root: Path) -> tuple[str, bytes]:
    body = prompt.to_mcp_prompt().model_dump(mode="json")
    payload = json.dumps(body, sort_keys=True).encode()
    if re.fullmatch(r"[A-Za-z0-9._-]+", str(prompt.name)):
        source = root / "prompts" / f"{prompt.name}.json"
        if source.is_file():
            payload += b"\0" + source.read_bytes()
    return str(prompt.name), payload


async def _resource_members(
    mcp: Any, descriptors: list[dict[str, Any]]
) -> dict[str, list[tuple[str, bytes]]]:
    members: dict[str, list[tuple[str, bytes]]] = {
        name: [] for name in ("skills", "ontology", "shapes", "data")
    }
    schemes = {
        "skill": "skills",
        "ontology": "ontology",
        "shapes": "shapes",
    }
    expected_data = {str(item["uri"]): item for item in descriptors}
    listed_data: set[str] = set()
    for resource in await mcp.list_resources():
        uri = str(resource.uri)
        if uri.startswith("data://"):
            listed_data.add(uri)
            continue
        kind = schemes.get(uri.partition(":")[0])
        if kind is None:
            continue
        content = await resource.read()
        result = (
            content if isinstance(content, ResourceResult) else ResourceResult(content)
        )
        payload = result.to_mcp_result(uri).model_dump_json(by_alias=True).encode()
        members[kind].append((uri, payload))
    if listed_data != set(expected_data):
        raise ValueError("served data resources differ from their declaration")
    members["data"] = [
        (uri, json.dumps(item, sort_keys=True).encode())
        for uri, item in expected_data.items()
    ]
    return members


def _summarize(items: list[tuple[str, bytes]]) -> dict[str, object]:
    manifest = [
        {"name": name, "sha256": hashlib.sha256(body).hexdigest()}
        for name, body in sorted(items)
    ]
    encoded = json.dumps(manifest, sort_keys=True, separators=(",", ":")).encode()
    return {"count": len(manifest), "sha256": hashlib.sha256(encoded).hexdigest()}


def _descriptor_resource(descriptor: dict[str, Any]) -> FunctionResource:
    def read() -> str:
        return json.dumps(descriptor, sort_keys=True, separators=(",", ":"))

    return FunctionResource(
        uri=descriptor["uri"],
        name=descriptor["name"],
        mime_type="application/json",
        description="Declared source contract; rows are read through the source operation.",
        fn=read,
    )


class _DataResourceProvider(Provider):
    """Resolve each descriptor at list and read time, after tools are registered."""

    def __init__(self, descriptors: Callable[[], list[dict[str, Any]]]) -> None:
        super().__init__()
        self._descriptors = descriptors

    async def _list_resources(self) -> Sequence[Resource]:
        return [_descriptor_resource(item) for item in self._descriptors()]
