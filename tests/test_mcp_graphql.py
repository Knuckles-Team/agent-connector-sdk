"""GraphQL introspection helpers accept sync and async executors."""

from __future__ import annotations

from typing import Any

import pytest

from agent_connector_sdk.mcp.graphql import (
    SCHEMA_TYPES_QUERY,
    TYPE_DETAILS_QUERY,
    graphql_schema_types,
    graphql_type_details,
)


async def test_schema_types_with_a_sync_executor() -> None:
    seen: list[str] = []

    def execute(query: str) -> dict[str, Any]:
        seen.append(query)
        return {"data": {"__schema": {"types": [{"name": "Query"}]}}}

    result = await graphql_schema_types(execute)
    assert result["data"]["__schema"]["types"] == [{"name": "Query"}]
    assert seen == [SCHEMA_TYPES_QUERY]


async def test_type_details_with_an_async_executor() -> None:
    calls: list[tuple[str, dict[str, Any]]] = []

    async def execute(query: str, variables: dict[str, Any]) -> dict[str, Any]:
        calls.append((query, variables))
        return {"data": {"__type": {"name": variables["name"]}}}

    result = await graphql_type_details(execute, " Issue ")
    assert result == {"data": {"__type": {"name": "Issue"}}}
    assert calls == [(TYPE_DETAILS_QUERY, {"name": "Issue"})]
    assert "ofType { name kind }" in TYPE_DETAILS_QUERY


async def test_type_details_requires_a_name_and_propagates_errors() -> None:
    def failing(query: str, variables: dict[str, Any]) -> Any:
        raise RuntimeError("upstream 500")

    with pytest.raises(ValueError, match="required"):
        await graphql_type_details(failing, " ")
    with pytest.raises(RuntimeError, match="upstream 500"):
        await graphql_type_details(failing, "Issue")
