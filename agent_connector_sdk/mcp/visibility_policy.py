"""The visibility policy: server allow/deny lists a client may only narrow.

Extracted from ``DynamicVisibilityTransform`` in
``agent_utilities.mcp.server_factory``. Server policy comes from
``MCP_ENABLED_TOOLS``, ``MCP_DISABLED_TOOLS``, ``MCP_ENABLED_TAGS``,
``MCP_DISABLED_TAGS`` and the ``--tools``/``--disabled-tools`` flags. An HTTP
client may narrow it through query parameters or ``x-mcp-*`` headers. A
malformed client filter, and a semantic ``q=`` filter (the SDK has no semantic
resolver), expose nothing rather than everything.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from dataclasses import dataclass, replace
from typing import Any

from agent_connector_sdk.config import csv_values, setting
from agent_connector_sdk.mcp.visibility_filters import narrow_values, request_values

__all__ = ["HEADER_KEYS", "QUERY_KEYS", "VisibilityPolicy", "current_request"]

_logger = logging.getLogger(__name__)
_NO_HTTP_REQUEST = "No active HTTP request found."

QUERY_KEYS: dict[str, tuple[str, ...]] = {
    "enabled_names": ("tools", "toolsets"),
    "disabled_names": ("disabled_tools", "disabled_toolsets"),
    "enabled_tags": ("tags",),
    "disabled_tags": ("disabled_tags",),
    "query": ("q", "query", "search"),
}
HEADER_KEYS: dict[str, tuple[str, ...]] = {
    "enabled_names": ("x-mcp-enabled-tools", "x-mcp-enabled-components"),
    "disabled_names": ("x-mcp-disabled-tools", "x-mcp-disabled-components"),
    "enabled_tags": ("x-mcp-enabled-tags",),
    "disabled_tags": ("x-mcp-disabled-tags",),
    "query": ("x-mcp-query", "x-mcp-search"),
}


def current_request() -> Any | None:
    """The active FastMCP HTTP request, or ``None`` outside an HTTP call."""
    from fastmcp.server.dependencies import get_http_request

    try:
        return get_http_request()
    except RuntimeError as exc:
        if exc.args == (_NO_HTTP_REQUEST,):
            return None
        raise


@dataclass(frozen=True)
class VisibilityPolicy:
    """Resolved allow and deny lists for component names and tags."""

    enabled_names: tuple[str, ...] = ()
    disabled_names: tuple[str, ...] = ()
    enabled_tags: tuple[str, ...] = ()
    disabled_tags: tuple[str, ...] = ()
    reject_all: bool = False

    @classmethod
    def from_settings(
        cls, cli_tools: str | None = None, cli_disabled_tools: str | None = None
    ) -> VisibilityPolicy:
        """Server policy from settings; CLI flags replace the tool lists."""
        return cls(
            enabled_names=tuple(csv_values(cli_tools or setting("MCP_ENABLED_TOOLS"))),
            disabled_names=tuple(
                csv_values(cli_disabled_tools or setting("MCP_DISABLED_TOOLS"))
            ),
            enabled_tags=tuple(csv_values(setting("MCP_ENABLED_TAGS"))),
            disabled_tags=tuple(csv_values(setting("MCP_DISABLED_TAGS"))),
        )

    def narrowed(
        self, source: Any, keys: dict[str, tuple[str, ...]]
    ) -> VisibilityPolicy:
        """Apply one request source; allowlists intersect, denylists union."""
        if any(source.get(name) for name in keys["query"]):
            return replace(self, reject_all=True)
        disabled_names = request_values(source, keys["disabled_names"])
        disabled_tags = request_values(source, keys["disabled_tags"])
        return replace(
            self,
            enabled_names=narrow_values(
                self.enabled_names, request_values(source, keys["enabled_names"])
            ),
            disabled_names=tuple(
                dict.fromkeys([*self.disabled_names, *disabled_names])
            ),
            enabled_tags=narrow_values(
                self.enabled_tags, request_values(source, keys["enabled_tags"])
            ),
            disabled_tags=tuple(dict.fromkeys([*self.disabled_tags, *disabled_tags])),
        )

    def for_current_request(self) -> VisibilityPolicy:
        """This policy narrowed by the active HTTP request; malformed rejects all."""
        try:
            request = current_request()
            narrowed = (
                self
                if request is None
                else self.narrowed(request.query_params, QUERY_KEYS)
            )
            return (
                narrowed
                if request is None
                else narrowed.narrowed(request.headers, HEADER_KEYS)
            )
        except Exception as exc:  # a malformed client filter exposes nothing
            _logger.warning("Rejected MCP visibility filter: %s", exc)
            return replace(self, reject_all=True)

    def _name_permitted(self, name: str) -> bool:
        enabled = set(self.enabled_names) - {"all"}
        return (not enabled or name in enabled) and name not in self.disabled_names

    def _tags_permitted(self, tags: set[str]) -> bool:
        if not tags:
            return not self.enabled_tags
        enabled = set(self.enabled_tags)
        return (not enabled or bool(tags & enabled)) and not tags & set(
            self.disabled_tags
        )

    def permits(self, component: Any) -> bool:
        """Whether one component is visible; a component without a name is not."""
        name = str(
            getattr(component, "name", None) or getattr(component, "uri", None) or ""
        )
        if self.reject_all or not name:
            return False
        return self._name_permitted(name) and self._tags_permitted(
            set(getattr(component, "tags", None) or ())
        )

    def visible(self, components: Sequence[Any]) -> list[Any]:
        """The visible subset of ``components``."""
        return [component for component in components if self.permits(component)]

    def visible_one(self, component: Any) -> Any:
        """``component`` when visible, otherwise ``None``."""
        return component if component is not None and self.permits(component) else None
