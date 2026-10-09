"""ETF fund-flow panel: daily net creation/redemption flow and AUM, by fund.

A fund-flow source reports, for one fund on one trading day, the net dollar
flow (creations minus redemptions) and the fund's assets under management as
of that day's close. Each record is tagged with its source and observation
time, the same provenance discipline every finance source record carries
(:class:`agent_connector_sdk.finance.records.FinanceRecordBase`).
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import UTC, date, datetime
from typing import Any

from pydantic import Field

from agent_connector_sdk.finance.records import FinanceRecordBase

__all__ = [
    "EtfFundFlow",
    "etf_fund_flows_from_source",
]


class EtfFundFlow(FinanceRecordBase):
    """One fund's net flow and AUM as of one trading day's close."""

    fund_ticker: str = Field(min_length=1)
    flow_date: date
    net_flow_usd: float
    aum_usd: float = Field(ge=0)


def _flow_event_id(fund_ticker: str, flow_date: str) -> str:
    return f"{fund_ticker}:{flow_date}"


def _flow_from_source(
    raw: Mapping[str, Any],
    *,
    tenant_id: str,
    source_id: str,
    provider: str,
    license_tag: str,
    observed_at_utc: datetime,
) -> EtfFundFlow:
    fund_ticker = str(raw["fund_ticker"])
    flow_date = str(raw["flow_date"])
    event_id = _flow_event_id(fund_ticker, flow_date)
    return EtfFundFlow(
        tenant_id=tenant_id,
        source_id=source_id,
        provider=provider,
        instrument_id=fund_ticker,
        source_event_id=event_id,
        event_time_utc=datetime.fromisoformat(flow_date).replace(tzinfo=UTC),
        observed_at_utc=observed_at_utc,
        license_tag=license_tag,
        source_digest=event_id,
        fund_ticker=fund_ticker,
        flow_date=date.fromisoformat(flow_date),
        net_flow_usd=float(raw["net_flow_usd"]),
        aum_usd=float(raw["aum_usd"]),
    )


def etf_fund_flows_from_source(
    payload: Mapping[str, Any],
    *,
    tenant_id: str,
    source_id: str,
    provider: str,
    license_tag: str,
    observed_at_utc: datetime,
) -> tuple[EtfFundFlow, ...]:
    """Normalize one fund-flow source page; one record per fund per day."""
    raw_flows: Sequence[Mapping[str, Any]] = payload.get("flows", ())
    return tuple(
        _flow_from_source(
            raw,
            tenant_id=tenant_id,
            source_id=source_id,
            provider=provider,
            license_tag=license_tag,
            observed_at_utc=observed_at_utc,
        )
        for raw in raw_flows
    )
