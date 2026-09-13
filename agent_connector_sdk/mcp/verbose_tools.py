"""Register one verbose MCP tool per API client method.

Extracted from ``agent_utilities.mcp.verbose_tools.register_verbose_tools``. A
method with a manifest operation listing typeable parameters gets a fully typed
tool; every other method gets a ``params_json`` tool. The live client is bound
per call through ``Depends(get_client)``, so no credentials are needed at
registration time. Destructive methods require an affirmative elicitation.
"""

from __future__ import annotations

import inspect
import keyword
import logging
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from fastmcp import Context
from fastmcp.dependencies import Depends
from pydantic import Field

from agent_connector_sdk.mcp.action_dispatch import (
    is_destructive_action,
    parse_json_object,
)
from agent_connector_sdk.mcp.concurrency import invoke_client_method
from agent_connector_sdk.mcp.context import ctx_confirm_destructive
from agent_connector_sdk.mcp.tool_mode import GRANULAR_TAG
from agent_connector_sdk.mcp.verbose_naming import (
    derive_domains,
    domain_methods,
    service_tool_prefix,
    verbose_tool_name,
)

__all__ = ["register_verbose_tools"]

_logger = logging.getLogger(__name__)

_PY_TYPES: dict[str, type] = {
    "string": str,
    "integer": int,
    "number": float,
    "boolean": bool,
    "array": list,
    "object": dict,
}
_RESERVED_PARAM_NAMES = frozenset({"client", "ctx", "self"})
_KEYWORD_ONLY = inspect.Parameter.KEYWORD_ONLY


def _is_typeable(param: dict[str, Any]) -> bool:
    name = param.get("name")
    return (
        isinstance(name, str)
        and name.isidentifier()
        and not keyword.iskeyword(name)
        and name not in _RESERVED_PARAM_NAMES
    )


@dataclass(frozen=True)
class _ToolSpec:
    method_name: str
    get_client: Any
    destructive: bool


async def _invoke(
    spec: _ToolSpec, client: Any, *, ctx: Any, kwargs: dict[str, Any]
) -> Any:
    arguments = {key: value for key, value in kwargs.items() if value is not None}
    if spec.destructive and not await ctx_confirm_destructive(ctx, spec.method_name):
        return {"cancelled": True, "operation": spec.method_name}
    return await invoke_client_method(getattr(client, spec.method_name), **arguments)


def _params_json_tool(spec: _ToolSpec) -> Callable[..., Any]:
    params_field = Field(
        default="{}", description="JSON object of arguments for this operation."
    )
    client_dependency = Depends(spec.get_client)

    async def _tool(
        params_json: str = params_field,
        client: Any = client_dependency,
        ctx: Context | None = None,
    ) -> Any:
        return await _invoke(
            spec, client, ctx=ctx, kwargs=parse_json_object(params_json)
        )

    return _tool


def _typed_parameter(param: dict[str, Any]) -> inspect.Parameter:
    py_type = _PY_TYPES.get(str(param.get("type", "string")).lower(), str)
    description = param.get("description") or ""
    if param.get("required"):
        default = Field(description=description)
        return inspect.Parameter(
            param["name"], _KEYWORD_ONLY, default=default, annotation=py_type
        )
    optional = Field(default=None, description=description)
    return inspect.Parameter(
        param["name"], _KEYWORD_ONLY, default=optional, annotation=py_type | None
    )


def _typed_tool(spec: _ToolSpec, params: list[dict[str, Any]]) -> Callable[..., Any]:
    async def _tool(**call: Any) -> Any:
        client = call.pop("client")
        ctx = call.pop("ctx", None)
        return await _invoke(spec, client, ctx=ctx, kwargs=call)

    parameters = [_typed_parameter(param) for param in params]
    parameters.append(
        inspect.Parameter("client", _KEYWORD_ONLY, default=Depends(spec.get_client))
    )
    parameters.append(
        inspect.Parameter("ctx", _KEYWORD_ONLY, default=None, annotation=Context | None)
    )
    _tool.__dict__["__signature__"] = inspect.Signature(parameters)
    _tool.__annotations__ = {
        **{parameter.name: parameter.annotation for parameter in parameters},
        "client": Any,
        "return": Any,
    }
    return _tool


@dataclass(frozen=True)
class _Registration:
    mcp: Any
    client_cls: type
    get_client: Any
    prefix: str
    domain_map: dict[str, str]
    domains: dict[str, str]


def _tool_doc(
    registration: _Registration, method_name: str, operation: dict[str, Any]
) -> str:
    method = getattr(registration.client_cls, method_name, None)
    doc = operation.get("summary") or operation.get("description")
    if not doc and not operation.get("params"):
        doc = getattr(method, "__doc__", None)
    return str(doc or f"Invoke the {method_name} operation.").strip()


def _register_one(
    registration: _Registration, method_name: str, operation: dict[str, Any]
) -> str:
    spec = _ToolSpec(
        method_name=method_name,
        get_client=registration.get_client,
        destructive=is_destructive_action(method_name, operation),
    )
    params = operation.get("params") or []
    typed = bool(params) and all(_is_typeable(param) for param in params)
    tool_fn = _typed_tool(spec, params) if typed else _params_json_tool(spec)
    tool_name = verbose_tool_name(method_name, registration.prefix)
    tool_fn.__name__ = tool_name
    tool_fn.__doc__ = _tool_doc(registration, method_name, operation)
    domain = (
        registration.domain_map.get(method_name)
        or operation.get("domain")
        or registration.domains.get(method_name, "api")
    )
    registration.mcp.tool(name=tool_name, tags={"verbose", domain, GRANULAR_TAG})(
        tool_fn
    )
    return tool_name


def register_verbose_tools(
    mcp: Any,
    client_cls: type,
    get_client: Any,
    *,
    service: str,
    tool_prefix: str | None = None,
    domain_map: dict[str, str] | None = None,
    manifest: list[dict[str, Any]] | None = None,
) -> list[str]:
    """Register one verbose MCP tool per public API method of ``client_cls``.

    Manifest operations name methods (``{"method", "domain"?, "summary"?,
    "params"?}``); an operation whose method the client lacks is skipped with a
    warning, since its tool could only fail.

    Returns:
        The registered tool names, sorted by method.
    """
    owners = domain_methods(client_cls)
    by_method = {op["method"]: op for op in (manifest or []) if op.get("method")}
    registration = _Registration(
        mcp=mcp,
        client_cls=client_cls,
        get_client=get_client,
        prefix=tool_prefix or service_tool_prefix(service),
        domain_map=dict(domain_map or {}),
        domains=derive_domains(owners),
    )
    registered: list[str] = []
    for method_name in sorted(set(owners) | set(by_method)):
        if method_name not in owners and not hasattr(client_cls, method_name):
            _logger.warning(
                "manifest method %r is not on %s", method_name, client_cls.__name__
            )
            continue
        registered.append(
            _register_one(registration, method_name, by_method.get(method_name, {}))
        )
    return registered
