"""Operation discovery, naming and HTTP-verb inference for :mod:`scion_sdk.mcp.method_tools`."""

from __future__ import annotations

import inspect
import os.path
import re
from collections.abc import Callable, Mapping
from typing import Any

_VERBS = ("GET", "HEAD", "POST", "PUT", "PATCH", "DELETE")
_DOC_VERB = re.compile(r"^\s*(GET|HEAD|POST|PUT|PATCH|DELETE)\s+/", re.MULTILINE)
_LITERAL_VERB = re.compile(r"""["'](GET|HEAD|POST|PUT|PATCH|DELETE)["']""")
_CALL_VERB = re.compile(
    r"\b\w*(?:session|client|http|requests)\w*\.(get|head|post|put|patch|delete)\("
)


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
