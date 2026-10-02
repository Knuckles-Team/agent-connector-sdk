"""Normalized finance record identity, adjustment and completeness rules."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from agent_connector_sdk.finance.account import AccountActivity, AccountSnapshot, Position
from agent_connector_sdk.finance.multi_asset import (
    CommodityPrice,
    CommodityPriceBasis,
    FxRate,
    RealEstateValuation,
)
from agent_connector_sdk.finance.records import (
    AdjustmentMode,
    Completeness,
    CorporateAction,
    OhlcvBar,
    Quote,
)

_NOW = datetime(2026, 1, 2, tzinfo=UTC)


def _base_fields(**overrides: object) -> dict[str, object]:
    fields: dict[str, object] = {
        "tenant_id": "tenant-1",
        "source_id": "source-1",
        "provider": "fixture-vendor",
        "instrument_id": "AAA",
        "source_event_id": "event-1",
        "event_time_utc": _NOW,
        "observed_at_utc": _NOW,
        "license_tag": "licensed",
        "source_digest": "digest-1",
    }
    fields.update(overrides)
    return fields


def _bar(**overrides: object) -> OhlcvBar:
    fields = _base_fields(
        timeframe="1d",
        session_calendar="XNYS",
        currency="USD",
        adjustment_mode=AdjustmentMode.RAW,
        completeness=Completeness.COMPLETE,
        open=10.0,
        high=11.0,
        low=9.0,
        close=10.5,
        volume=100.0,
    )
    fields.update(overrides)
    return OhlcvBar(**fields)


def test_ohlcv_bar_requires_explicit_adjustment_and_completeness() -> None:
    bar = _bar()
    assert bar.adjustment_mode is AdjustmentMode.RAW
    assert bar.completeness is Completeness.COMPLETE


def test_ohlcv_bar_rejects_high_low_that_do_not_bound_open_close() -> None:
    with pytest.raises(ValidationError, match="bound open and close"):
        _bar(high=9.5)


def test_naive_timestamp_is_rejected() -> None:
    with pytest.raises(ValidationError, match="timezone-aware"):
        _bar(event_time_utc=datetime(2026, 1, 2))


def test_quote_rejects_bid_above_ask() -> None:
    with pytest.raises(ValidationError, match="bid must not exceed ask"):
        Quote(**_base_fields(), bid=10.5, ask=10.0, quote_time_utc=_NOW)


def test_corporate_action_rejects_ex_date_after_effective_date() -> None:
    with pytest.raises(ValidationError, match="ex_date"):
        CorporateAction(
            **_base_fields(),
            ex_date=datetime(2026, 2, 1, tzinfo=UTC),
            effective_date=datetime(2026, 1, 1, tzinfo=UTC),
            action_type="split",
            adjustment_factor=2.0,
        )


def test_fx_rate_inversion_swaps_base_quote_and_rate() -> None:
    rate = FxRate(
        **_base_fields(), base_currency="EUR", quote_currency="USD", rate=1.1
    )

    inverted = rate.inverted()

    assert inverted.base_currency == "USD"
    assert inverted.quote_currency == "EUR"
    assert inverted.rate == pytest.approx(1 / 1.1)
    assert inverted.source_event_id == f"{rate.source_event_id}:inverted"


def test_fx_rate_rejects_identical_base_and_quote() -> None:
    with pytest.raises(ValidationError, match="must differ"):
        FxRate(**_base_fields(), base_currency="USD", quote_currency="USD", rate=1.0)


def test_commodity_future_requires_contract_fields() -> None:
    with pytest.raises(ValidationError, match="requires contract_code"):
        CommodityPrice(
            **_base_fields(),
            basis=CommodityPriceBasis.FUTURE,
            price=1900.0,
            currency="USD",
        )


def test_commodity_spot_rejects_future_only_fields() -> None:
    with pytest.raises(ValidationError, match="must not carry future-only"):
        CommodityPrice(
            **_base_fields(),
            basis=CommodityPriceBasis.SPOT,
            price=1900.0,
            currency="USD",
            contract_code="GCZ26",
        )


def test_commodity_future_with_full_roll_rule_is_explicit() -> None:
    price = CommodityPrice(
        **_base_fields(),
        basis=CommodityPriceBasis.FUTURE,
        price=1950.0,
        currency="USD",
        contract_code="GCZ26",
        expiry=datetime(2026, 12, 1, tzinfo=UTC),
        roll_rule="roll to front month 5 business days before expiry",
    )
    assert price.basis is CommodityPriceBasis.FUTURE


def test_real_estate_valuation_reports_staleness_explicitly() -> None:
    fresh = RealEstateValuation(
        **_base_fields(),
        valuation_date=_NOW,
        method="comparable-sales",
        currency="USD",
        staleness_days=0,
        stale=False,
    )
    stale = RealEstateValuation(
        **_base_fields(),
        valuation_date=_NOW,
        method="comparable-sales",
        currency="USD",
        staleness_days=400,
        stale=True,
    )
    assert fresh.stale is False
    assert stale.staleness_days == 400


def test_real_estate_valuation_rejects_same_day_stale_claim() -> None:
    with pytest.raises(ValidationError, match="same-day valuation"):
        RealEstateValuation(
            **_base_fields(),
            valuation_date=_NOW,
            method="comparable-sales",
            currency="USD",
            staleness_days=0,
            stale=True,
        )


def test_account_activity_requires_a_stable_identity() -> None:
    with pytest.raises(ValidationError, match="requires broker_event_id"):
        AccountActivity(
            **_base_fields(),
            account_id="acct-1",
            action="buy",
            quantity=10,
            price=1.0,
            fees=0.0,
            currency="USD",
            settlement_time_utc=_NOW,
        )


def test_account_snapshot_rejects_a_foreign_position() -> None:
    position = Position(
        account_id="other-account",
        instrument_id="AAA",
        quantity=1,
        average_cost=1.0,
        currency="USD",
    )
    with pytest.raises(ValidationError, match="belong to this account_id"):
        AccountSnapshot(
            **_base_fields(),
            account_id="acct-1",
            cash_balance=100.0,
            currency="USD",
            positions=(position,),
        )
