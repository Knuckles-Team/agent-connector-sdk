"""Endpoint, header and shape validation for GraphQL profiles."""

from __future__ import annotations

from typing import Any
from urllib.parse import urlparse

from ._graphql_base import (
    _BLOCKED_REQUEST_HEADERS,
    _HEADER_RE,
    GraphQLDocumentError,
)


def _validate_endpoint(profile: dict[str, Any]) -> None:
    endpoint = str(profile.get("endpoint") or "")
    parsed_endpoint = urlparse(endpoint)
    if (
        parsed_endpoint.scheme != "https"
        or not parsed_endpoint.hostname
        or parsed_endpoint.username is not None
        or parsed_endpoint.password is not None
        or parsed_endpoint.query
        or parsed_endpoint.fragment
    ):
        raise GraphQLDocumentError("GraphQL endpoint must use HTTPS")


def _validate_profile_shape(profile: dict[str, Any]) -> tuple[Any, Any]:
    headers = profile.get("headers") or {}
    operations = profile.get("operations") or {}
    if not isinstance(headers, dict) or not isinstance(operations, dict):
        raise GraphQLDocumentError("GraphQL profile has an invalid shape")
    return headers, operations


def _validate_header_entry(name: Any, value: Any, normalized_names: set[str]) -> None:
    if not isinstance(name, str) or not isinstance(value, str):
        raise GraphQLDocumentError("GraphQL profile headers are invalid")
    rendered_name = str(name)
    rendered_value = str(value)
    normalized_name = rendered_name.lower()
    if (
        not _HEADER_RE.fullmatch(rendered_name)
        or len(rendered_value.encode("utf-8")) > 16_384
        or "\r" in rendered_value
        or "\n" in rendered_value
        or normalized_name in _BLOCKED_REQUEST_HEADERS
        or normalized_name in normalized_names
    ):
        raise GraphQLDocumentError("GraphQL profile headers are invalid")
    normalized_names.add(normalized_name)


def _validate_headers(headers: dict[str, Any]) -> None:
    if len(headers) > 32:
        raise GraphQLDocumentError("GraphQL profile headers are invalid")
    normalized_names: set[str] = set()
    for name, value in headers.items():
        _validate_header_entry(name, value, normalized_names)
