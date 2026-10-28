"""Data-resource declarations of a connector pack (SDK-CONNECTOR-CONTROL-R074).

A :class:`ResourceDescriptor` states how one record type of the source is read
live: the ontology class, the field-to-property pairs, the access method, the
record identity field and the pagination form. epistemic-graph federates the
rows at query time from this declaration. The SDK never copies source rows.

A mapping is ``declared`` when the connector wrote it and ``proposed`` when
:mod:`agent_connector_sdk.artifacts.resource_derivation` matched names. A
proposed mapping is a candidate a steward approves; this module never marks
one approved.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any

from agent_connector_sdk.artifacts.resource_descriptor_model import (
    FieldBinding,
    ResourceDeclarationError,
    ResourceDescriptor,
    _validate,
)

__all__ = [
    "RESOURCES_URI",
    "FieldBinding",
    "ResourceDeclarationError",
    "ResourceDescriptor",
    "check_declarations",
    "merge_declarations",
    "render_resources_document",
]

#: The served resource that lists every data-resource descriptor.
RESOURCES_URI = "connector://resources"

_REQUIRED = ("name", "ontology_class", "operation", "key_field", "pagination")


def _binding(item: object) -> FieldBinding:
    if isinstance(item, str):
        return FieldBinding(name=item)
    if not isinstance(item, dict) or not isinstance(item.get("name"), str):
        raise ResourceDeclarationError("FIELD_INVALID", f"bad field entry {item!r}")
    prop = item.get("ontology_property")
    return FieldBinding(
        name=item["name"],
        type=str(item.get("type", "string")),
        ontology_property=prop if isinstance(prop, str) else None,
        mapping_status="declared" if isinstance(prop, str) else "unmapped",
    )


def _check_captured_descriptor(
    entry: Mapping[str, Any], classes: frozenset[str]
) -> None:
    """Reject an incomplete or unsafe data descriptor before pack creation."""
    refusal = _validate(entry, classes)
    if refusal is not None:
        raise refusal


def check_declarations(
    entries: list[dict[str, Any]], classes: frozenset[str] | None
) -> None:
    """Refuse a declaration that is wrong on its own, before any tool exists.

    Completeness is checked when the declaration is merged over the derived
    defaults, because a partial declaration may override a derived resource.

    Raises:
        ResourceDeclarationError: for the codes of :func:`merge_declarations`.
    """
    for entry in entries:
        checked = {
            key: value
            for key, value in {"pagination": "none", **entry}.items()
            if value is not None
        }
        if "ontology_class" not in checked and classes is not None:
            checked["ontology_class"] = next(iter(classes), None)
        refusal = _validate(checked, classes)
        if refusal is not None:
            raise refusal


def _declared(
    connector: str,
    entry: dict[str, Any],
    base: ResourceDescriptor | None,
) -> ResourceDescriptor:
    merged = base.to_json() if base else {}
    merged.update({k: v for k, v in entry.items() if v is not None})
    missing = [key for key in _REQUIRED if not merged.get(key)]
    if missing:
        raise ResourceDeclarationError(
            "DECLARATION_INCOMPLETE", f"{entry.get('name')}: missing {missing}"
        )
    name = str(merged["name"])
    fields = merged.get("fields") or ()
    return ResourceDescriptor(
        name=name,
        uri=f"data://{connector}/{name}",
        ontology_class=str(merged["ontology_class"]),
        mapping_status="declared",
        operation=str(merged["operation"]),
        key_field=str(merged["key_field"]),
        pagination=str(merged["pagination"]),
        origin="declared",
        fields=tuple(_binding(item) for item in fields),
        arguments=dict(merged.get("arguments") or {}),
        pagination_param=merged.get("pagination_param"),
        get_operation=merged.get("get_operation"),
        access_kind=str(merged.get("access_kind", "mcp_tool")),
        owner=merged.get("owner"),
        credential_ref=merged.get("credential_ref"),
    )


def merge_declarations(
    connector: str,
    derived: list[ResourceDescriptor],
    declared: list[dict[str, Any]],
    classes: frozenset[str] | None,
) -> tuple[ResourceDescriptor, ...]:
    """Derived defaults overlaid by the connector's declarations.

    A declaration with the name of a derived resource overrides its keys; any
    other declaration stands alone. Every declaration is validated.

    Raises:
        ResourceDeclarationError: ``RESOURCE_UNMAPPED``, ``ACCESS_KIND_UNKNOWN``,
            ``PAGINATION_UNDECLARED``, ``SECRET_IN_CONTRACT`` or an incomplete entry.
    """
    by_name = {descriptor.name: descriptor for descriptor in derived}
    for entry in declared:
        descriptor = _declared(connector, entry, by_name.get(str(entry.get("name"))))
        refusal = _validate(descriptor.to_json(), classes)
        if refusal is not None:
            raise refusal
        by_name[descriptor.name] = descriptor
    return tuple(sorted(by_name.values(), key=lambda d: d.name))


def render_resources_document(
    connector: str, descriptors: tuple[ResourceDescriptor, ...]
) -> str:
    """The body served at :data:`RESOURCES_URI`."""
    return json.dumps(
        {
            "connector": connector,
            "descriptors": [d.to_json() for d in descriptors],
        },
        sort_keys=True,
        indent=2,
    )
