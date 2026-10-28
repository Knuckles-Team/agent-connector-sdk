"""Validated resource descriptor model and serialization."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

from agent_connector_sdk.credentials.references import (
    SecretReferenceError,
    parse_secret_reference,
)

_RESOURCE_KINDS = frozenset({"data", "ontology", "shapes", "skill", "seed", "manifest"})
# Do not admit a newly described protocol into a captured pack until its
# transport has a certification boundary. Keep existing resource support.
_RESOURCE_ACCESS_KINDS = frozenset(
    {"mcp_tool", "http_endpoint", "graphql_query", "a2a_skill", "virtual_graph"}
)
_RESOURCE_PAGINATION_MODES = frozenset({"none", "cursor", "offset", "page"})


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

    def __post_init__(self) -> None:
        """Refuse unsafe values even when callers construct a descriptor directly."""
        if self.kind not in _RESOURCE_KINDS:
            raise ResourceDeclarationError(
                "RESOURCE_KIND_UNKNOWN", "unknown resource kind"
            )
        refusal = _validate(self.to_json(), None)
        if refusal is not None:
            raise refusal

    @classmethod
    def from_json(cls, document: Mapping[str, Any]) -> ResourceDescriptor:
        """Read the SDK's serialized descriptor and validate its contract."""
        values = dict(document)
        values["fields"] = tuple(
            FieldBinding(**field) for field in values.get("fields", ())
        )
        return cls(**values)

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


def _validate(
    entry: Mapping[str, Any], classes: frozenset[str] | None
) -> ResourceDeclarationError | None:
    """The refusal for one merged declaration, or ``None`` when it is sound."""
    name = entry.get("name")
    if entry.get("access_kind", "mcp_tool") not in _RESOURCE_ACCESS_KINDS:
        return ResourceDeclarationError(
            "ACCESS_KIND_UNKNOWN", f"{name}: unknown access_kind"
        )
    if entry.get("pagination") not in _RESOURCE_PAGINATION_MODES:
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
            parse_secret_reference(ref)
        except SecretReferenceError:
            raise ResourceDeclarationError(
                "SECRET_IN_CONTRACT", f"{name}: credential_ref must be a reference"
            ) from None
    return None
