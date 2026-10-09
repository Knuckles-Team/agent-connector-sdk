"""Opt-in: one directly-invokable MCP tool per public API-client method.

Extracted from the untyped-parameter tier of
``agent_utilities.mcp.verbose_tools.register_verbose_tools``.
SDK-CONNECTOR-CONTROL-R020 retired the *implicit*, ``MCP_TOOL_MODE``-toggled
verbose 1:1 tool surface in :mod:`agent_connector_sdk.mcp.tool_surface`: every
connector now always registers exactly the condensed, action-routed,
intent-gated tools. That retirement did not remove the need for the
primitive itself -- a connector whose already-served tool surface genuinely
depends on one separately-invokable tool per client method (not routed
through a condensed ``action`` + ``params_json`` tool) still needs it, now as
an explicit call its own server module makes, never as a hidden env-toggle
branch.

Every registered tool takes one ``params_json`` blob (the manifest-driven
typed-signature tier of the ``agent_utilities`` original is not ported here;
a connector that needs that stays on ``agent_utilities`` for it) and
dispatches by name to ``client.<method>(**kwargs)`` through
:func:`agent_connector_sdk.mcp.concurrency.invoke_client_method`, so a
synchronous or asynchronous client method runs the same way the condensed
action-routed tools already do. A method name
:func:`agent_connector_sdk.mcp.action_dispatch.is_destructive_action`
classifies destructive asks the connected caller to confirm first via
:func:`agent_connector_sdk.mcp.context.ctx_confirm_destructive`; an
unattended or declined request never runs it.
"""

from __future__ import annotations

import inspect
import os.path
import re
from typing import Any

from fastmcp import Context
from pydantic import Field

from agent_connector_sdk.mcp.action_dispatch import (
    is_destructive_action,
    parse_json_object,
)
from agent_connector_sdk.mcp.concurrency import invoke_client_method
from agent_connector_sdk.mcp.context import ctx_confirm_destructive
from agent_connector_sdk.mcp.tool_surface import GRANULAR_TAG

__all__ = ["register_method_tools"]


def _defining_class(client_cls: type, name: str) -> type | None:
    """The class in ``client_cls``'s MRO that actually defines attribute ``name``."""
    for klass in client_cls.__mro__:
        if name in klass.__dict__:
            return klass
    return None


def _is_base_infra_class_name(name: str) -> bool:
    """Whether a class name follows the fleet's base-infra naming convention.

    Two conventions coexist across the connector fleet for the class holding
    auth/pagination/retry machinery (never a real API operation): a suffix
    (``ApiBase``) and a prefix (``BaseApiClient``). A leading underscore (a
    module-private class) is ignored before matching.
    """
    core = name.lstrip("_")
    return core.endswith("Base") or core.startswith("Base")


def _domain_methods(client_cls: type) -> dict[str, type]:
    """Public domain methods of ``client_cls`` mapped to their defining class.

    Excludes private names, anything inherited from ``object``, and
    base-infrastructure methods.
    """
    methods: dict[str, type] = {}
    for name in dir(client_cls):
        if name.startswith("_"):
            continue
        attr = getattr(client_cls, name, None)
        if not callable(attr):
            continue
        owner = _defining_class(client_cls, name)
        if owner is None or owner is object:
            continue
        if _is_base_infra_class_name(owner.__name__):
            continue
        methods[name] = owner
    return methods


def _camel_to_snake(name: str) -> str:
    s = re.sub(r"(.)([A-Z][a-z]+)", r"\1_\2", name)
    s = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", s)
    return s.lower()


def _derive_domains(owners: dict[str, type]) -> dict[str, str]:
    """Map each method to a snake_case domain tag from its defining class name.

    Strips the longest common prefix shared by the domain classes (the
    service prefix) so e.g. ``DemoApiItems``/``DemoApiUsers`` -> ``items``/``users``.
    """
    class_names = sorted({owner.__name__ for owner in owners.values()})
    common = ""
    if len(class_names) > 1:
        common = os.path.commonprefix(class_names)
        ref = class_names[0]
        k = len(common)
        while k > 0 and not ref[k : k + 1].isupper():
            k -= 1
        common = ref[:k]
    domains: dict[str, str] = {}
    for method, owner in owners.items():
        remainder = owner.__name__[len(common) :] if common else owner.__name__
        domains[method] = _camel_to_snake(remainder) or _camel_to_snake(owner.__name__)
    return domains


def _tool_name(method_name: str, prefix: str) -> str:
    """Avoid a doubled prefix when the method is already named with it."""
    if method_name == prefix or method_name.startswith(f"{prefix}_"):
        return method_name
    return f"{prefix}_{method_name}"


async def _resolve_client(get_client: Any) -> Any:
    client = get_client()
    if inspect.isawaitable(client):
        return await client
    return client


def _build_tool(method_name: str, get_client: Any, *, destructive: bool) -> Any:
    async def _tool(
        params_json: str = Field(
            default="{}", description="JSON object of arguments for this operation."
        ),
        ctx: Context | None = None,
    ) -> Any:
        kwargs = parse_json_object(params_json)
        kwargs = {k: v for k, v in kwargs.items() if v is not None}
        if destructive and not await ctx_confirm_destructive(ctx, method_name):
            return {"cancelled": True, "operation": method_name}
        client = await _resolve_client(get_client)
        return await invoke_client_method(getattr(client, method_name), **kwargs)

    return _tool


def register_method_tools(
    mcp: Any,
    client_cls: type,
    get_client: Any,
    *,
    prefix: str,
) -> list[str]:
    """Register one ``params_json``-dispatched tool per public method of ``client_cls``.

    Each tool is named ``<prefix>_<method>`` (no doubled prefix when a method
    already starts with it), tagged with a domain derived from the method's
    defining class and :data:`agent_connector_sdk.mcp.tool_surface.GRANULAR_TAG`.
    ``get_client`` is called fresh on every invocation (synchronous or
    returning an awaitable), the same per-call resolution a condensed
    action-routed tool already uses.

    Skips methods defined only on a base-infrastructure class (auth,
    pagination, retry machinery -- never a real operation). A method name
    :func:`agent_connector_sdk.mcp.action_dispatch.is_destructive_action`
    classifies destructive is gated behind a live caller's confirmation.

    Returns:
        The registered tool names, in method-iteration order.
    """
    owners = _domain_methods(client_cls)
    domains = _derive_domains(owners)
    registered: list[str] = []
    for method_name in owners:
        tool_name = _tool_name(method_name, prefix)
        destructive = is_destructive_action(method_name)
        tool_fn = _build_tool(method_name, get_client, destructive=destructive)
        tool_fn.__name__ = tool_name
        doc = getattr(client_cls, method_name).__doc__
        tool_fn.__doc__ = (doc or f"Invoke the {method_name} operation.").strip()
        mcp.tool(name=tool_name, tags={"verbose", domains[method_name], GRANULAR_TAG})(
            tool_fn
        )
        registered.append(tool_name)
    return registered
