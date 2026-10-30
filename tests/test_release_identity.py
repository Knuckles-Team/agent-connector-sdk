"""Live release identity binds both the declaration and ontology."""

import pytest
from rdflib import BNode, Graph, Literal, URIRef

from scion_sdk.ingest.sources import IngestSourceDeclaration
from scion_sdk.manifest.release_identity import release_identity_digest


def graph(reverse: bool = False) -> Graph:
    result = Graph()
    node = BNode()
    triples = [
        (URIRef("urn:example:subject"), URIRef("urn:example:link"), node),
        (node, URIRef("urn:example:name"), Literal("value")),
    ]
    for triple in reversed(triples) if reverse else triples:
        result.add(triple)
    return result


@pytest.mark.spec("SCION-CONNECTOR-CONTROL-R650.2")
def test_release_digest_binds_live_declaration_and_graph() -> None:
    first = IngestSourceDeclaration.model_validate(
        {"connector": "example", "descriptors": [{"a": 1, "b": 2}]}
    )
    reordered = IngestSourceDeclaration.model_validate(
        {"descriptors": [{"b": 2, "a": 1}], "connector": "example"}
    )
    digest = release_identity_digest(first, graph())
    assert digest == release_identity_digest(reordered, graph(reverse=True))
    changed = first.model_copy(update={"connector": "other"})
    assert digest != release_identity_digest(changed, graph())
    altered_graph = graph()
    altered_graph.add((URIRef("urn:a"), URIRef("urn:b"), Literal("changed")))
    assert digest != release_identity_digest(first, altered_graph)


@pytest.mark.spec("SCION-CONNECTOR-CONTROL-R650.2")
def test_release_digest_rejects_nonfinite_declaration_numbers() -> None:
    invalid = IngestSourceDeclaration.model_validate(
        {"connector": "example", "descriptors": [{"value": float("nan")}]}
    )
    with pytest.raises(ValueError):
        release_identity_digest(invalid, graph())


@pytest.mark.spec("SCION-CONNECTOR-CONTROL-R650.2")
def test_release_digest_refuses_nonstring_keys() -> None:
    invalid = IngestSourceDeclaration.model_validate(
        {"connector": "example", "descriptors": [{"nested": {1: "value"}}]}
    )
    with pytest.raises(ValueError):
        release_identity_digest(invalid, graph())
