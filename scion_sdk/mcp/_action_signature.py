"""Build the per-action callable that fronts one branch of a routed tool."""

from __future__ import annotations

import inspect
import typing
from collections.abc import Callable
from typing import Any

from pydantic.fields import FieldInfo


def _plain_default(param: inspect.Parameter) -> Any:
    default = param.default
    if isinstance(default, FieldInfo):
        if default.default_factory is not None:
            return default.default_factory()  # type: ignore[call-arg]
        return None if default.is_required() else default.default
    return None if default is inspect.Parameter.empty else default


def _is_served(
    param: inspect.Parameter, hints: dict[str, Any], keep: set[str] | None
) -> bool:
    is_context = "Context" in str(hints.get(param.name, param.annotation))
    return keep is None or param.name in keep or is_context


def _partition(
    signature: inspect.Signature, hints: dict[str, Any], keep: set[str] | None
) -> tuple[list[inspect.Parameter], dict[str, Any]]:
    """The parameters a per-action tool serves, and defaults for the rest."""
    served: list[inspect.Parameter] = []
    omitted: dict[str, Any] = {}
    for param in signature.parameters.values():
        if param.name == "action":
            continue
        if _is_served(param, hints, keep):
            served.append(
                param.replace(annotation=hints.get(param.name, param.annotation))
            )
        else:
            omitted[param.name] = _plain_default(param)
    return served, omitted


def _per_action(
    tool: Any, action: str, keep: set[str] | None
) -> tuple[Callable[..., Any], list[str]]:
    fn = tool.fn
    signature = inspect.signature(fn)
    try:
        hints = typing.get_type_hints(fn, include_extras=True)
    except Exception:
        hints = dict(getattr(fn, "__annotations__", {}))
    served, omitted = _partition(signature, hints, keep)

    async def call(**kwargs: Any) -> Any:
        result = fn(action=action, **omitted, **kwargs)
        return await result if inspect.isawaitable(result) else result

    call.__signature__ = signature.replace(  # type: ignore[attr-defined]
        parameters=served,
        return_annotation=hints.get("return", signature.return_annotation),
    )
    call.__annotations__ = {
        k: v for k, v in hints.items() if k == "return" or k in {p.name for p in served}
    }
    call.__name__ = action
    call.__doc__ = fn.__doc__
    return call, [p.name for p in served]
