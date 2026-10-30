"""Validate captured data surfaces and render their access contract."""

from collections.abc import Sequence
from typing import Any

from epistemic_graph.connector_pack import ConnectorPackEntryContent
from epistemic_graph.generated.connector_pack import PackEntryKind

from scion_sdk.artifacts.common import json_object
from scion_sdk.artifacts.resource_descriptor import (
    RESOURCES_URI,
    _check_captured_descriptor,
)
from scion_sdk.artifacts.source_contract import render_source_contract
from scion_sdk.contracts import CapturedArtifact
from scion_sdk.ports.errors import MalformedArtifactError


def _source_contract_entries(
    entries: Sequence[CapturedArtifact], connector: str
) -> tuple[ConnectorPackEntryContent, ...]:
    declaration = next((entry for entry in entries if entry.uri == RESOURCES_URI), None)
    descriptors = json_object(declaration).get("descriptors", []) if declaration else []
    _validate_data_entries(entries, descriptors)
    contract_entries: tuple[ConnectorPackEntryContent, ...] = ()
    if descriptors:
        contract_uri = f"contract://{connector}"
        if any(entry.uri == contract_uri for entry in entries):
            raise MalformedArtifactError("a content URI is served more than once")
        contract_entries = (
            ConnectorPackEntryContent(
                kind=PackEntryKind.RESOURCE,
                uri=contract_uri,
                name="source-contract",
                media_type="text/turtle",
                body=render_source_contract(connector, descriptors).encode("utf-8"),
                output_schema=b'{"type":"string"}',
            ),
        )
    return contract_entries


def _validate_data_entries(
    entries: Sequence[CapturedArtifact], descriptors: list[dict[str, Any]]
) -> None:
    data_entries = {
        entry.uri: entry for entry in entries if entry.uri.startswith("data://")
    }
    for descriptor in descriptors:
        uri = descriptor.get("uri")
        entry = data_entries.pop(uri, None) if isinstance(uri, str) else None
        if entry is None or json_object(entry) != descriptor:
            raise MalformedArtifactError(
                "served data resources differ from their declaration"
            )
    if data_entries:
        raise MalformedArtifactError("undeclared data resource in connector pack")


def _validate_resource_descriptors(entries: Sequence[CapturedArtifact]) -> None:
    """Validate the served declaration before it enters a content pack."""
    resources = next((entry for entry in entries if entry.uri == RESOURCES_URI), None)
    if resources is None:
        return
    descriptors = json_object(resources).get("descriptors", [])
    if not isinstance(descriptors, list) or any(
        not isinstance(d, dict) for d in descriptors
    ):
        raise MalformedArtifactError("resource descriptors must be a list of objects")
    if not descriptors:
        return
    classes = _ontology_classes(entries)
    for descriptor in descriptors:
        if descriptor.get("kind", "data") == "data":
            _check_captured_descriptor(descriptor, classes)


def _ontology_classes(entries: Sequence[CapturedArtifact]) -> frozenset[str]:
    from rdflib import RDF, RDFS, Graph, URIRef
    from rdflib.namespace import OWL

    graph = Graph()
    try:
        for entry in entries:
            if entry.kind == "resource" and entry.uri.startswith("ontology://"):
                graph.parse(data=entry.body, format="turtle")
    except Exception as exc:
        raise MalformedArtifactError("connector ontology is malformed") from exc
    classes = frozenset(
        str(subject)
        for kind in (OWL.Class, RDFS.Class)
        for subject in graph.subjects(RDF.type, kind)
        if isinstance(subject, URIRef)
    )
    return classes
