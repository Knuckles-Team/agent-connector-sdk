"""Helpers for the optional FastMCP ``Context`` handed to tool handlers.

Extracted from ``agent_utilities.mcp.context_helpers``. A missing context or a
failed elicitation always denies a destructive operation: unattended execution
is not write authorization.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

__all__ = [
    "GraphQLField",
    "GraphQLFieldArgument",
    "GraphQLTypeDetails",
    "GraphQLTypeNotFoundError",
    "ctx_confirm_destructive",
    "ctx_graphql_get_type_details",
    "ctx_graphql_list_types",
    "ctx_log",
]

_logger = logging.getLogger(__name__)

_LOG_LEVELS = frozenset({"debug", "info", "warning", "error"})

_LIST_TYPES_QUERY = "query { __schema { types { name } } }"
_TYPE_DETAILS_QUERY = """
query($name: String!) {
  __type(name: $name) {
    name
    kind
    fields {
      name
      type { name kind ofType { name kind } }
      args {
        name
        type { name kind ofType { name kind } }
      }
    }
  }
}
""".strip()


async def ctx_confirm_destructive(ctx: Any, action_description: str) -> bool:
    """Ask the connected user to confirm a destructive operation.

    Returns:
        ``True`` only when a live context exists and the user accepted.
    """
    if not ctx:
        return False
    try:
        result = await ctx.elicit(
            f"Are you sure you want to {action_description}?", response_type=bool
        )
    except Exception as exc:  # a failed elicitation denies the operation
        _logger.warning(
            "Elicitation failed; destructive operation denied: %s",
            exc,
        )
        return False
    return bool(result.action == "accept" and bool(result.data))


async def ctx_log(
    ctx: Any, message: str, *, logger: logging.Logger, level: str = "info"
) -> None:
    """Log ``message`` to ``logger`` and, when a context is present, the client.

    Raises:
        ValueError: ``level`` is not debug, info, warning or error.
    """
    if level not in _LOG_LEVELS:
        raise ValueError(f"unsupported log level {level!r}")
    getattr(logger, level)(message)
    if not ctx:
        return
    try:
        await getattr(ctx, level)(message)
    except Exception as exc:  # client log delivery is best-effort by contract
        logger.warning("MCP client log delivery failed: %s", exc)


@dataclass(frozen=True)
class GraphQLFieldArgument:
    """One argument a GraphQL field accepts."""

    name: str
    type_name: str


@dataclass(frozen=True)
class GraphQLField:
    """One field a GraphQL type declares."""

    name: str
    type_name: str
    arguments: tuple[GraphQLFieldArgument, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class GraphQLTypeDetails:
    """A named GraphQL type's own fields and argument shapes."""

    name: str
    kind: str
    fields: tuple[GraphQLField, ...] = field(default_factory=tuple)


class GraphQLTypeNotFoundError(LookupError):
    """The schema declares no type with the requested name."""


def _named_type(type_ref: Mapping[str, Any] | None) -> str:
    if not type_ref:
        return "Unknown"
    name = type_ref.get("name")
    if name:
        return str(name)
    return _named_type(type_ref.get("ofType"))


async def ctx_graphql_list_types(ctx: Any) -> tuple[str, ...]:
    """The connector's GraphQL schema's declared type names.

    Resolved through ``ctx.graphql(query)`` on the connector's own session
    context; the caller never hand-rolls the introspection query.
    """
    result = await ctx.graphql(_LIST_TYPES_QUERY)
    types: Sequence[Mapping[str, Any]] = result["data"]["__schema"]["types"]
    return tuple(str(item["name"]) for item in types)


async def ctx_graphql_get_type_details(ctx: Any, type_name: str) -> GraphQLTypeDetails:
    """A named GraphQL type's fields and their argument shapes.

    Raises:
        GraphQLTypeNotFoundError: the schema declares no type ``type_name``.
    """
    result = await ctx.graphql(_TYPE_DETAILS_QUERY, {"name": type_name})
    raw = result["data"]["__type"]
    if raw is None:
        raise GraphQLTypeNotFoundError(type_name)
    fields = tuple(
        GraphQLField(
            name=str(item["name"]),
            type_name=_named_type(item.get("type")),
            arguments=tuple(
                GraphQLFieldArgument(
                    name=str(argument["name"]),
                    type_name=_named_type(argument.get("type")),
                )
                for argument in item.get("args") or ()
            ),
        )
        for item in raw.get("fields") or ()
    )
    return GraphQLTypeDetails(
        name=str(raw["name"]), kind=str(raw["kind"]), fields=fields
    )
