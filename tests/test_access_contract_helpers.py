"""The access-contract helper modules expose small, tested building blocks."""

from __future__ import annotations

from agent_connector_sdk._contract_fields import COST_HINTS, integer
from agent_connector_sdk._turtle import RDF_TYPE, parse_graph


def test_parse_graph_reads_typed_subjects_with_rdf_type() -> None:
    graph = parse_graph(
        "@prefix ex: <http://example.org/> .\nex:a a ex:Thing ; ex:size 3 .\n"
    )
    subject = graph["http://example.org/a"]
    assert subject[RDF_TYPE]


def test_integer_reads_an_integer_field_and_cost_hints_are_bounded() -> None:
    graph = parse_graph(
        "@prefix ac: <https://knuckles-team.github.io/agent-connector-sdk/access#> .\n"
        "@prefix ex: <http://example.org/> .\nex:a ac:rateLimit 3 .\n"
    )
    props = graph["http://example.org/a"]
    assert integer(props, "rateLimit", "http://example.org/a") == 3
    assert {"low", "medium", "high"} == set(COST_HINTS)
