"""One typed, annotated MCP tool per API operation of a connector's client class.

SDK-CONNECTOR-CONTROL-R020 makes this the connector standard: every public
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
:func:`agent_connector_sdk.mcp.context.ctx_confirm_destructive` before the
client is called (SDK-CONNECTOR-CONTROL-R026.1).
"""

from __future__ import annotations

import inspect
import keyword
import os.path
import re
import types
import typing
from collections.abc import Callable, Mapping
from typing import Any

from fastmcp import Context
from mcp.types import InputRequiredResult, ToolAnnotations
from pydantic import BaseModel, Field
from pydantic_core import to_jsonable_python

from agent_connector_sdk.mcp.action_dispatch import (
    is_destructive_action,
    parse_json_object,
)
from agent_connector_sdk.mcp.concurrency import invoke_client_method
from agent_connector_sdk.mcp.context import ctx_confirm_destructive

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

_VERBS = ("GET", "HEAD", "POST", "PUT", "PATCH", "DELETE")
_DOC_VERB = re.compile(r"^\s*(GET|HEAD|POST|PUT|PATCH|DELETE)\s+/", re.MULTILINE)
_LITERAL_VERB = re.compile(r"""["'](GET|HEAD|POST|PUT|PATCH|DELETE)["']""")
_CALL_VERB = re.compile(
    r"\b\w*(?:session|client|http|requests)\w*\.(get|head|post|put|patch|delete)\("
)
_READ_TOKENS = frozenset(
    {"get", "list", "search", "read", "fetch", "find", "query", "count", "ping"}
)
_JSON_TYPES: dict[str, Any] = {
    "string": str,
    "integer": int,
    "number": float,
    "boolean": bool,
    "array": list[Any],
    "object": dict[str, Any],
}


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
        if not callable(attr) or isinstance(attr, type):
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
    return re.sub(r"\W+", "_", s).strip("_").lower()


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


def operation_verb(
    method: Callable[..., Any], operation: Mapping[str, Any] | None = None
) -> str | None:
    """The HTTP verb an operation sends, or ``None`` when it cannot be known.

    Precedence: the manifest ``http`` field, an ``__http_method__`` attribute,
    a ``VERB /path`` docstring line, then the single verb the method body
    sends (a quoted verb literal or a ``<session>.<verb>(`` call).
    """
    if operation and str(operation.get("http", "")).upper() in _VERBS:
        return str(operation["http"]).upper()
    declared = str(getattr(method, "__http_method__", "")).upper()
    if declared in _VERBS:
        return declared
    match = _DOC_VERB.search(inspect.getdoc(method) or "")
    if match:
        return match.group(1)
    target = inspect.unwrap(method)
    try:
        source = inspect.getsource(target)
    except (OSError, TypeError):
        return None
    body = source.split(":", 1)[-1]
    found = {m.upper() for m in _LITERAL_VERB.findall(body)}
    found |= {m.upper() for m in _CALL_VERB.findall(body)}
    return found.pop() if len(found) == 1 else None


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


def _method_parameters(
    method: Callable[..., Any],
) -> tuple[list[inspect.Parameter], bool] | None:
    """Typed keyword parameters of ``method`` and whether it accepts ``**kwargs``.

    ``None`` means the method is a bare ``**kwargs`` method (no typed surface).
    """
    try:
        signature = inspect.signature(method)
    except (TypeError, ValueError):
        return None
    try:
        hints = typing.get_type_hints(method, include_extras=True)
    except Exception:  # unresolved hints degrade to Any
        hints = {}
    params: list[inspect.Parameter] = []
    var_keyword = False
    for index, param in enumerate(signature.parameters.values()):
        if index == 0 and param.name in ("self", "cls"):
            continue
        if param.kind is inspect.Parameter.VAR_KEYWORD:
            var_keyword = True
            continue
        if param.kind is inspect.Parameter.VAR_POSITIONAL:
            continue
        params.append(
            inspect.Parameter(
                param.name,
                inspect.Parameter.KEYWORD_ONLY,
                default=param.default,
                annotation=hints.get(param.name, Any),
            )
        )
    if not params and var_keyword:
        modelled = _kwargs_model_parameters(method)
        return (modelled, False) if modelled else None
    return params, var_keyword


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


