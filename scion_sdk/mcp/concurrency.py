"""Run provider SDK calls from async MCP handlers without blocking the loop.

Extracted from ``agent_utilities.mcp.concurrency``. Fleet MCP tools are
``async def`` while provider clients may be synchronous or asynchronous.
:func:`run_blocking` is the strict synchronous primitive and
:func:`invoke_client_method` awaits asynchronous methods and offloads
synchronous ones to a worker thread.
"""

from __future__ import annotations

import functools
import inspect
from collections.abc import Awaitable, Callable
from typing import Any, cast

import anyio

__all__ = ["fold_body_arguments", "invoke_client_method", "run_blocking"]

#: Names fleet API-client methods use for their single REST-body parameter.
_BODY_PARAM_NAMES = ("data", "payload", "body")
_NAMED_KINDS = (inspect.Parameter.POSITIONAL_OR_KEYWORD, inspect.Parameter.KEYWORD_ONLY)


def _body_parameter(func: Callable[..., Any]) -> tuple[str, frozenset[str]] | None:
    """The single body parameter name and all named parameters, when unambiguous."""
    try:
        params = inspect.signature(func).parameters
    except (TypeError, ValueError):
        return None
    if any(p.kind is inspect.Parameter.VAR_KEYWORD for p in params.values()):
        return None
    body = [name for name in _BODY_PARAM_NAMES if name in params]
    if len(body) != 1:
        return None
    named = frozenset(name for name, p in params.items() if p.kind in _NAMED_KINDS)
    return body[0], named


def fold_body_arguments(
    func: Callable[..., Any], args: tuple[Any, ...], kwargs: dict[str, Any]
) -> dict[str, Any]:
    """Fold stray keyword fields into the target's single REST-body parameter.

    Action-routed tools pass a model's free-form ``params_json`` fields as flat
    keyword arguments. When ``func`` declares exactly one of ``data``,
    ``payload`` or ``body``, that parameter was not supplied, and some keywords
    match no named parameter, those keywords are collected into it. Every other
    call is returned unchanged.
    """
    shape = None if args or not kwargs else _body_parameter(func)
    if shape is None or shape[0] in kwargs:
        return kwargs
    body, named = shape
    stray = {key: value for key, value in kwargs.items() if key not in named}
    if not stray:
        return kwargs
    folded = {key: value for key, value in kwargs.items() if key in named}
    folded[body] = stray
    return folded


async def run_blocking[T](func: Callable[..., T], /, *args: Any, **kwargs: Any) -> T:
    """Run a synchronous callable in a worker thread and return its result.

    Raises:
        TypeError: ``func`` is a coroutine function or returns an awaitable;
            use :func:`invoke_client_method` for those.
    """
    if inspect.iscoroutinefunction(func):
        raise TypeError("run_blocking requires a synchronous callable")
    call = functools.partial(func, *args, **fold_body_arguments(func, args, kwargs))
    result = await anyio.to_thread.run_sync(call)
    if inspect.isawaitable(result):
        if inspect.iscoroutine(result):
            result.close()
        raise TypeError("run_blocking callable returned an awaitable")
    return result


async def invoke_client_method[T](
    func: Callable[..., T | Awaitable[T]], /, *args: Any, **kwargs: Any
) -> T:
    """Invoke one provider SDK method without blocking the event loop.

    Coroutine functions run on the loop. Synchronous callables run in a worker
    thread; an awaitable they return is awaited as well.
    """
    call_kwargs = fold_body_arguments(func, args, kwargs)
    if inspect.iscoroutinefunction(func):
        return cast(T, await func(*args, **call_kwargs))
    result = await anyio.to_thread.run_sync(
        functools.partial(func, *args, **call_kwargs)
    )
    if inspect.isawaitable(result):
        return await cast(Awaitable[T], result)
    return result
