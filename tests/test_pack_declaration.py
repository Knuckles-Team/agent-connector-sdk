"""ConnectorPackDeclaration: typed model, round trip, nested-property refusal."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from scion_sdk.manifest.pack_declaration import (
    AccessPolicy,
    ConnectorPackDeclaration,
    CursorPolicy,
    DeclaredNode,
    FieldMapping,
    SourceObject,
)

_DECLARATION = {
    "connector": "widget-mcp",
    "contract_version": "1",
    "nodes": [
        {
            "kind": "tool",
            "name": "list_widgets",
            "domain_class_iri": "http://knuckles.team/kg#Widget",
        }
    ],
    "sources": [
        {
            "name": "widgets",
            "class_iri": "http://knuckles.team/kg#Widget",
            "field_mappings": [
                {
                    "field": "serial",
                    "property_iri": "http://knuckles.team/kg#serialNumber",
                }
            ],
            "key_fields": ["serial"],
            "cursor": {"mode": "cursor", "field": "next"},
            "access": {"method": "mcp_tool", "operation": "list_widgets"},
            "privacy_classes": ["internal"],
            "provenance_required": True,
            "served_by": ["list_widgets"],
        }
    ],
}


@pytest.mark.spec("SCION-CONNECTOR-CONTROL-R067.1")
def test_declaration_round_trip_and_nested_property_refusal() -> None:
    declaration = ConnectorPackDeclaration.model_validate(_DECLARATION)
    again = ConnectorPackDeclaration.model_validate(declaration.model_dump())
    assert again == declaration
    with pytest.raises(ValidationError):
        declaration.connector = "other"  # type: ignore[misc]

    nested = {**_DECLARATION, "sources": [{**_DECLARATION["sources"][0]}]}
    nested["sources"][0]["sourceProperties"] = {"color": "red"}  # type: ignore[index]
    with pytest.raises(ValidationError):
        ConnectorPackDeclaration.model_validate(nested)

    dangling = {**_DECLARATION, "sources": [{**_DECLARATION["sources"][0]}]}
    dangling["sources"][0]["served_by"] = ["missing_tool"]  # type: ignore[index]
    with pytest.raises(ValidationError, match="undeclared nodes"):
        ConnectorPackDeclaration.model_validate(dangling)

    unmapped = {**_DECLARATION, "sources": [{**_DECLARATION["sources"][0]}]}
    unmapped["sources"][0]["key_fields"] = ["id"]  # type: ignore[index]
    with pytest.raises(ValidationError, match="no field mapping"):
        ConnectorPackDeclaration.model_validate(unmapped)


@pytest.mark.spec("SCION-CONNECTOR-CONTROL-R067.1")
def test_components_build_a_declaration_directly() -> None:
    source = SourceObject(
        name="widgets",
        class_iri="http://knuckles.team/kg#Widget",
        field_mappings=(
            FieldMapping(
                field="serial", property_iri="http://knuckles.team/kg#serialNumber"
            ),
        ),
        key_fields=("serial",),
        cursor=CursorPolicy(mode="cursor", field="next"),
        access=AccessPolicy(method="mcp_tool", operation="list_widgets"),
        served_by=("list_widgets",),
    )
    node = DeclaredNode(
        kind="tool",
        name="list_widgets",
        domain_class_iri="http://knuckles.team/kg#Widget",
    )
    declaration = ConnectorPackDeclaration(
        connector="widget-mcp",
        contract_version="1",
        sources=(source,),
        nodes=(node,),
    )
    assert declaration.sources[0].cursor.mode == "cursor"