def _manifest_parameters(
    operation: Mapping[str, Any],
) -> list[inspect.Parameter] | None:
    """Typed keyword parameters from an OpenAPI-shaped manifest entry."""
    declared = operation.get("parameters")
    body = operation.get("requestBody")
    if declared is None and body is None:
        return None
    required: list[inspect.Parameter] = []
    optional: list[inspect.Parameter] = []
    for item in declared or []:
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
        if is_required:
            required.append(
                inspect.Parameter(
                    name, inspect.Parameter.KEYWORD_ONLY, annotation=annotation
                )
            )
        else:
            optional.append(
                inspect.Parameter(
                    name,
                    inspect.Parameter.KEYWORD_ONLY,
                    default=None,
                    annotation=annotation,
                )
            )
    if body is not None:
        body_name = str(body.get("python_name", "body"))
        if body.get("required"):
            required.append(
                inspect.Parameter(
                    body_name, inspect.Parameter.KEYWORD_ONLY, annotation=dict[str, Any]
                )
            )
        else:
            optional.append(
                inspect.Parameter(
                    body_name,
                    inspect.Parameter.KEYWORD_ONLY,
                    default=None,
                    annotation=dict[str, Any] | None,
                )
            )
    return required + optional


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


def _context_name(params: list[inspect.Parameter]) -> str:
    taken = {p.name for p in params}
    return "ctx" if "ctx" not in taken else "mcp_ctx"


async def _invoke(
    method_name: str,
    get_client: Any,
    kwargs: dict[str, Any],
    ctx: Any,
    *,
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
    params: list[inspect.Parameter],
    *,
    extra_json: bool,
    destructive: bool,
    coercer: Callable[[Any], Any],
    returns: Any = Any,
) -> Callable[..., Any]:
    """A tool whose signature mirrors the operation's typed parameters."""
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
            kwargs,
            ctx,
            destructive=destructive,
            coercer=coercer,
        )

    ordered = [p for p in params if p.default is inspect.Parameter.empty] + [
        p for p in params if p.default is not inspect.Parameter.empty
    ]
    if extra_json:
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
            kwargs,
            ctx,
            destructive=destructive,
            coercer=coercer,
        )

    return _tool


def _description(method: Callable[..., Any], operation: Mapping[str, Any]) -> str:
    text = operation.get("summary") or operation.get("description")
    if not text:
        text = inspect.getdoc(method)
    return str(text or f"Invoke the {method.__name__} operation.").strip()


def _manifest_index(
    manifest: list[dict[str, Any]] | None,
) -> dict[str, dict[str, Any]]:
    index: dict[str, dict[str, Any]] = {}
    for entry in manifest or []:
        method = entry.get("method")
        if not method:
            raise ValueError("every manifest entry must name its client 'method'")
        if method in index:
            raise ValueError(f"duplicate manifest entry for method {method!r}")
        index[str(method)] = entry
    return index


def operation_tool_names(
    client_cls: type, *, prefix: str, manifest: list[dict[str, Any]] | None = None
) -> dict[str, str]:
    """``{method: tool_name}`` for every operation :func:`register_method_tools` serves."""
    operations = _manifest_index(manifest)
    return {
        method_name: _tool_name(
            str(operations.get(method_name, {}).get("name") or method_name), prefix
        )
        for method_name in _domain_methods(client_cls)
    }


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
        method = getattr(client_cls, method_name)
        operation = operations.get(method_name, {})
        tool_name = _tool_name(str(operation.get("name") or method_name), prefix)
        if tool_name in existing:
            raise ValueError(f"operation tool name collides: {tool_name!r}")
        verb = operation_verb(method, operation)
        destructive = verb == "DELETE" or is_destructive_action(method_name, operation)
        options = {
            "name": tool_name,
            "description": _description(method, operation),
            "tags": {domains[method_name], OPERATION_TAG, GRANULAR_TAG, GATED_TAG},
            "annotations": operation_annotations(method_name, verb),
        }
        shape = _manifest_parameters(operation)
        typed = (shape, False) if shape is not None else _method_parameters(method)
        try:
            if typed is None:
                raise TypeError("no typed parameters")
            mcp.tool(**options)(
                _typed_tool(
                    method_name,
                    get_client,
                    typed[0],
                    extra_json=typed[1],
                    destructive=destructive,
                    coercer=coercer,
                    returns=_json_return(method) if result_coercer is None else Any,
                )
            )
        except (TypeError, ValueError) as error:
            if tool_name in _registered_names(mcp):
                raise ValueError(f"operation tool {tool_name!r}: {error}") from error
            mcp.tool(**options)(
                _untyped_tool(
                    method_name, get_client, destructive=destructive, coercer=coercer
                )
            )
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
