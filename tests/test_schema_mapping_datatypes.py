"""Explicit datatypes stay tied to a declared ontology target."""

import pytest
from pydantic import ValidationError

from scion_sdk.manifest.model import SchemaMapping


def test_mapping_preserves_legacy_shape_and_explicit_datetime():
    assert "datatypes" not in SchemaMapping(fields={"time": "observedAt"}).model_dump()
    mapping = SchemaMapping(
        fields={"time": "observedAt"}, datatypes={"time": "xsd:dateTime"}
    )
    assert mapping.model_dump()["datatypes"] == {"time": "xsd:dateTime"}


@pytest.mark.parametrize(
    "fields,datatypes",
    [
        ({}, {"time": "xsd:dateTime"}),
        ({"time": ""}, {"time": "xsd:dateTime"}),
        ({"time": "xsd:string"}, {"time": "xsd:dateTime"}),
        ({"time": "observedAt"}, {"time": "xsd:invented"}),
    ],
)
def test_mapping_refuses_unbound_or_unknown_datatypes(fields, datatypes):
    with pytest.raises(ValidationError):
        SchemaMapping(fields=fields, datatypes=datatypes)
