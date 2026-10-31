"""Request header and query-parameter validation for the source HTTP boundary."""

from __future__ import annotations

from typing import Any

from ._http_types import (
    _FORBIDDEN_CALLER_HEADERS,
    _HARD_MAX_QUERY_PARAMETERS,
    _HARD_MAX_REQUEST_HEADER_BYTES,
    _HARD_MAX_REQUEST_HEADERS,
    _HARD_MAX_URL_CHARS,
    _SENSITIVE_REDIRECT_HEADERS,
    ResolvedSourceURL,
    SourceEgressError,
)
from ._http_urls import _logical_authority, _logical_origin


def _validate_header_shape(name: str, value: str) -> None:
    lowered = name.casefold()
    if (
        not name
        or lowered in _FORBIDDEN_CALLER_HEADERS
        or any(character in name for character in "\r\n:")
        or any(character in value for character in "\r\n")
    ):
        raise SourceEgressError("Source request contained a forbidden header")


def _header_byte_length(name: str, value: str) -> int:
    try:
        return len(name.encode("ascii")) + len(value.encode("latin-1"))
    except UnicodeEncodeError as exc:
        raise SourceEgressError("Source request contained an invalid header") from exc


def _validated_headers(headers: dict[str, str] | None) -> dict[str, str]:
    if len(headers or {}) > _HARD_MAX_REQUEST_HEADERS:
        raise SourceEgressError("Source request contained too many headers")
    normalized: dict[str, str] = {}
    total_bytes = 0
    for raw_name, raw_value in (headers or {}).items():
        name = str(raw_name).strip()
        value = str(raw_value).strip()
        _validate_header_shape(name, value)
        total_bytes += _header_byte_length(name, value)
        if total_bytes > _HARD_MAX_REQUEST_HEADER_BYTES:
            raise SourceEgressError(
                "Source request headers exceeded the configured limit"
            )
        normalized[name] = value
    return normalized


def _validated_params(params: dict[str, Any] | None) -> dict[str, Any]:
    selected = dict(params or {})
    if len(selected) > _HARD_MAX_QUERY_PARAMETERS:
        raise SourceEgressError("Source request contained too many query parameters")
    for raw_name, raw_value in selected.items():
        values = raw_value if isinstance(raw_value, list | tuple) else (raw_value,)
        if len(values) > _HARD_MAX_QUERY_PARAMETERS:
            raise SourceEgressError("Source query parameter contained too many values")
        rendered_name = str(raw_name)
        if len(rendered_name) > _HARD_MAX_URL_CHARS:
            raise SourceEgressError(
                "Source query parameter exceeded the configured limit"
            )
        for value in values:
            if len(str(value)) > _HARD_MAX_URL_CHARS:
                raise SourceEgressError(
                    "Source query parameter exceeded the configured limit"
                )
    return selected


def _headers_for_hop(
    logical_url: str,
    headers: dict[str, str],
    *,
    initial_origin: tuple[str, str, int],
) -> dict[str, str]:
    same_origin = _logical_origin(logical_url) == initial_origin
    selected = {
        name: value
        for name, value in headers.items()
        if same_origin or name.casefold() not in _SENSITIVE_REDIRECT_HEADERS
    }
    selected["Host"] = _logical_authority(logical_url)
    return selected


def _request_extensions(resolution: ResolvedSourceURL) -> dict[str, Any]:
    return {"sni_hostname": resolution.host} if resolution.scheme == "https" else {}
