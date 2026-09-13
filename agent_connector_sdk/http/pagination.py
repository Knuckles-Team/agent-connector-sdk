"""Tool result pages that feed the ``mcp_tool`` pagination modes.

A connector tool fetches one vendor page per call and returns a
:class:`ToolPage`. The page's JSON shape matches what the ``mcp_tool`` adapter
reads (:mod:`agent_connector_sdk.adapters.mcp_tool_paging`), so the preset fields
:func:`preset_pagination` returns describe it exactly:

``cursor``
    ``next_cursor`` holds the token (``cursor_path``) and ``has_more`` gates it
    (``more_path``).
``page``
    The tool takes a page index and a page size; the sweep ends at a short page.
``offset``
    The tool takes a record offset and a page size; the sweep ends at a short page.

When a vendor paginates with ``Link: <...>; rel="next"`` (RFC 8288),
:func:`next_link_cursor` turns the link into a same-origin cursor and
:func:`cursor_target` validates a cursor a caller hands back before it is
requested, so a cursor can never redirect the client to another host.
"""

from __future__ import annotations

from typing import Literal
from urllib.parse import urljoin, urlsplit

import httpx
from pydantic import BaseModel, ConfigDict, Field, JsonValue

from agent_connector_sdk.http.errors import HttpProblemError
from agent_connector_sdk.http.problems import ProblemDetails

__all__ = ["ToolPage", "cursor_target", "next_link_cursor", "preset_pagination"]

_ORIGIN_PORTS = {"http": 80, "https": 443}


class ToolPage(BaseModel):
    """One page of records returned by a connector tool."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    items: list[JsonValue]
    next_cursor: str | None = None
    has_more: bool = False
    total: int | None = Field(default=None, ge=0)

    @classmethod
    def from_cursor(cls, items: list[JsonValue], next_cursor: str | None) -> ToolPage:
        """A cursor page; ``has_more`` is whether a next cursor exists."""
        return cls(
            items=items, next_cursor=next_cursor, has_more=next_cursor is not None
        )

    @classmethod
    def from_window(
        cls, items: list[JsonValue], *, page_size: int, total: int | None = None
    ) -> ToolPage:
        """A page or offset page; ``has_more`` is whether the page was full."""
        return cls(items=items, has_more=len(items) >= page_size, total=total)


def preset_pagination(
    mode: Literal["cursor", "page", "offset"],
    *,
    page_param: str = "",
    page_size_param: str = "",
    cursor_param: str = "",
    page_size: int = 100,
) -> dict[str, JsonValue]:
    """The ``mcp_source_presets.json`` fields for a tool returning :class:`ToolPage`."""
    fields: dict[str, JsonValue] = {"records_path": "items", "pagination": mode}
    if mode == "cursor":
        return {
            **fields,
            "cursor_param": cursor_param,
            "cursor_path": "next_cursor",
            "more_path": "has_more",
        }
    numbered: dict[str, JsonValue] = {
        "page_param": page_param,
        "page_size_param": page_size_param,
        "page_size": page_size,
        "page_kind": "offset" if mode == "offset" else "number",
    }
    return {**fields, **numbered}


def _origin(url: str) -> tuple[str, str, int | None]:
    parts = urlsplit(url)
    scheme = parts.scheme.casefold()
    return (
        scheme,
        (parts.hostname or "").casefold(),
        parts.port or _ORIGIN_PORTS.get(scheme),
    )


def _cross_origin() -> HttpProblemError:
    return HttpProblemError(
        ProblemDetails.sdk(
            "cross-origin-cursor", "Pagination cursor leaves the API origin"
        )
    )


def next_link_cursor(response: httpx.Response, *, base_url: str) -> str | None:
    """The ``rel="next"`` link as a path-and-query cursor, or ``None`` on the last page.

    Raises:
        HttpProblemError: the link points outside ``base_url``'s origin.
    """
    link = response.links.get("next", {}).get("url")
    if not link:
        return None
    absolute = urljoin(str(response.request.url), link)
    if _origin(absolute) != _origin(base_url):
        raise _cross_origin()
    parts = urlsplit(absolute)
    return f"{parts.path or '/'}?{parts.query}" if parts.query else parts.path or "/"


def cursor_target(cursor: str, *, base_url: str) -> str:
    """Validate a cursor from :func:`next_link_cursor` before requesting it.

    Raises:
        HttpProblemError: the cursor is not a same-origin path.
    """
    parts = urlsplit(cursor)
    if (
        parts.scheme
        or parts.netloc
        or not cursor.startswith("/")
        or cursor.startswith("//")
    ):
        raise _cross_origin()
    if _origin(urljoin(base_url, cursor)) != _origin(base_url):
        raise _cross_origin()
    return cursor
