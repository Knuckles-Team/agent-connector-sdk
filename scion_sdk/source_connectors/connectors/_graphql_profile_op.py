"""Operation, pagination and fallback validation for GraphQL profiles."""

from __future__ import annotations

from typing import Any

from ._graphql_base import (
    _ERROR_CODE_RE,
    _FIELD_PATH_RE,
    GraphQLDocumentError,
)
from ._graphql_paths import _valid_field_name, _valid_field_path
from ._graphql_query import (
    _query_binds_row_bound,
    _validate_query_document,
)
from ._graphql_values import _policy_values


def _validate_operation_paths_and_query(op: dict[str, Any]) -> Any:
    validated_query = _validate_query_document(op.get("query"))
    if not _valid_field_path(op.get("root_path")):
        raise GraphQLDocumentError("GraphQL operation has no response root mapping")
    for key, value in op.items():
        if (
            key.endswith("_path")
            and value not in (None, "")
            and not _valid_field_path(value)
        ):
            raise GraphQLDocumentError("GraphQL operation field path is invalid")
    for key in (
        "section_content_field",
        "section_level_field",
        "section_title_field",
    ):
        if key in op and not _valid_field_name(op[key]):
            raise GraphQLDocumentError("GraphQL operation field name is invalid")
    return validated_query


def _validate_identity_and_limits(profile: dict[str, Any]) -> None:
    identity_key = str(profile.get("identity_hmac_key") or "")
    if len(identity_key) < 32:
        raise GraphQLDocumentError(
            "GraphQL profile requires a 32-character identity HMAC key"
        )
    limits = profile.get("limits") or {}
    if not isinstance(limits, dict):
        raise GraphQLDocumentError("GraphQL profile limits are invalid")


def _validate_pagination(op: dict[str, Any], validated_query: Any) -> Any:
    pagination = op.get("pagination")
    if pagination is not None:
        if not isinstance(pagination, dict):
            raise GraphQLDocumentError("GraphQL pagination mapping is invalid")
        if any(
            not _valid_field_name(pagination.get(key))
            for key in ("cursor_variable", "page_size_variable")
        ) or any(
            not _valid_field_path(pagination.get(key))
            for key in ("next_cursor_path", "has_more_path")
        ):
            raise GraphQLDocumentError("GraphQL pagination mapping is invalid")
        if not _query_binds_row_bound(
            validated_query, str(pagination["page_size_variable"])
        ):
            raise GraphQLDocumentError(
                "GraphQL pagination query does not enforce its row bound"
            )
    return pagination


def _validate_read_bound(
    op: dict[str, Any], validated_query: Any, pagination: Any
) -> None:
    read_bound = op.get("read_bound")
    if read_bound is not None:
        if pagination is not None or not isinstance(read_bound, dict):
            raise GraphQLDocumentError("GraphQL read bound is invalid")
        variable = str(read_bound.get("variable") or "")
        maximum = read_bound.get("maximum")
        if (
            variable not in {"first", "limit"}
            or isinstance(maximum, bool)
            or not isinstance(maximum, int)
            or not 1 <= maximum <= 1_000
            or not _query_binds_row_bound(validated_query, variable)
        ):
            raise GraphQLDocumentError("GraphQL read bound is invalid")


def _validate_partial_errors(op: dict[str, Any]) -> None:
    partial = op.get("partial_errors")
    if partial is not None:
        if not isinstance(partial, dict):
            raise GraphQLDocumentError("GraphQL partial-error policy is invalid")
        _policy_values(
            partial.get("codes"), label="partial-error code", pattern=_ERROR_CODE_RE
        )
        _policy_values(
            partial.get("paths"), label="partial-error path", pattern=_FIELD_PATH_RE
        )


def _validate_fallbacks(op: dict[str, Any]) -> None:
    fallbacks = op.get("optional_field_fallbacks") or []
    if not isinstance(fallbacks, list) or len(fallbacks) > 3:
        raise GraphQLDocumentError("GraphQL optional-field fallbacks are invalid")
    for fallback in fallbacks:
        if not isinstance(fallback, dict):
            raise GraphQLDocumentError("GraphQL optional-field fallback is invalid")
        _validate_query_document(fallback.get("query"))
        _policy_values(
            fallback.get("codes"), label="fallback code", pattern=_ERROR_CODE_RE
        )
        _policy_values(
            fallback.get("paths"), label="fallback path", pattern=_FIELD_PATH_RE
        )
