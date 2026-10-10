"""FS: Alpaca account/position read, idempotent by account id and instant."""

from __future__ import annotations

from datetime import UTC, datetime

from agent_connector_sdk.finance.alpaca_account import account_snapshot_from_alpaca
from agent_connector_sdk.finance.csv_import import AccountContext

_CONTEXT = AccountContext(
    tenant_id="tenant-1",
    source_id="alpaca",
    provider="alpaca",
    instrument_id="ACCOUNT",
    account_id="acct-1",
    license_tag="licensed",
)

_AS_OF = datetime(2026, 1, 2, tzinfo=UTC)
_OBSERVED = datetime(2026, 1, 2, 0, 0, 5, tzinfo=UTC)

_ACCOUNT = {"currency": "USD", "cash": "4000.32"}
_POSITIONS = [
    {"symbol": "AAPL", "qty": "5", "avg_entry_price": "100.0"},
    {"symbol": "MSFT", "qty": "2", "avg_entry_price": "200.0", "currency": "USD"},
]


def _snapshot(**overrides: object) -> dict[str, object]:
    fields: dict[str, object] = {
        "account": _ACCOUNT,
        "positions": _POSITIONS,
        "context": _CONTEXT,
        "as_of_utc": _AS_OF,
        "observed_at_utc": _OBSERVED,
    }
    fields.update(overrides)
    return fields


def test_snapshot_maps_cash_balance_and_every_position() -> None:
    snapshot = account_snapshot_from_alpaca(**_snapshot())

    assert snapshot.account_id == "acct-1"
    assert snapshot.cash_balance == 4000.32
    assert snapshot.currency == "USD"
    assert [p.instrument_id for p in snapshot.positions] == ["AAPL", "MSFT"]
    assert snapshot.positions[0].average_cost == 100.0


def test_position_without_its_own_currency_inherits_the_account_currency() -> None:
    snapshot = account_snapshot_from_alpaca(**_snapshot())
    assert snapshot.positions[0].currency == "USD"


@pytest.mark.spec("SDK-FINANCE-SOURCES-R004")
def test_rereading_the_same_account_at_the_same_instant_is_idempotent() -> None:
    first = account_snapshot_from_alpaca(**_snapshot())
    second = account_snapshot_from_alpaca(**_snapshot())

    assert first.source_event_id == second.source_event_id
    assert first.source_digest == second.source_digest


def test_a_later_read_instant_is_a_new_version() -> None:
    first = account_snapshot_from_alpaca(**_snapshot())
    later = account_snapshot_from_alpaca(
        **_snapshot(as_of_utc=datetime(2026, 1, 3, tzinfo=UTC))
    )

    assert first.source_event_id != later.source_event_id
    assert first.source_digest != later.source_digest
