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
from dataclasses import dataclass, field
from typing import Any

from agent_connector_sdk._contract_fields import ACCESS_KINDS, PAGINATION_MODES
from agent_connector_sdk.credentials.references import (
    SecretReferenceError,
    parse_secret_reference,
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


class ResourceDeclarationError(ValueError):
    """A declared data resource is refused; ``code`` names the reason."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(f"{code}: {message}")
        self.code = code


@dataclass(frozen=True)
class FieldBinding:
    """One response field and the ontology property it carries."""

    name: str
    type: str = "string"
    ontology_property: str | None = None
    mapping_status: str = "unmapped"

    def to_json(self) -> dict[str, Any]:
        """The field as a JSON object."""
        return {
            "name": self.name,
            "type": self.type,
            "ontology_property": self.ontology_property,
            "mapping_status": self.mapping_status,
        }


@dataclass(frozen=True)
class ResourceDescriptor:
    """One data resource of the connector and the contract to read it live."""

    name: str
    uri: str
    ontology_class: str | None
    mapping_status: str
    operation: str
    key_field: str
    pagination: str
    origin: str
    fields: tuple[FieldBinding, ...] = ()
    arguments: Mapping[str, str] = field(default_factory=dict)
    pagination_param: str | None = None
    get_operation: str | None = None
    access_kind: str = "mcp_tool"
    kind: str = "data"
    read_only: bool = True
    owner: str | None = None
    credential_ref: str | None = None

    def to_json(self) -> dict[str, Any]:
        """The descriptor as a JSON object."""
        return {
            "name": self.name,
            "uri": self.uri,
            "kind": self.kind,
            "origin": self.origin,
            "ontology_class": self.ontology_class,
            "mapping_status": self.mapping_status,
            "fields": [binding.to_json() for binding in self.fields],
            "access_kind": self.access_kind,
            "operation": self.operation,
            "get_operation": self.get_operation,
            "arguments": dict(self.arguments),
            "key_field": self.key_field,
            "pagination": self.pagination,
            "pagination_param": self.pagination_param,
            "read_only": self.read_only,
            "owner": self.owner,
            "credential_ref": self.credential_ref,
        }


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


def _validate(
    entry: Mapping[str, Any], classes: frozenset[str] | None
) -> ResourceDeclarationError | None:
    """The refusal for one merged declaration, or ``None`` when it is sound."""
    name = entry.get("name")
    if entry.get("access_kind", "mcp_tool") not in ACCESS_KINDS:
        return ResourceDeclarationError(
            "ACCESS_KIND_UNKNOWN", f"{name}: unknown access_kind"
        )
    if entry.get("pagination") not in PAGINATION_MODES:
        return ResourceDeclarationError(
            "PAGINATION_UNDECLARED",
            f"{name}: pagination must be one of cursor, page, offset or none",
        )
    if classes is not None and entry.get("ontology_class") not in classes:
        return ResourceDeclarationError(
            "RESOURCE_UNMAPPED",
            f"{name}: {entry.get('ontology_class')!r} is not declared in the ontology",
        )
    ref = entry.get("credential_ref")
    if ref is not None:
        try:
            parse_secret_reference(str(ref))
        except SecretReferenceError as exc:
            raise ResourceDeclarationError(
                "SECRET_IN_CONTRACT", f"{name}: credential_ref must be a reference"
            ) from exc
    return None


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
