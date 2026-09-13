"""Names and domain tags for verbose 1:1 tools derived from an API client class."""

from __future__ import annotations

import os.path
import re

__all__ = [
    "derive_domains",
    "domain_methods",
    "service_tool_prefix",
    "verbose_tool_name",
]


def _camel_to_snake(name: str) -> str:
    text = re.sub(r"(.)([A-Z][a-z]+)", r"\1_\2", name)
    return re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", text).lower()


def service_tool_prefix(service: str) -> str:
    """``servicenow-api`` becomes ``servicenow``: the tool-name prefix."""
    prefix = service.strip().lower()
    for suffix in ("-api", "-mcp", "-agent"):
        if prefix.endswith(suffix):
            prefix = prefix[: -len(suffix)]
            break
    return re.sub(r"[^0-9a-z]+", "_", prefix).strip("_") or "tool"


def _defining_class(client_cls: type, name: str) -> type | None:
    return next((klass for klass in client_cls.__mro__ if name in klass.__dict__), None)


def _is_api_method(client_cls: type, name: str) -> bool:
    """Public, callable, and not defined on ``object`` or a base-infra class.

    Base infrastructure (auth, pagination, retry) lives on a class named
    ``*Base`` or ``Base*``; it is never an API operation.
    """
    if name.startswith("_") or not callable(getattr(client_cls, name, None)):
        return False
    owner = _defining_class(client_cls, name)
    if owner is None or owner is object:
        return False
    core = owner.__name__.lstrip("_")
    return not (core.endswith("Base") or core.startswith("Base"))


def domain_methods(client_cls: type) -> dict[str, type]:
    """Public API methods of ``client_cls`` mapped to their defining class."""
    return {
        name: owner
        for name in dir(client_cls)
        if _is_api_method(client_cls, name)
        and (owner := _defining_class(client_cls, name)) is not None
    }


def _common_class_prefix(class_names: list[str]) -> str:
    if len(class_names) < 2:
        return ""
    reference = class_names[0]
    boundary = len(os.path.commonprefix(class_names))
    while boundary > 0 and not reference[boundary : boundary + 1].isupper():
        boundary -= 1
    return reference[:boundary]


def derive_domains(owners: dict[str, type]) -> dict[str, str]:
    """Map each method to a snake_case domain from its defining class name.

    The CamelCase prefix shared by all defining classes (the service name) is
    stripped: ``ServiceNowApiCmdb`` becomes ``cmdb``.
    """
    common = _common_class_prefix(sorted({owner.__name__ for owner in owners.values()}))
    return {
        method: _camel_to_snake(owner.__name__[len(common) :])
        or _camel_to_snake(owner.__name__)
        for method, owner in owners.items()
    }


def verbose_tool_name(method_name: str, prefix: str) -> str:
    """``<prefix>_<method>``, without doubling a prefix the method already has."""
    if method_name == prefix or method_name.startswith(f"{prefix}_"):
        return method_name
    return f"{prefix}_{method_name}"
