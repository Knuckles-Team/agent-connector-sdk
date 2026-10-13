"""Helpers for the optional FastMCP ``Context`` handed to tool handlers.

Extracted from ``agent_utilities.mcp.context_helpers``. A missing context or a
failed elicitation always denies a destructive operation: unattended execution
is not write authorization.
"""

from __future__ import annotations

import hashlib
import json
import logging
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from mcp.types import ElicitRequest, ElicitRequestFormParams, InputRequiredResult
from pydantic import BaseModel, StrictBool

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
_MODERN_MCP_PROTOCOL = "2026-07-28"
_CONFIRMATION_INPUT_KEY = "destructive_action_confirmation"


class _DestructiveActionConfirmation(BaseModel):
    confirmed: StrictBool


class _FailClosedInputRequiredResult(InputRequiredResult):
    """Keep legacy boolean guards fail-closed while new callers propagate us."""

    def __bool__(self) -> bool:
        return False


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


def _confirmation_binding(
    action_description: str, arguments: Mapping[str, Any] | None
) -> str | None:
    """Bind a modern confirmation response to this action and its arguments."""
    try:
        payload = json.dumps(
            {"action": action_description, "arguments": dict(arguments or {})},
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
            allow_nan=False,
        )
    except (TypeError, ValueError):
        return None
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _input_required_result(
    action_description: str, binding: str
) -> InputRequiredResult:
    """Ask for an explicit boolean confirmation in a modern MCP round trip."""
    return _FailClosedInputRequiredResult(
        result_type="input_required",
        input_requests={
            _CONFIRMATION_INPUT_KEY: ElicitRequest(
                method="elicitation/create",
                params=ElicitRequestFormParams(
                    message=f"Are you sure you want to {action_description}?",
                    requested_schema={
                        "type": "object",
                        "properties": {
                            "confirmed": {
                                "type": "boolean",
                                "title": "Confirm this destructive action",
                            }
                        },
                        "required": ["confirmed"],
                    },
                ),
            )
        },
        request_state=binding,
    )


async def ctx_confirm_destructive(
    ctx: Any,
    action_description: str,
    *,
    confirmation_arguments: Mapping[str, Any] | None = None,
) -> bool | InputRequiredResult:
    """Require explicit confirmation in the live negotiated MCP era.

    Modern MCP returns an input request and only continues when the client
    retries with an accepted response bound to the same action and arguments.
    Earlier protocol versions use FastMCP's elicitation request. Any missing
    context, response, or protocol identity denies by default.
    """
    if not ctx:
        return False

    request_context = getattr(ctx, "request_context", None)
    protocol_version = getattr(request_context, "protocol_version", None)
    if not isinstance(protocol_version, str):
        return False

    if protocol_version >= _MODERN_MCP_PROTOCOL:
        binding = _confirmation_binding(action_description, confirmation_arguments)
        if binding is None:
            _logger.warning("Could not bind destructive confirmation; operation denied")
            return False

        responses = getattr(ctx, "input_responses", None)
        request_state = getattr(ctx, "request_state", None)
        if responses is None:
            if request_state is not None:
                return False
            return _input_required_result(action_description, binding)
        if request_state != binding or not isinstance(responses, Mapping):
            return False

        response = responses.get(_CONFIRMATION_INPUT_KEY)
        content = getattr(response, "content", None)
        return bool(
            getattr(response, "action", None) == "accept"
            and isinstance(content, Mapping)
            and content.get("confirmed") is True
        )

    try:
        result = await ctx.elicit(
            f"Are you sure you want to {action_description}?",
            response_type=_DestructiveActionConfirmation,
        )
    except Exception:
        _logger.warning("Elicitation failed; destructive operation denied")
        return False
    return bool(
        result.action == "accept" and getattr(result.data, "confirmed", None) is True
    )


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
