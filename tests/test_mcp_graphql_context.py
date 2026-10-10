"""SDK-CONNECTOR-CONTROL-R030: GraphQL introspection context helpers."""

from __future__ import annotations

from typing import Any

import pytest

from agent_connector_sdk.mcp.context import (
    GraphQLField,
    GraphQLFieldArgument,
    GraphQLTypeDetails,
    GraphQLTypeNotFoundError,
    ctx_graphql_get_type_details,
    ctx_graphql_list_types,
)

_SCHEMA_TYPES = {
    "data": {"__schema": {"types": [{"name": "Widget"}, {"name": "Order"}]}}
}

_WIDGET_TYPE = {
    "data": {
        "__type": {
            "name": "Widget",
            "kind": "OBJECT",
            "fields": [
                {
                    "name": "id",
                    "type": {"name": "ID", "kind": "SCALAR", "ofType": None},
                    "args": [],
                },
                {
                    "name": "orders",
                    "type": {
                        "name": None,
                        "kind": "LIST",
                        "ofType": {"name": "Order", "kind": "OBJECT"},
                    },
                    "args": [
                        {
                            "name": "limit",
                            "type": {"name": "Int", "kind": "SCALAR", "ofType": None},
                        }
                    ],
                },
            ],
        }
    }
}

_MISSING_TYPE: dict[str, Any] = {"data": {"__type": None}}


class _FakeGraphQLSession:
    def __init__(self, responses: dict[str, dict[str, Any]]) -> None:
        self._responses = responses

    async def graphql(
        self, query: str, variables: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        if "__schema" in query:
            return self._responses["list_types"]
        return self._responses["type_details"]


async def test_lists_declared_types() -> None:
    ctx = _FakeGraphQLSession({"list_types": _SCHEMA_TYPES, "type_details": {}})
    types = await ctx_graphql_list_types(ctx)
    assert types == ("Widget", "Order")


async def test_returns_a_named_types_fields_and_arguments() -> None:
    ctx = _FakeGraphQLSession({"list_types": {}, "type_details": _WIDGET_TYPE})
    details = await ctx_graphql_get_type_details(ctx, "Widget")
    assert isinstance(details, GraphQLTypeDetails)
    assert details.name == "Widget"
    assert details.kind == "OBJECT"
    by_name = {field.name: field for field in details.fields}
    assert isinstance(by_name["id"], GraphQLField)
    assert by_name["id"].type_name == "ID"
    assert by_name["orders"].type_name == "Order"
    assert isinstance(by_name["orders"].arguments[0], GraphQLFieldArgument)
    assert by_name["orders"].arguments[0].name == "limit"
    assert by_name["orders"].arguments[0].type_name == "Int"


async def test_unknown_type_name_raises() -> None:
    ctx = _FakeGraphQLSession({"list_types": {}, "type_details": _MISSING_TYPE})
    with pytest.raises(GraphQLTypeNotFoundError):
        await ctx_graphql_get_type_details(ctx, "DoesNotExist")
