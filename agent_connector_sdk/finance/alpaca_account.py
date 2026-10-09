"""Alpaca account and position read, normalized to ``AccountSnapshot``.

Maps one Alpaca ``GET /v2/account`` plus ``GET /v2/positions`` read onto the
vendor-neutral :class:`AccountSnapshot`/:class:`Position` shapes. The
snapshot's identity is derived only from the account id and the read's
``as_of_utc`` instant, so re-reading the same account at the same instant
always reproduces the same ``source_event_id`` and ``source_digest``; a sink
that upserts on that identity creates no duplicate record.
"""

from __future__ import annotations

import hashlib
from collections.abc import Mapping, Sequence
from datetime import datetime
from typing import Any

from agent_connector_sdk.finance.account import AccountSnapshot, Position
from agent_connector_sdk.finance.csv_import import AccountContext

__all__ = ["account_snapshot_from_alpaca"]


def _read_digest(account_id: str, as_of_utc: datetime) -> str:
    payload = f"{account_id}:{as_of_utc.isoformat()}".encode()
    return f"sha256:{hashlib.sha256(payload).hexdigest()}"


def _position_from_alpaca(
    raw: Mapping[str, Any], *, account_id: str, default_currency: str
) -> Position:
    return Position(
        account_id=account_id,
        instrument_id=str(raw["symbol"]),
        quantity=float(raw["qty"]),
        average_cost=float(raw["avg_entry_price"]),
        currency=str(raw.get("currency", default_currency)),
    )


def account_snapshot_from_alpaca(
    account: Mapping[str, Any],
    positions: Sequence[Mapping[str, Any]],
    *,
    context: AccountContext,
    as_of_utc: datetime,
    observed_at_utc: datetime,
) -> AccountSnapshot:
    """Normalize one Alpaca account-plus-positions read into one snapshot."""
    currency = str(account["currency"])
    digest = _read_digest(context.account_id, as_of_utc)
    return AccountSnapshot(
        tenant_id=context.tenant_id,
        source_id=context.source_id,
        provider=context.provider,
        instrument_id=context.instrument_id,
        source_event_id=digest,
        event_time_utc=as_of_utc,
        observed_at_utc=observed_at_utc,
        license_tag=context.license_tag,
        source_digest=digest,
        account_id=context.account_id,
        cash_balance=float(account["cash"]),
        currency=currency,
        positions=tuple(
            _position_from_alpaca(
                position, account_id=context.account_id, default_currency=currency
            )
            for position in positions
        ),
    )
