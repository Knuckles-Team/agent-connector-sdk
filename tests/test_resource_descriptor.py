"""The live descriptor model validates and round-trips resource contracts."""

import pytest

from agent_connector_sdk.artifacts.resource_descriptor import (
    FieldBinding,
    ResourceDeclarationError,
    ResourceDescriptor,
)


def _descriptor(**changes):
    values = {
        "name": "tickets",
        "uri": "data://demo/tickets",
        "ontology_class": "https://example.org/Ticket",
        "mapping_status": "declared",
        "operation": "list_tickets",
        "key_field": "id",
        "pagination": "cursor",
        "origin": "declared",
        "fields": (FieldBinding("id", ontology_property="https://example.org/id"),),
        "owner": "support",
        "credential_ref": "env://TICKET_TOKEN",
        "access_kind": "http_endpoint",
    }
    return ResourceDescriptor(**(values | changes))


@pytest.mark.spec("SDK-CONNECTOR-CONTROL-R074.1")
def test_descriptor_round_trips_and_names_only_a_credential_reference():
    descriptor = _descriptor()
    assert ResourceDescriptor.from_json(descriptor.to_json()) == descriptor
    for kind in ("data", "ontology", "shapes", "skill", "seed", "manifest"):
        assert (
            ResourceDescriptor.from_json(_descriptor(kind=kind).to_json()).kind == kind
        )
    with pytest.raises(ResourceDeclarationError, match="RESOURCE_KIND_UNKNOWN"):
        _descriptor(kind="invalid")
    with pytest.raises(ResourceDeclarationError, match="ACCESS_KIND_UNKNOWN"):
        _descriptor(access_kind="carrier_pigeon")
    secret = (
        "private-literal-value"  # sanitizer:ignore - synthetic invalid test fixture
    )
    with pytest.raises(ResourceDeclarationError, match="SECRET_IN_CONTRACT") as failure:
        _descriptor(credential_ref=secret)
    assert secret not in str(failure.value)
    with pytest.raises(ResourceDeclarationError, match="SECRET_IN_CONTRACT"):
        ResourceDescriptor.from_json(
            _descriptor().to_json() | {"credential_ref": secret}
        )
