"""Host admission and relationship closure for bounded taxonomy subgraphs."""

import pytest

from agent_connector_sdk.taxonomy.graph_stream import _entities
from agent_connector_sdk.taxonomy.records import TaxonRecord


def rows():
    return (
        TaxonRecord(
            scientific_name="Parent",
            term_curie="NCBITaxon:1",
            taxon_rank="GENUS",
            ncbi_taxon_id="1",
        ),
        TaxonRecord(
            scientific_name="Child",
            term_curie="NCBITaxon:2",
            taxon_rank="SPECIES",
            parent_term_curie="NCBITaxon:1",
            ncbi_taxon_id="2",
        ),
    )


def test_admitted_subgraph_contains_cross_identifiers_and_typed_edges():
    records, edges = _entities(
        rows(),
        crosswalk={"NCBITaxon:1": ("1", "11"), "NCBITaxon:2": ("2", "22")},
        ranks={"GENUS": "genus", "SPECIES": "species"},
        roots=frozenset({"NCBITaxon:1"}),
    )
    taxa = [record for record in records if record["node_type"] == "Taxon"]
    assert {(record["ncbi_taxon_id"], record["gbif_taxon_id"]) for record in taxa} == {
        ("1", "11"),
        ("2", "22"),
    }
    assert {edge["relationship"] for edge in edges} == {"parentTaxon", "taxonRank"}
    assert len(edges) == 3


@pytest.mark.parametrize("case", ["crosswalk", "rank", "root", "parent"])
def test_refuses_missing_authority_or_parent(case):
    selected = rows()
    crosswalk = {"NCBITaxon:1": ("1", "11"), "NCBITaxon:2": ("2", "22")}
    ranks = {"GENUS": "genus", "SPECIES": "species"}
    roots = frozenset({"NCBITaxon:1"})
    if case == "crosswalk":
        crosswalk["NCBITaxon:2"] = ("9", "22")
    elif case == "rank":
        ranks.pop("SPECIES")
    elif case == "root":
        roots = frozenset()
    else:
        selected = selected[1:]
    with pytest.raises(ValueError):
        _entities(selected, crosswalk=crosswalk, ranks=ranks, roots=roots)


def test_crosswalk_is_complete_one_to_one_and_bound_to_provider_ids():
    from agent_connector_sdk.taxonomy.graph_stream import _validate_crosswalk

    identifiers = ["1", "2"]
    _validate_crosswalk(
        "ncbi", identifiers, {"NCBITaxon:1": ("1", "11"), "NCBITaxon:2": ("2", "22")}
    )
    for invalid in (
        {"NCBITaxon:1": ("1", "11")},
        {"NCBITaxon:1": ("1", "11"), "NCBITaxon:2": ("2", "11")},
        {"NCBITaxon:1": ("9", "11"), "NCBITaxon:2": ("2", "22")},
    ):
        with pytest.raises(ValueError):
            _validate_crosswalk("ncbi", identifiers, invalid)


@pytest.mark.asyncio
async def test_served_taxonomy_graph_authorizes_and_checks_policy_before_egress():
    import json
    from contextlib import asynccontextmanager

    from fastmcp import Client, FastMCP
    from fastmcp.exceptions import ToolError

    from agent_connector_sdk.http.options import HttpClientOptions
    from agent_connector_sdk.http.retry import RetryPolicy
    from agent_connector_sdk.taxonomy.graph_stream import register_taxonomy_graph_stream
    from agent_connector_sdk.taxonomy.provider import TaxonomyProvider
    from agent_connector_sdk.testing.http_server import (
        ScriptedHttpServer,
        ScriptedResponse,
    )

    @asynccontextmanager
    async def quota(_name):
        yield

    allowed = False

    async def authorize(tenant, context):
        return allowed and tenant == "allowed" and context is not None

    def body(identifier):
        return json.dumps(
            {
                "key": identifier,
                "nubKey": identifier,
                "scientificName": f"Taxon {identifier}",
                "rank": "GENUS" if identifier == 11 else "SPECIES",
                "parentKey": None if identifier == 11 else 11,
            }
        ).encode()

    with ScriptedHttpServer(
        ScriptedResponse(body=body(11)), ScriptedResponse(body=body(22))
    ) as http:
        provider = TaxonomyProvider(
            provider="gbif",
            http=HttpClientOptions(
                base_url=http.base_url,
                pin_egress=True,
                allow_loopback=True,
                retry=RetryPolicy(max_attempts=1),
            ),
            quota=quota,
            max_bytes=65536,
        )
        server = FastMCP("taxonomy-graph")
        register_taxonomy_graph_stream(
            server,
            provider,
            ["11", "22"],
            tenant="allowed",
            name="taxa",
            connector="taxonomy",
            policy_revision="v1",
            authorize=authorize,
            max_records=2,
            crosswalk={"GBIF:11": ("1", "11"), "GBIF:22": ("2", "22")},
            ranks={"GENUS": "genus", "SPECIES": "species"},
            roots=["GBIF:11"],
        )
        async with Client(server) as client:
            with pytest.raises(ToolError):
                await client.call_tool("taxa", {})
            assert not http.requests
            allowed = True
            with pytest.raises(ToolError):
                await client.call_tool(
                    "taxa", {"state": {"binding": "wrong", "generation": "g"}}
                )
            assert not http.requests
            page = (await client.call_tool("taxa", {})).structured_content
            assert len(page["records"]) == 4
            assert len(page["relationships"]) == 3
            assert page["checkpoint"]["binding"]
            assert len(http.requests) == 2


def test_taxonomy_graph_bound_counts_rank_nodes_too():
    from agent_connector_sdk.taxonomy._graph_policy import _validate_policy

    identifiers = [str(value) for value in range(1, 1001)]
    ranks = {str(value): str(value) for value in range(25)}
    with pytest.raises(ValueError, match="source batch record bound"):
        _validate_policy(identifiers, max_records=1000, ranks=ranks)
    with pytest.raises(ValueError, match="bound"):
        _validate_policy(["1"], max_records=True, ranks={"SPECIES": "species"})
