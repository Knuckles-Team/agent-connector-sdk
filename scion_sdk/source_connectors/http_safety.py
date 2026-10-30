"""Fail-closed HTTP boundary shared by native source connectors.

Every network fetch validates the destination immediately before I/O, disables
automatic redirects, re-validates each redirect target, limits redirect hops,
and bounds the decoded response body. Private/reserved destinations are denied
unless their exact hostname is present in an operator-supplied allow-list.

Injected transports/fetch callables remain available for deterministic tests;
they never weaken validation of an untrusted redirect or pagination URL.

The implementation is layered across the private ``_http_*`` siblings; this
module is the stable public surface.
"""

from __future__ import annotations

import json
from typing import Any, Unpack

from scion_sdk.config import csv_values, setting

from ._http_fetch import _FetchOptions, safe_get_bytes, safe_get_bytes_async
from ._http_resolve import (
    normalize_allowed_hosts,
    require_safe_source_url,
    resolve_safe_source_url,
    source_url_host,
)
from ._http_types import (
    DEFAULT_MAX_REDIRECTS,
    DEFAULT_MAX_REQUEST_BYTES,
    DEFAULT_MAX_RESPONSE_BYTES,
    HARD_MAX_REDIRECTS,
    HARD_MAX_RESPONSE_BYTES,
    ResolvedSourceURL,
    SourceEgressError,
)
from ._http_write import _safe_write_json, _WriteOptions, safe_post_json_async


def safe_get_text(url: str, **kwargs: Unpack[_FetchOptions]) -> str:
    body, encoding = safe_get_bytes(url, **kwargs)
    return body.decode(encoding or "utf-8", errors="replace")


def safe_get_json(url: str, **kwargs: Unpack[_FetchOptions]) -> Any:
    body, encoding = safe_get_bytes(url, **kwargs)
    try:
        return json.loads(body.decode(encoding or "utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise SourceEgressError("Source response was not valid JSON") from exc


async def safe_get_text_async(url: str, **kwargs: Unpack[_FetchOptions]) -> str:
    body, encoding = await safe_get_bytes_async(url, **kwargs)
    return body.decode(encoding or "utf-8", errors="replace")


async def safe_get_json_async(url: str, **kwargs: Unpack[_FetchOptions]) -> Any:
    body, encoding = await safe_get_bytes_async(url, **kwargs)
    try:
        return json.loads(body.decode(encoding or "utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise SourceEgressError("Source response was not valid JSON") from exc


def safe_post_json(url: str, payload: Any, **kwargs: Unpack[_WriteOptions]) -> Any:
    """POST JSON through the canonical bounded, DNS-pinned HTTP boundary."""
    return _safe_write_json("POST", url, payload, **kwargs)


def safe_delete_json(url: str, **kwargs: Unpack[_WriteOptions]) -> Any:
    """DELETE through the canonical bounded, DNS-pinned HTTP boundary."""
    return _safe_write_json("DELETE", url, None, **kwargs)


def configured_source_http_policy() -> dict[str, Any]:
    """Return the bounded, operator-configured policy for outbound source reads.

    Importing ``AgentConfig`` lazily keeps this low-level module usable by
    connector unit tests with injected transports while ensuring older fetch
    paths share the same deny-by-default private-host and redirect policy.
    """

    def _csv(name: str) -> tuple[str, ...]:
        return tuple(csv_values(setting(name, "")))

    return {
        "max_bytes": int(
            setting("SOURCE_HTTP_MAX_RESPONSE_BYTES", DEFAULT_MAX_RESPONSE_BYTES)
        ),
        "max_redirects": int(
            setting("SOURCE_HTTP_MAX_REDIRECTS", DEFAULT_MAX_REDIRECTS)
        ),
        "allowed_private_hosts": _csv("SOURCE_HTTP_ALLOWED_PRIVATE_HOSTS"),
        "allowed_redirect_hosts": _csv("SOURCE_HTTP_ALLOWED_REDIRECT_HOSTS"),
    }


__all__ = [
    "DEFAULT_MAX_REDIRECTS",
    "DEFAULT_MAX_REQUEST_BYTES",
    "DEFAULT_MAX_RESPONSE_BYTES",
    "HARD_MAX_REDIRECTS",
    "HARD_MAX_RESPONSE_BYTES",
    "ResolvedSourceURL",
    "SourceEgressError",
    "configured_source_http_policy",
    "normalize_allowed_hosts",
    "require_safe_source_url",
    "resolve_safe_source_url",
    "safe_delete_json",
    "safe_get_bytes",
    "safe_get_bytes_async",
    "safe_get_json",
    "safe_get_json_async",
    "safe_get_text",
    "safe_get_text_async",
    "safe_post_json",
    "safe_post_json_async",
    "source_url_host",
]
