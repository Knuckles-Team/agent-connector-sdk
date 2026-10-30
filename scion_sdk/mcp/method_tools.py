"""One typed, annotated MCP tool per API operation of a connector's client class.

SCION-CONNECTOR-CONTROL-R020 makes this the connector standard: every public
operation of the connector's API client (``client_cls``) is served as its own
MCP tool. A fleet gateway scales the large catalog through lazy ``find`` and
load, so no operation is folded behind an ``action`` string.

For each operation the tool carries:

* **Name** ``<prefix>_<operation>`` (no doubled prefix), stable snake_case.
  ``<operation>`` is the client method name, or the manifest entry's ``name``.
* **Input schema** from the operation manifest (OpenAPI ``parameters`` and
  ``requestBody``) when the connector ships one, otherwise from the client
  method's signature and type hints (for a bare ``**kwargs`` method, from the
  one Pydantic model it validates its keywords through). Required parameters stay required;
  optional ones default. A bare ``**kwargs`` method, or one whose types cannot
  form a schema, takes one ``params_json`` object and is recorded on the server
  under :data:`UNTYPED_TOOLS_ATTRIBUTE` so the debt stays visible.
* **Description** from the manifest summary or the method docstring.
* **Annotations** from the HTTP verb: GET/HEAD are read-only and idempotent;
  PUT and DELETE are idempotent; DELETE is destructive; every non-GET verb is
  not read-only. The verb comes from the manifest, an ``__http_method__``
  attribute, a ``VERB /path`` docstring line, or the single verb the method
  body sends; without one, name tokens classify the operation.

A destructive operation asks the connected caller to confirm through
:func:`scion_sdk.mcp.context.ctx_confirm_destructive` before the
client is called (SCION-CONNECTOR-CONTROL-R026.1).
"""

from __future__ import annotations

import inspect
from collections.abc import Callable, Mapping
from functools import partial
from typing import Any

from mcp.types import ToolAnnotations

from scion_sdk.mcp._method_introspect import (
    _derive_domains,
    _domain_methods,
    _manifest_index,
    _tool_name,
    operation_tool_names,
    operation_verb,
)
from scion_sdk.mcp._method_invoke import _typed_tool, _untyped_tool, jsonable_result
from scion_sdk.mcp._method_params import (
    _json_return,
    _manifest_parameters,
    _method_parameters,
    _ParamShape,
)
from scion_sdk.mcp.action_dispatch import is_destructive_action

__all__ = [
    "GATED_TAG",
    "GRANULAR_TAG",
    "OPERATION_TAG",
    "UNTYPED_TOOLS_ATTRIBUTE",
    "jsonable_result",
    "operation_annotations",
    "operation_tool_names",
    "operation_verb",
    "register_method_tools",
]

#: Tag stamped on every operation tool and every compatibility action tool.
GRANULAR_TAG = "granular"
#: Tag stamped on every served tool, held back from a default session view.
GATED_TAG = "gated"
#: Tag stamped on every per-operation tool.
OPERATION_TAG = "operation"
#: Server attribute recording operation tools that fell back to ``params_json``.
UNTYPED_TOOLS_ATTRIBUTE = "_untyped_operation_tools"

_READ_TOKENS = frozenset(
    {"get", "list", "search", "read", "fetch", "find", "query", "count", "ping"}
)


def operation_annotations(
    name: str, verb: str | None, *, title: str | None = None
) -> ToolAnnotations:
    """MCP tool annotations for one operation, from its HTTP verb or name tokens."""
    destructive = verb == "DELETE" or is_destructive_action(name)
    if verb is None:
        read_only = name.split("_", 1)[0] in _READ_TOKENS and not destructive
        idempotent = True if read_only else None
    else:
        read_only = verb in ("GET", "HEAD")
        idempotent = verb in ("GET", "HEAD", "PUT", "DELETE")
    return ToolAnnotations(
        title=title or name.replace("_", " ").capitalize(),
        read_only_hint=read_only,
        destructive_hint=False if read_only else destructive,
        idempotent_hint=idempotent,
        open_world_hint=True,
    )


def _description(method: Callable[..., Any], operation: Mapping[str, Any]) -> str:
    text = operation.get("summary") or operation.get("description")
    if not text:
        text = inspect.getdoc(method)
    return str(text or f"Invoke the {method.__name__} operation.").strip()


