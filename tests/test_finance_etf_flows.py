"""ETF fund-flow panel, tagged with source and observation time
(SDK-FINANCE-SOURCES-R005)."""

from __future__ import annotations

from datetime import UTC, date, datetime

from agent_connector_sdk.finance.etf_flows import (
    EtfFundFlow,
    etf_fund_flows_from_source,
)

_OBSERVED = datetime(2026, 1, 2, tzinfo=UTC)

_PAGE = {
    "flows": [
        {
            "fund_ticker": "SPY",
            "flow_date": "2026-01-01",
            "net_flow_usd": 1_250_000_000.0,
            "aum_usd": 512_000_000_000.0,
        },
        {
            "fund_ticker": "QQQ",
            "flow_date": "2026-01-01",
            "net_flow_usd": -340_000_000.0,
            "aum_usd": 300_000_000_000.0,
        },
    ]
}


def _flows(**overrides: object) -> tuple[EtfFundFlow, ...]:
    fields: dict[str, object] = {
        "payload": _PAGE,
        "tenant_id": "tenant-1",
        "source_id": "etf-flow-vendor",
        "provider": "etf-flow-vendor",
        "license_tag": "licensed",
        "observed_at_utc": _OBSERVED,
    }
    fields.update(overrides)
    return etf_fund_flows_from_source(**fields)


def test_one_record_per_fund_per_day() -> None:
    flows = _flows()
    assert [f.fund_ticker for f in flows] == ["SPY", "QQQ"]
    assert flows[0].flow_date == date(2026, 1, 1)
    assert flows[0].net_flow_usd == 1_250_000_000.0
    assert flows[0].aum_usd == 512_000_000_000.0


@pytest.mark.spec("SDK-FINANCE-SOURCES-R005")
def test_each_record_is_tagged_with_source_and_observation_time() -> None:
    flows = _flows()
    assert all(f.source_id == "etf-flow-vendor" for f in flows)
    assert all(f.provider == "etf-flow-vendor" for f in flows)
    assert all(f.observed_at_utc == _OBSERVED for f in flows)
    assert all(f.instrument_id == f.fund_ticker for f in flows)


def test_outflow_is_a_negative_net_flow() -> None:
    flows = _flows()
    assert flows[1].net_flow_usd < 0


def test_distinct_funds_on_the_same_day_get_distinct_event_ids() -> None:
    flows = _flows()
    assert flows[0].source_event_id != flows[1].source_event_id


def test_empty_flows_yields_no_records() -> None:
    assert _flows(payload={"flows": []}) == ()
