"""Bounded JSON POST over the SDK's governed, DNS-pinned HTTP client."""

from __future__ import annotations

import json
import math
from collections.abc import Iterable, Mapping
from typing import Any

import httpx

from agent_connector_sdk.http.bodies import aread_bounded
from agent_connector_sdk.http.client import create_async_http_client
from agent_connector_sdk.http.egress_policy import EgressPolicy
from agent_connector_sdk.http.options import HttpClientOptions
from agent_connector_sdk.http.retry import RetryPolicy
from agent_connector_sdk.http.source_egress import (
    SourceEgressError,
    normalize_allowed_hosts,
    require_safe_source_url,
)
from agent_connector_sdk.tls.profile import ResolvedTLSProfile

__all__ = ["safe_post_json_async"]

_MAX_BODY_BYTES = 64 * 1024 * 1024
_MAX_HEADERS = 64
_MAX_HEADER_BYTES = 64 * 1024
_FORBIDDEN_HEADERS = frozenset(
    {
        "connection",
        "content-length",
        "host",
        "proxy-authorization",
        "proxy-connection",
        "te",
        "trailer",
        "transfer-encoding",
        "upgrade",
    }
)


def _limit(value: int, label: str) -> int:
    if isinstance(value, bool) or not 1 <= value <= _MAX_BODY_BYTES:
        raise ValueError(f"{label} must be between 1 and {_MAX_BODY_BYTES}")
    return value


def _headers(values: Mapping[str, str] | None) -> dict[str, str]:
    if len(values or {}) > _MAX_HEADERS:
        raise SourceEgressError("Source request contained too many headers")
    selected: dict[str, str] = {}
    size = 0
    for raw_name, raw_value in (values or {}).items():
        name, value = str(raw_name).strip(), str(raw_value).strip()
        if (
            not name
            or name.casefold() in _FORBIDDEN_HEADERS
            or any(
                ord(ch) < 33 or ord(ch) > 126 or ch in '():<>@,;\\"/[]?={} \t'
                for ch in name
            )
            or any((ord(ch) < 32 and ch != "\t") or ord(ch) == 127 for ch in value)
        ):
            raise SourceEgressError("Source request contained an invalid header")
        try:
            size += len(name.encode("ascii")) + len(value.encode("latin-1"))
        except UnicodeEncodeError as exc:
            raise SourceEgressError(
                "Source request contained an invalid header"
            ) from exc
        if size > _MAX_HEADER_BYTES:
            raise SourceEgressError(
                "Source request headers exceeded the configured limit"
            )
        selected[name] = value
    selected.setdefault("Content-Type", "application/json")
    return selected


def _body(payload: Any, max_request_bytes: int) -> bytes:
    try:
        body = json.dumps(
            payload, ensure_ascii=False, allow_nan=False, separators=(",", ":")
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise SourceEgressError("Source request body is not valid JSON") from exc
    if len(body) > max_request_bytes:
        raise SourceEgressError("Source request body exceeded the configured limit")
    return body


async def safe_post_json_async(
    url: str,
    payload: Any,
    *,
    headers: Mapping[str, str] | None = None,
    timeout: float = 30.0,
    max_bytes: int = 10 * 1024 * 1024,
    max_request_bytes: int = 10 * 1024 * 1024,
    allowed_private_hosts: Iterable[str] | None = None,
    transport: httpx.AsyncBaseTransport | None = None,
    tls: ResolvedTLSProfile | None = None,
) -> Any:
    """POST one JSON body with no redirect or response-size ambiguity.

    An injected transport is for in-process tests. Production requests use an
    exact-host egress policy and verify the peer selected by DNS pinning.
    """
    host = require_safe_source_url(url, allowed_private_hosts=allowed_private_hosts)
    allowed = normalize_allowed_hosts(allowed_private_hosts)
    response_limit = _limit(max_bytes, "max_bytes")
    request_limit = _limit(max_request_bytes, "max_request_bytes")
    if (
        isinstance(timeout, bool)
        or not math.isfinite(timeout)
        or not 0 < timeout <= 300
    ):
        raise ValueError("timeout must be finite and between 0 and 300 seconds")
    body = _body(payload, request_limit)
    request_headers = _headers(headers)
    options = HttpClientOptions(
        base_url=url,
        timeout=timeout,
        tls=tls,
        retry=RetryPolicy(max_attempts=1),
        egress=None if transport is not None else EgressPolicy.for_hosts(allowed),
        allow_plaintext=host in allowed,
    )
    try:
        async with (
            create_async_http_client(options, transport=transport) as client,
            client.stream(
                "POST", url, content=body, headers=request_headers
            ) as response,
        ):
            if 300 <= response.status_code < 400:
                raise SourceEgressError("State-changing source redirect is forbidden")
            response.raise_for_status()
            raw = await aread_bounded(response, response_limit)
            encoding = response.encoding or "utf-8"
    except httpx.HTTPError as exc:
        raise SourceEgressError("Source request failed") from exc
    if not raw:
        return {}
    try:
        return json.loads(raw.decode(encoding))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise SourceEgressError("Source response is not valid JSON") from exc
