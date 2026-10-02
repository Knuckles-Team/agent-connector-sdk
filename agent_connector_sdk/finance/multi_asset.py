"""FX, commodity and real-estate records with explicit roll and staleness.

FX quotes identify base and quote currency and rate direction. Gold and
commodity adapters distinguish a spot price from a specific futures contract,
its expiry and an explicit roll rule. Real estate is a dated, potentially
stale valuation rather than a live market quote. An impossible combination
(a future price with no contract, a spot price carrying future-only fields,
an inverted FX pair naming the same currency twice) refuses rather than
silently producing a record a consumer would misread.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Self

from pydantic import Field, model_validator

from agent_connector_sdk.finance.records import FinanceRecordBase

__all__ = [
    "CommodityPrice",
    "CommodityPriceBasis",
    "FxRate",
    "RealEstateValuation",
]


class FxRate(FinanceRecordBase):
    """One exchange rate between an identified base and quote currency."""

    base_currency: str = Field(min_length=3, max_length=3)
    quote_currency: str = Field(min_length=3, max_length=3)
    rate: float = Field(gt=0)

    @model_validator(mode="after")
    def _base_and_quote_differ(self) -> Self:
        if self.base_currency == self.quote_currency:
            raise ValueError("base_currency and quote_currency must differ")
        return self

    def inverted(self) -> FxRate:
        """Return the mirror rate with base and quote swapped."""
        return self.model_copy(
            update={
                "base_currency": self.quote_currency,
                "quote_currency": self.base_currency,
                "rate": 1.0 / self.rate,
                "source_event_id": f"{self.source_event_id}:inverted",
            }
        )


class CommodityPriceBasis(StrEnum):
    """Whether a commodity price is a live spot print or a futures contract."""

    SPOT = "spot"
    FUTURE = "future"


class CommodityPrice(FinanceRecordBase):
    """One gold or commodity price, spot or a specific futures contract."""

    basis: CommodityPriceBasis
    price: float = Field(gt=0)
    currency: str = Field(min_length=3, max_length=3)
    contract_code: str | None = None
    expiry: datetime | None = None
    roll_rule: str | None = None

    @model_validator(mode="after")
    def _contract_fields_match_basis(self) -> Self:
        contract_fields = (self.contract_code, self.expiry, self.roll_rule)
        if self.basis is CommodityPriceBasis.FUTURE:
            if not all(contract_fields):
                raise ValueError(
                    "a future price requires contract_code, expiry and roll_rule"
                )
        elif any(contract_fields):
            raise ValueError("a spot price must not carry future-only fields")
        return self


class RealEstateValuation(FinanceRecordBase):
    """One dated, potentially stale real-estate valuation.

    Real estate is never a live market quote: ``staleness_days`` is always
    reported, and ``stale`` must agree with whether that staleness exceeds
    the method's own freshness expectation.
    """

    valuation_date: datetime
    method: str = Field(min_length=1)
    currency: str = Field(min_length=3, max_length=3)
    staleness_days: int = Field(ge=0)
    stale: bool

    @model_validator(mode="after")
    def _staleness_is_consistent(self) -> Self:
        if self.staleness_days == 0 and self.stale:
            raise ValueError("a same-day valuation cannot be reported stale")
        return self
