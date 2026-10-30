"""Graph-sourced FRED inputs retain exact values and capture time."""

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest

from scion_sdk.finance.liquidity_panel import read_liquidity_panel
from scion_sdk.ports.errors import SourceContractError


def node(stream, series, value, text):
    period, vintage = "2026-10-21", "2026-10-22"
    return {
        "source_stream": stream,
        "source_record_id": f"{series}:{period}:{vintage}",
        "source_mapping_reference": "connector:bellwether-mcp#mappings/EconomicIndicator",
        "source_raw_sha256": "a" * 64,
        "source_provenance": {
            "connector": "bellwether-mcp",
            "server": "bellwether-mcp",
            "tool": "fred_series_observations",
            "tool_schema_sha256": "b" * 64,
            "source_uri": f"mcp-tool://bellwether-mcp/fred_series_observations/{series}:{period}:{vintage}",
        },
        "series_id": series,
        "date": period,
        "realtime_start": vintage,
        "observed_at": "2026-10-27T12:00:00.123456+00:00",
        "value": value,
        "value_text": text,
    }


class Graph:
    def __init__(self, nodes):
        self.nodes = nodes
        self.calls = []
        self.query = SimpleNamespace(cypher_read=self.read)
        self.finance = SimpleNamespace(market=self.market)

    async def read(self, query):
        self.calls.append(("query", query))
        return [{"n": item} for item in self.nodes]

    async def market(self, op, **kwargs):
        self.calls.append((op, kwargs))
        return kwargs["request"]


def nodes():
    return [
        node("macro_series_fed_balance_sheet", "WALCL", 6753604.0, "6753604"),
        node("macro_series_treasury_general_account", "WDTGAL", 945153.0, "945153"),
        node("macro_series_reverse_repo_overnight", "RRPONTSYD", 0.226, "0.226"),
    ]


async def test_graph_sources_are_forwarded_exactly_to_engine():
    graph = Graph(nodes())
    result = await read_liquidity_panel(
        graph, as_of=datetime(2026, 10, 28, tzinfo=UTC), max_age=timedelta(days=14)
    )
    assert [item["series"] for item in result["observations"]] == [
        "walcl",
        "wdtgal",
        "rrpontsyd",
    ]
    assert [item["value_milliunits"] for item in result["observations"]] == [
        6753604000,
        945153000,
        226,
    ]
    assert result["observations"][0]["observed_ms"] % 1000 == 124
    assert all(
        "bellwether-mcp:" in item["source_ref"] for item in result["observations"]
    )
    assert graph.calls[-1][0] == "liquidity_panel"


@pytest.mark.parametrize(
    "change",
    [
        {"source_stream": "other"},
        {"series_id": "WDTGAL"},
        {"source_record_id": "other"},
        {"source_raw_sha256": "bad"},
        {
            "source_provenance": {
                "connector": "other",
                "tool": "fred_series_observations",
            }
        },
        {"observed_at": "2026-10-27T12:00:00"},
        {"value_text": "6753604.0001"},
        {"value_text": "6753604." + "0" * 80 + "1"},
        {"value_text": "NaN"},
        {"value_text": "6753605"},
        {"value_text": None},
    ],
)
async def test_bad_sources_refuse_before_engine(change):
    data = nodes()
    data[0].update(change)
    graph = Graph(data)
    with pytest.raises(SourceContractError, match="invalid liquidity source record"):
        await read_liquidity_panel(
            graph, as_of=datetime(2026, 10, 28, tzinfo=UTC), max_age=timedelta(days=14)
        )
    assert len(graph.calls) == 1


async def test_missing_fred_value_is_not_fabricated():
    data = nodes()
    data[0].update(value=None, value_text=None)
    graph = Graph(data)
    result = await read_liquidity_panel(
        graph, as_of=datetime(2026, 10, 28, tzinfo=UTC), max_age=timedelta(days=14)
    )
    assert [item["series"] for item in result["observations"]] == [
        "wdtgal",
        "rrpontsyd",
    ]


@pytest.mark.spec("SCION-FINANCE-SOURCES-R005.1")
async def test_versioned_request_returns_engine_composite_and_heat_strip_unchanged():
    graph = Graph(nodes())
    panel = {"version": 1, "composite": {"score": 3}, "heat_strip": [{"cell": "x"}]}

    async def market(op, **kwargs):
        graph.calls.append((op, kwargs))
        return panel

    graph.finance = SimpleNamespace(market=market)
    result = await read_liquidity_panel(
        graph, as_of=datetime(2026, 10, 28, tzinfo=UTC), max_age=timedelta(days=14)
    )
    assert result is panel
    op, kwargs = graph.calls[-1]
    assert op == "liquidity_panel"
    assert kwargs["request"]["version"] == 1
