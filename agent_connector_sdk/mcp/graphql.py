"""Standard GraphQL schema introspection for connectors that front a GraphQL API.

Replaces ``agent_utilities.mcp.context_helpers.ctx_graphql_list_types`` and
``ctx_graphql_get_type_details``. ``execute`` is the connector's own query
function, sync or async, called as ``execute(query)`` or
``execute(query, variables=...)``; its response is returned unchanged and its
errors propagate to the server's error middleware.
"""

from __future__ import annotations

import inspect
from collections.abc import Callable
from typing import Any

__all__ = [
    "SCHEMA_TYPES_QUERY",
    "TYPE_DETAILS_QUERY",
    "graphql_schema_types",
    "graphql_type_details",
]

#: Every type in the schema with its kind and description.
SCHEMA_TYPES_QUERY = """
query IntrospectionQuery {
  __schema {
    types {
      name
      kind
      description
    }
  }
}
"""

_TYPE_REF = "type { name kind ofType { name kind } }"

#: One type's fields, their arguments and their (unwrapped once) types.
TYPE_DETAILS_QUERY = (
    "query GetTypeDetails($name: String!) {\n"
    "  __type(name: $name) {\n"
    "    name\n    kind\n    description\n"
    "    fields {\n"
    "      name\n      description\n"
    f"      args {{ name description {_TYPE_REF} }}\n"
    f"      {_TYPE_REF}\n"
    "    }\n"
    "  }\n"
    "}\n"
)


async def _execute(execute: Callable[..., Any], query: str, **kwargs: Any) -> Any:
    result = execute(query, **kwargs)
    return await result if inspect.isawaitable(result) else result


async def graphql_schema_types(execute: Callable[..., Any]) -> Any:
    """The schema's types (name, kind, description)."""
    return await _execute(execute, SCHEMA_TYPES_QUERY)


async def graphql_type_details(execute: Callable[..., Any], type_name: str) -> Any:
    """One type's fields and arguments.

    Raises:
        ValueError: ``type_name`` is empty.
    """
    if not type_name.strip():
        raise ValueError("type_name is required")
    return await _execute(
        execute, TYPE_DETAILS_QUERY, variables={"name": type_name.strip()}
    )