def _build_tool(
    *,
    method_name: str,
    method: Callable[..., Any],
    get_client: Any,
    operation: Mapping[str, Any],
    destructive: bool,
    coercer: Callable[[Any], Any],
    returns: Any,
) -> tuple[Callable[[], Callable[..., Any]] | None, Callable[..., Any]]:
    """``(typed-tool factory or None, untyped fallback)`` for one operation."""
    params = _manifest_parameters(operation)
    shape = _ParamShape(params) if params is not None else _method_parameters(method)
    untyped = _untyped_tool(
        method_name, get_client, destructive=destructive, coercer=coercer
    )
    if shape is None:
        return None, untyped
    typed = partial(
        _typed_tool,
        method_name,
        get_client,
        shape,
        destructive=destructive,
        coercer=coercer,
        returns=returns,
    )
    return typed, untyped


def _register_tool(
    mcp: Any,
    options: dict[str, Any],
    tools: tuple[Callable[[], Callable[..., Any]] | None, Callable[..., Any]],
) -> bool:
    """Register the typed tool (built lazily), else the ``params_json`` one.

    Returns ``True`` when the typed tool registered.
    """
    typed, untyped = tools
    name = options["name"]
    try:
        if typed is None:
            raise TypeError("no typed parameters")
        mcp.tool(**options)(typed())
    except (TypeError, ValueError) as error:
        if name in _registered_names(mcp):
            raise ValueError(f"operation tool {name!r}: {error}") from error
        mcp.tool(**options)(untyped)
        return False
    return True


def _register_operation(
    mcp: Any,
    *,
    tool_name: str,
    method_name: str,
    method: Callable[..., Any],
    operation: Mapping[str, Any],
    domain: str,
    get_client: Any,
    coercer: Callable[[Any], Any],
    typed_returns: bool,
) -> bool:
    verb = operation_verb(method, operation)
    options = {
        "name": tool_name,
        "description": _description(method, operation),
        "tags": {domain, OPERATION_TAG, GRANULAR_TAG, GATED_TAG},
        "annotations": operation_annotations(method_name, verb),
    }
    tools = _build_tool(
        method_name=method_name,
        method=method,
        get_client=get_client,
        operation=operation,
        destructive=verb == "DELETE" or is_destructive_action(method_name, operation),
        coercer=coercer,
        returns=_json_return(method) if typed_returns else Any,
    )
    return _register_tool(mcp, options, tools)


def register_method_tools(
    mcp: Any,
    client_cls: type,
    get_client: Any,
    *,
    prefix: str,
    manifest: list[dict[str, Any]] | None = None,
    result_coercer: Callable[[Any], Any] | None = None,
) -> list[str]:
    """Register one typed, annotated MCP tool per public method of ``client_cls``.

    Each tool is named ``<prefix>_<method>`` (or ``<prefix>_<name>`` from its
    manifest entry), tagged with a domain derived from the method's defining
    class, :data:`OPERATION_TAG`, :data:`GRANULAR_TAG` and :data:`GATED_TAG`.
    ``manifest`` entries (``{method, http, name?, summary?, parameters?,
    requestBody?}``) supply the OpenAPI schema and verb; otherwise the method
    signature and type hints do. ``get_client`` is called fresh on every
    invocation (synchronous or returning an awaitable). ``result_coercer``
    shapes each client return value; :func:`jsonable_result` is the default.

    Skips methods defined only on a base-infrastructure class (auth,
    pagination, retry machinery -- never a real operation). A destructive
    operation is gated behind a live caller's confirmation.

    Returns:
        The registered tool names, in method-iteration order.

    Raises:
        ValueError: a manifest entry is malformed or a tool name collides with
            one already registered on ``mcp``.
    """
    coercer = result_coercer or jsonable_result
    operations = _manifest_index(manifest)
    owners = _domain_methods(client_cls)
    domains = _derive_domains(owners)
    untyped: set[str] = set(getattr(mcp, UNTYPED_TOOLS_ATTRIBUTE, set()))
    existing = _registered_names(mcp)
    registered: list[str] = []
    for method_name in owners:
        operation = operations.get(method_name, {})
        tool_name = _tool_name(str(operation.get("name") or method_name), prefix)
        if tool_name in existing:
            raise ValueError(f"operation tool name collides: {tool_name!r}")
        typed = _register_operation(
            mcp,
            tool_name=tool_name,
            method_name=method_name,
            method=getattr(client_cls, method_name),
            operation=operation,
            domain=domains[method_name],
            get_client=get_client,
            coercer=coercer,
            typed_returns=result_coercer is None,
        )
        if not typed:
            untyped.add(tool_name)
        existing.add(tool_name)
        registered.append(tool_name)
    setattr(mcp, UNTYPED_TOOLS_ATTRIBUTE, untyped)
    return registered


def _registered_names(mcp: Any) -> set[str]:
    provider = getattr(mcp, "_local_provider", None)
    components = getattr(provider, "_components", None)
    if not isinstance(components, dict):
        return set()
    return {
        str(getattr(value, "name", ""))
        for key, value in components.items()
        if str(key).startswith("tool:")
    }
