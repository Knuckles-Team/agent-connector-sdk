"""Normalized broker account, position and activity records.

A brokerage connector owns its own credentials and API client; this module
only normalizes what it reads into shared record shapes so every broker's
account data carries the same identity and idempotency rules. An activity is
identified by a stable provider event ID, or by a source-file digest plus
its row identity when it was imported from a statement, so a re-import or a
duplicate read never produces a second record for the same event.
"""

from __future__ import annotations

from datetime import datetime
from typing import Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from agent_connector_sdk.finance.records import FinanceRecordBase

__all__ = ["AccountActivity", "AccountSnapshot", "Position"]


class _Frozen(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class Position(_Frozen):
    """One open position held in an account."""

    account_id: str = Field(min_length=1)
    instrument_id: str = Field(min_length=1)
    quantity: float
    average_cost: float = Field(ge=0)
    currency: str = Field(min_length=3, max_length=3)


class AccountSnapshot(FinanceRecordBase):
    """One account read: cash balance plus every currently held position."""

    account_id: str = Field(min_length=1)
    cash_balance: float
    currency: str = Field(min_length=3, max_length=3)
    positions: tuple[Position, ...] = ()

    @model_validator(mode="after")
    def _positions_belong_to_this_account(self) -> Self:
        if any(position.account_id != self.account_id for position in self.positions):
            raise ValueError("every position must belong to this account_id")
        return self


class AccountActivity(FinanceRecordBase):
    """One broker event or imported statement row.

    Identity is stable across a re-read or a re-import: either
    ``broker_event_id`` is set, or both ``source_file_digest`` and ``row_id``
    are, so the same underlying event always maps to the same record.
    """

    account_id: str = Field(min_length=1)
    broker_event_id: str | None = None
    source_file_digest: str | None = None
    row_id: str | None = None
    action: str = Field(min_length=1)
    quantity: float
    price: float = Field(ge=0)
    fees: float = Field(ge=0)
    currency: str = Field(min_length=3, max_length=3)
    settlement_time_utc: datetime

    @model_validator(mode="after")
    def _has_a_stable_identity(self) -> Self:
        has_broker_id = bool(self.broker_event_id)
        has_file_row = bool(self.source_file_digest) and bool(self.row_id)
        if not (has_broker_id or has_file_row):
            raise ValueError(
                "activity requires broker_event_id or "
                "(source_file_digest and row_id)"
            )
        return self
