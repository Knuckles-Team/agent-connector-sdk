"""Tool bodies and result coercion for :mod:`scion_sdk.mcp.method_tools`."""

from __future__ import annotations

import inspect
from collections.abc import Callable
from typing import Any

from fastmcp import Context
from mcp.types import InputRequiredResult
from pydantic import Field
from pydantic_core import to_jsonable_python

from scion_sdk.mcp._method_params import _ParamShape
from scion_sdk.mcp.action_dispatch import parse_json_object
from scion_sdk.mcp.concurrency import invoke_client_method
from scion_sdk.mcp.context import ctx_confirm_destructive


def _fallback(value: Any) -> Any:
    status = getattr(value, "status_code", None)
    if isinstance(status, int):
        return {"status_code": status}
    return str(value)


def jsonable_result(result: Any) -> Any:
    """Default result coercion: JSON-ready data for any client return value.

    Pydantic models dump to JSON data, bytes encode as base64, and an
    unserializable object (a raw HTTP response) becomes its status code or text.
    """
    return to_jsonable_python(result, fallback=_fallback, bytes_mode="base64")


async def _resolve_client(get_client: Any) -> Any:
    client = get_client()
    if inspect.isawaitable(client):
        return await client
    return client


def _context_name(params: list[inspect.Parameter]) -> str:
    taken = {p.name for p in params}
    return "ctx" if "ctx" not in taken else "mcp_ctx"


async def _invoke(
    method_name: str,
    get_client: Any,
    *,
    kwargs: dict[str, Any],
    ctx: Any,
    destructive: bool,
    coercer: Callable[[Any], Any],
) -> Any:
    if destructive:
        confirmation = await ctx_confirm_destructive(
            ctx, method_name, confirmation_arguments=kwargs
        )
        if isinstance(confirmation, InputRequiredResult):
            return confirmation
        if confirmation is not True:
            return {"cancelled": True, "operation": method_name}
    client = await _resolve_client(get_client)
    result = await invoke_client_method(getattr(client, method_name), **kwargs)
    coerced = coercer(result)
    return await coerced if inspect.isawaitable(coerced) else coerced


def _typed_tool(
    method_name: str,
    get_client: Any,
    shape: _ParamShape,
    *,
    destructive: bool,
    coercer: Callable[[Any], Any],
    returns: Any = Any,
) -> Callable[..., Any]:
    """A tool whose signature mirrors the operation's typed parameters."""
    params = shape.params
    ctx_name = _context_name(params)
    declared = {p.name for p in params}

    async def _tool(**arguments: Any) -> Any:
        ctx = arguments.pop(ctx_name, None)
        extra = parse_json_object(arguments.pop("params_json", None))
        kwargs = {
            k: v
            for k, v in arguments.items()
            if k in declared and v is not None and v is not inspect.Parameter.empty
        }
        kwargs.update({k: v for k, v in extra.items() if v is not None})
        return await _invoke(
            method_name,
            get_client,
            kwargs=kwargs,
            ctx=ctx,
            destructive=destructive,
            coercer=coercer,
        )

    ordered = [p for p in params if p.default is inspect.Parameter.empty] + [
        p for p in params if p.default is not inspect.Parameter.empty
    ]
    if shape.extra_json:
        ordered.append(
            inspect.Parameter(
                "params_json",
                inspect.Parameter.KEYWORD_ONLY,
                default="{}",
                annotation=str,
            )
        )
    ordered.append(
        inspect.Parameter(
            ctx_name,
            inspect.Parameter.KEYWORD_ONLY,
            default=None,
            annotation=Context | None,
        )
    )
    _tool.__signature__ = inspect.Signature(  # type: ignore[attr-defined]
        ordered, return_annotation=returns
    )
    _tool.__annotations__ = {p.name: p.annotation for p in ordered} | {
        "return": returns
    }
    return _tool


def _untyped_tool(
    method_name: str,
    get_client: Any,
    *,
    destructive: bool,
    coercer: Callable[[Any], Any],
) -> Callable[..., Any]:
    """A ``params_json`` tool for an operation with no typed surface."""

    async def _tool(
        params_json: str = Field(
            default="{}", description="JSON object of arguments for this operation."
        ),
        ctx: Context | None = None,
    ) -> Any:
        kwargs = parse_json_object(params_json)
        kwargs = {k: v for k, v in kwargs.items() if v is not None}
        return await _invoke(
            method_name,
            get_client,
            kwargs=kwargs,
            ctx=ctx,
            destructive=destructive,
            coercer=coercer,
        )

    return _tool
