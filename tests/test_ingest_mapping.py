"""Declared record mappers and shared field validation."""

from __future__ import annotations

import pytest

from scion_sdk.ingest import (
    EdgeMap,
    IngestError,
    Mapped,
    RecordMap,
    document_from_record,
    entity_from_record,
    ext_id,
    read_field,
    records_of,
    relationship_from_record,
    slug,
)

CONTACT = RecordMap(
    node_type="Contact",
    id_template="crm:Contact:{_id}",
    id_keys=("Id",),
    fields={"name": "Name", "city": "Address.City"},
    external_id="Id",
    constants={"source": "crm"},
    edges=(
        EdgeMap("worksAt", "AccountId", "crm:Account:{AccountId}"),
        EdgeMap(
            "ownedBy",
            "OwnerId",
            "crm:User:{OwnerId}",
            target_type="Person",
            target_fields={"name": "OwnerName"},
        ),
    ),
)


@pytest.mark.spec("SCION-SOURCE-INGEST-R004.30")
def test_record_map_builds_entities_and_edges() -> None:
    mapped = CONTACT(
        [
            {
                "Id": "1",
                "Name": "Ada",
                "Address": {"City": "X"},
                "AccountId": "a1",
                "OwnerId": "u1",
                "OwnerName": "Owner",
            },
            {"Id": "2", "Name": "Bo", "OwnerId": "u1", "OwnerName": "Owner"},
            {"Name": "no id"},
        ]
    )
    types = [(e.id, e.node_type) for e in mapped.entities]
    assert types == [
        ("crm:Contact:1", "Contact"),
        ("crm:User:u1", "Person"),
        ("crm:Contact:2", "Contact"),
    ]
    first = mapped.entities[0].properties
    assert first == {"name": "Ada", "city": "X", "source": "crm", "externalToolId": "1"}
    assert [(r.target, r.relationship) for r in mapped.relationships] == [
        ("crm:Account:a1", "worksAt"),
        ("crm:User:u1", "ownedBy"),
        ("crm:User:u1", "ownedBy"),
    ]


@pytest.mark.spec("SCION-SOURCE-INGEST-R004.30")
def test_strict_record_map_refuses_a_record_without_id() -> None:
    strict = RecordMap("Item", "x:{_id}", strict=True)
    with pytest.raises(IngestError):
        strict([{"name": "n"}])


@pytest.mark.spec("SCION-SOURCE-INGEST-R004.30")
def test_mapped_keeps_each_entity_once() -> None:
    mapped = Mapped().entity("a", "T", x=1).entity("a", "T", x=2).edge("a", "b", "r")
    assert len(mapped.entities) == 1
    assert mapped.relationships[0].properties is None


@pytest.mark.spec("SCION-SOURCE-INGEST-R004.30")
def test_validated_reads_raise_ingest_error() -> None:
    assert read_field({"a": 5}, "a") == "5"
    assert read_field({}, "a", required=False) is None
    with pytest.raises(IngestError):
        read_field({"a": ""}, "a")
    with pytest.raises(IngestError):
        read_field({"a": "x"}, "a", kind=dict)
    with pytest.raises(IngestError):
        entity_from_record({"id": "1"})
    with pytest.raises(IngestError):
        relationship_from_record({"source": "a", "target": "b"})
    with pytest.raises(IngestError):
        document_from_record({"id": "1"})


@pytest.mark.spec("SCION-SOURCE-INGEST-R004.30")
def test_record_helpers() -> None:
    entity = entity_from_record({"id": "1", "node_type": "T", "k": "v"})
    assert entity.properties == {"k": "v"}
    doc = document_from_record({"id": "d", "text": "t", "title": "T", "extra": 1})
    assert (doc.title, dict(doc.properties)) == ("T", {"extra": 1})
    assert records_of({"data": [{"a": 1}, 3]}) == [{"a": 1}]
    assert records_of([{"a": 1}]) == [{"a": 1}]
    assert records_of(None) == []
    assert ext_id({"a": "", "b": 7}, "a", "b") == "7"
    assert slug(" Hello, World! ") == "hello-world"
    assert slug("", default="d") == "d"
