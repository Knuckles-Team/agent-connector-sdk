"""Typed parameter shapes of operation tools, for :mod:`scion_sdk.mcp.method_tools`."""

from __future__ import annotations

import inspect
import keyword
import re
import types
import typing
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel, Field

from scion_sdk.mcp._method_introspect import _camel_to_snake

_JSON_TYPES: dict[str, Any] = {
    "string": str,
    "integer": int,
    "number": float,
    "boolean": bool,
    "array": list[Any],
    "object": dict[str, Any],
}


@dataclass(frozen=True)
class _ParamShape:
    """Typed keyword parameters of an operation and whether ``params_json`` extends them."""

    params: list[inspect.Parameter]
    extra_json: bool = False


def _type_hints(method: Callable[..., Any]) -> dict[str, Any]:
    try:
        return typing.get_type_hints(method, include_extras=True)
    except Exception:  # unresolved hints degrade to Any
        return {}


def _keyword_only(param: inspect.Parameter, hints: dict[str, Any]) -> inspect.Parameter:
    return inspect.Parameter(
        param.name,
        inspect.Parameter.KEYWORD_ONLY,
        default=param.default,
        annotation=hints.get(param.name, Any),
    )


def _method_parameters(method: Callable[..., Any]) -> _ParamShape | None:
    """Typed keyword parameters of ``method`` and whether it accepts ``**kwargs``.

    ``None`` means the method is a bare ``**kwargs`` method (no typed surface).
    """
    try:
        signature = inspect.signature(method)
    except (TypeError, ValueError):
        return None
    hints = _type_hints(method)
    declared = list(signature.parameters.values())
    if declared and declared[0].name in ("self", "cls"):
        declared = declared[1:]
    kinds = inspect.Parameter
    params = [
        _keyword_only(p, hints)
        for p in declared
        if p.kind not in (kinds.VAR_KEYWORD, kinds.VAR_POSITIONAL)
    ]
    var_keyword = any(p.kind is kinds.VAR_KEYWORD for p in declared)
    if not params and var_keyword:
        modelled = _kwargs_model_parameters(method)
        return _ParamShape(modelled) if modelled else None
    return _ParamShape(params, var_keyword)


_KWARGS_MODEL = re.compile(r"\b([A-Za-z_]\w*)\(\s*\*\*kwargs\s*\)")


def _kwargs_model_parameters(
    method: Callable[..., Any],
) -> list[inspect.Parameter] | None:
    """Parameters of the Pydantic model a bare ``**kwargs`` method validates through.

    A method shaped ``def op(self, **kwargs): model = OpModel(**kwargs)``
    takes exactly that model's fields.
    """
    target = inspect.unwrap(method)
    try:
        source = inspect.getsource(target)
    except (OSError, TypeError):
        return None
    names = set(_KWARGS_MODEL.findall(source))
    namespace = getattr(target, "__globals__", {})
    models = [
        namespace[name]
        for name in sorted(names)
        if isinstance(namespace.get(name), type)
        and issubclass(namespace[name], BaseModel)
    ]
    if len(models) != 1:
        return None
    params: list[inspect.Parameter] = []
    for name, field in models[0].model_fields.items():
        if not name.isidentifier():
            return None
        default = (
            inspect.Parameter.empty
            if field.is_required()
            else field.get_default(call_default_factory=True)
        )
        params.append(
            inspect.Parameter(
                name,
                inspect.Parameter.KEYWORD_ONLY,
                default=default,
                annotation=field.annotation,
            )
        )
    return params


def _declared_parameter(item: Mapping[str, Any]) -> tuple[inspect.Parameter, bool]:
    wire = str(item["name"])
    name = str(item.get("python_name") or _camel_to_snake(wire))
    schema = item.get("schema") or {}
    kind = _JSON_TYPES.get(str(schema.get("type")), Any)
    is_required = bool(item.get("required") or item.get("in") == "path")
    annotation: Any = kind if is_required else kind | None
    if keyword.iskeyword(wire) and name != wire:
        # A Python keyword (``from``) cannot be a parameter name: the parameter
        # keeps its python_name (``from_``) and the schema shows the wire name
        # through a pydantic field alias.
        annotation = typing.Annotated[annotation, Field(alias=wire)]
    return _keyword_parameter(name, annotation, required=is_required), is_required


def _keyword_parameter(
    name: str, annotation: Any, *, required: bool
) -> inspect.Parameter:
    if required:
        return inspect.Parameter(
            name, inspect.Parameter.KEYWORD_ONLY, annotation=annotation
        )
    return inspect.Parameter(
        name, inspect.Parameter.KEYWORD_ONLY, default=None, annotation=annotation
    )


def _body_parameter(body: Mapping[str, Any]) -> tuple[inspect.Parameter, bool]:
    is_required = bool(body.get("required"))
    annotation: Any = dict[str, Any] if is_required else dict[str, Any] | None
    name = str(body.get("python_name", "body"))
    return _keyword_parameter(name, annotation, required=is_required), is_required


def _manifest_parameters(
    operation: Mapping[str, Any],
) -> list[inspect.Parameter] | None:
    """Typed keyword parameters from an OpenAPI-shaped manifest entry."""
    declared = operation.get("parameters")
    body = operation.get("requestBody")
    if declared is None and body is None:
        return None
    parsed = [_declared_parameter(item) for item in declared or []]
    if body is not None:
        parsed.append(_body_parameter(body))
    return [p for p, req in parsed if req] + [p for p, req in parsed if not req]


_JSON_LEAVES = (str, int, float, bool, type(None))


def _is_plain_json(hint: Any) -> bool:
    if hint is Any or hint in _JSON_LEAVES:
        return True
    origin = typing.get_origin(hint)
    if origin in (dict, list, typing.Union, types.UnionType):
        return all(_is_plain_json(arg) for arg in typing.get_args(hint))
    return False


def _json_return(method: Callable[..., Any]) -> Any:
    """The method's return hint when it is plain JSON data, so it can be an output schema.

    Any other hint (a model, a raw response object) stays ``Any``: the default
    result coercer reshapes those values, so their hint is not the wire shape.
    """
    try:
        hint = typing.get_type_hints(method).get("return", Any)
    except Exception:  # unresolved hints have no output schema
        return Any
    if typing.get_origin(hint) not in (dict, list):
        return Any
    return hint if _is_plain_json(hint) else Any
