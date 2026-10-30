"""MCP pack capture does not require ontology tooling without descriptors."""

from __future__ import annotations

import builtins
import json

import pytest
from fastmcp import FastMCP

from scion_sdk.artifacts.pack import (
    _validate_resource_descriptors,
    build_content_pack,
)
from scion_sdk.artifacts.resources import ResourceArtifactKind
from scion_sdk.contracts import CapturedArtifact, ServerIdentity
from scion_sdk.ports.session import TransportEndpoint
from scion_sdk.transports.mcp import McpTransport


def _without_rdflib(monkeypatch):
    original = builtins.__import__

    def import_without_rdf(name, *args, **kwargs):
        if name == "rdflib" or name.startswith("rdflib."):
            raise ModuleNotFoundError("No module named 'rdflib'")
        return original(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", import_without_rdf)


async def test_real_pack_with_no_descriptors_needs_no_rdf(monkeypatch):
    mcp = FastMCP("sample", version="1.0.0")

    @mcp.resource("connector://resources")
    def declaration() -> str:
        return json.dumps({"connector": "sample", "sources": [], "schema_mappings": {}})

    _without_rdflib(monkeypatch)
    async with McpTransport().session(TransportEndpoint(in_process=mcp)) as session:
        pack = await build_content_pack(
            session, connector="sample", kinds=[ResourceArtifactKind()]
        )
    assert "connector://resources" in pack.resource_uris


def test_descriptors_do_not_skip_ontology_verification_without_rdf(monkeypatch):
    _without_rdflib(monkeypatch)
    entry = CapturedArtifact(
        kind="resource",
        uri="connector://resources",
        name="resources",
        media_type="application/json",
        body=json.dumps({"descriptors": [{"name": "item"}]}),
        server=ServerIdentity(name="sample", version="1.0.0"),
    )
    with pytest.raises(ModuleNotFoundError, match="rdflib"):
        _validate_resource_descriptors([entry])
