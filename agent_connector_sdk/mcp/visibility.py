"""The FastMCP transform that applies :class:`VisibilityPolicy` per request."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from fastmcp.server.transforms import Transform

from agent_connector_sdk.mcp.visibility_policy import VisibilityPolicy

__all__ = ["VisibilityTransform"]


class VisibilityTransform(Transform):
    """Filters every tool, resource, template and prompt listing and lookup."""

    def __init__(self, policy: VisibilityPolicy) -> None:
        super().__init__()
        self._policy = policy

    async def list_tools(self, tools: Sequence[Any]) -> Sequence[Any]:
        """Visible tools."""
        return self._policy.for_current_request().visible(tools)

    async def get_tool(self, name: str, call_next: Any, *, version: Any = None) -> Any:
        """A tool only when visible."""
        found = await call_next(name, version=version)
        return self._policy.for_current_request().visible_one(found)

    async def list_resources(self, resources: Sequence[Any]) -> Sequence[Any]:
        """Visible resources."""
        return self._policy.for_current_request().visible(resources)

    async def get_resource(
        self, uri: str, call_next: Any, *, version: Any = None
    ) -> Any:
        """A resource only when visible."""
        found = await call_next(uri, version=version)
        return self._policy.for_current_request().visible_one(found)

    async def list_resource_templates(self, templates: Sequence[Any]) -> Sequence[Any]:
        """Visible resource templates."""
        return self._policy.for_current_request().visible(templates)

    async def get_resource_template(
        self, uri: str, call_next: Any, *, version: Any = None
    ) -> Any:
        """A resource template only when visible."""
        found = await call_next(uri, version=version)
        return self._policy.for_current_request().visible_one(found)

    async def list_prompts(self, prompts: Sequence[Any]) -> Sequence[Any]:
        """Visible prompts."""
        return self._policy.for_current_request().visible(prompts)

    async def get_prompt(
        self, name: str, call_next: Any, *, version: Any = None
    ) -> Any:
        """A prompt only when visible."""
        found = await call_next(name, version=version)
        return self._policy.for_current_request().visible_one(found)
