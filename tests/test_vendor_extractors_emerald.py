"""SDK-SOURCE-INGEST-R006.12: the Emerald-Exchange vendor extractor port."""

from __future__ import annotations

import pytest

from agent_connector_sdk.ingest import ChangeSet, Entity, Relationship
from agent_connector_sdk.vendor_extractors import (
    get_vendor_extractor,
    list_vendor_extractors,
)
from agent_connector_sdk.vendor_extractors.emerald import CATEGORY, extract


class _Account:
    exchange = "alpaca"
    equity = 1000.0
    cash = 500.0
    buying_power = 2000.0
    currency = "USD"


class _Position:
    def __init__(self, symbol: str) -> None:
        self.symbol = symbol
        self.qty = 10
        self.avg_entry_price = 100.0
        self.current_price = 110.0
        self.unrealized_pnl = 100.0
        self.side = "long"


class _FakeClient:
    def __init__(self, account: object, positions: object) -> None:
        self._account = account
        self._positions = positions

    def get_account(self) -> object:
        return self._account

    def get_positions(self) -> object:
        return self._positions


@pytest.mark.spec("SDK-SOURCE-INGEST-R006.12")
def test_extract_returns_portfolio_account_and_position_entities() -> None:
    config = {"client": _FakeClient(_Account(), [_Position("AAPL")])}

    result = extract(config)

    assert isinstance(result, ChangeSet)
    assert len(result.entities) == 3
    portfolio, account, position = result.entities
    assert isinstance(portfolio, Entity)
    assert portfolio.id == "emerald:portfolio:alpaca"
    assert portfolio.node_type == "Portfolio"
    assert account.id == "emerald:account:alpaca"
    assert account.node_type == "Account"
    assert account.properties["equity"] == 1000.0
    assert position.id == "emerald:pos:alpaca:AAPL"
    assert position.node_type == "Position"
    assert len(result.relationships) == 1
    relationship = result.relationships[0]
    assert isinstance(relationship, Relationship)
    assert relationship.source == "emerald:pos:alpaca:AAPL"
    assert relationship.target == "emerald:portfolio:alpaca"
    assert relationship.relationship == "HELD_IN"


@pytest.mark.spec("SDK-SOURCE-INGEST-R006.12")
def test_extract_returns_only_a_default_portfolio_without_a_client_account() -> None:
    config = {"client": _FakeClient(None, [])}

    result = extract(config)

    assert len(result.entities) == 1
    assert result.entities[0].id == "emerald:portfolio:emerald"


@pytest.mark.spec("SDK-SOURCE-INGEST-R006.12")
def test_extract_returns_an_empty_change_set_without_a_client() -> None:
    assert extract({}) == ChangeSet()


@pytest.mark.spec("SDK-SOURCE-INGEST-R006.12")
def test_emerald_self_registers_under_the_vendor_extractor_registry() -> None:
    registered = get_vendor_extractor(CATEGORY)

    assert registered is not None
    assert registered.extract is extract
    assert CATEGORY in [vendor.category for vendor in list_vendor_extractors()]
