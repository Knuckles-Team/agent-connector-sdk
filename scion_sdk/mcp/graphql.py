"""GraphQL schema-discovery helpers over a connector's own executor (SCION-CONNECTOR-CONTROL-R014.12).

Replaces ``agent_utilities.mcp.context_helpers.ctx_graphql_list_types`` and
``ctx_graphql_get_type_details`` for connectors (gitlab-api, twenty-mcp) that
pass their own GraphQL executor rather than a session context. The executor is
a sync or async callable ``execute(query, variables=None) -> dict``; the
helpers send standard introspection queries and return its response unchanged.
A failure never surfaces the exception text: it returns a fixed
``operation_failed`` payload with the exception class and a correlation id,
and logs the cause server-side under that id.

For the typed, session-context variant see
:func:`scion_sdk.mcp.context.ctx_graphql_list_types`.
"""

from __future__ import annotations

import inspect
import logging
import uuid
from typing import Any, cast

__all__ = [
    "GET_TYPE_DETAILS_QUERY",
    "LIST_TYPES_QUERY",
    "ctx_graphql_get_type_details",
    "ctx_graphql_list_types",
    "graphql_failure_payload",
]

_logger = logging.getLogger(__name__)

LIST_TYPES_QUERY = """
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

GET_TYPE_DETAILS_QUERY = """
query GetTypeDetails($name: String!) {
  __type(name: $name) {
    name
    kind
    description
    fields {
      name
      description
      args {
        name
        description
        type { name kind ofType { name kind } }
      }
      type { name kind ofType { name kind } }
    }
  }
}
"""


def graphql_failure_payload(exc: BaseException) -> dict[str, Any]:
    """The public failure payload: no exception message, one correlation id."""
    correlation_id = uuid.uuid4().hex
    _logger.warning(
        "GraphQL introspection failed (correlation_id=%s, error_class=%s)",
        correlation_id,
        type(exc).__name__,
    )
    return {
        "status": "error",
        "code": "operation_failed",
        "retryable": False,
        "error_class": type(exc).__name__,
        "correlation_id": correlation_id,
    }


async def _execute(execute_gql_fn: Any, query: str, **kwargs: Any) -> dict[str, Any]:
    result = execute_gql_fn(query, **kwargs)
    if inspect.isawaitable(result):
        result = await result
    return cast("dict[str, Any]", result)


async def ctx_graphql_list_types(execute_gql_fn: Any) -> dict[str, Any]:
    """Every type in the schema (name, kind, description) via introspection."""
    try:
        return await _execute(execute_gql_fn, LIST_TYPES_QUERY)
    except Exception as exc:
        return graphql_failure_payload(exc)


async def ctx_graphql_get_type_details(
    execute_gql_fn: Any, type_name: str
) -> dict[str, Any]:
    """One type's fields, their arguments and types via introspection."""
    try:
        return await _execute(
            execute_gql_fn, GET_TYPE_DETAILS_QUERY, variables={"name": type_name}
        )
    except Exception as exc:
        return graphql_failure_payload(exc)
