"""Repeated continuation tokens stop the current pagination sweep."""

from __future__ import annotations

import pytest

from agent_connector_sdk.httpsupport.pagination import (
    AsyncPaginationIterator,
    PaginationIterator,
)


@pytest.mark.spec("SCION-CENTRALIZED-CAPABILITIES-R004.8")
def test_cursor_cycle_stops_before_repeating_request():
    calls = []

    def fetch(_url, params):
        cursor = (params or {}).get("cursor")
        calls.append(cursor)
        return {
            "items": [len(calls)],
            "next_cursor": {None: "a", "a": "b", "b": "a"}[cursor],
        }, {}

    result = PaginationIterator(
        fetch, "/items", mode="cursor", items_path="items"
    ).collect()
    assert result["data"] == [1, 2, 3]
    assert calls == [None, "a", "b"]
    assert result["truncated"] is True and result["next_cursor"] is None


@pytest.mark.spec("SCION-CENTRALIZED-CAPABILITIES-R004.8")
async def test_async_cursor_repeat_preserves_initial_request_bound():
    calls = []

    async def fetch(_url, params):
        calls.append(params)
        return {"items": [1], "next_cursor": "same"}, {}

    iterator = AsyncPaginationIterator(
        fetch, "/items", mode="cursor", items_path="items", params={"cursor": "same"}
    )
    result = await iterator.collect()
    assert result["data"] == [1] and len(calls) == 1
    assert result["truncated"] is True and result["next_cursor"] is None


@pytest.mark.spec("SCION-CENTRALIZED-CAPABILITIES-R004.8")
def test_since_id_repeat_stops_without_next_cursor():
    calls = []

    def fetch(_url, params):
        calls.append(params)
        return [{"id": 5}], {}

    iterator = PaginationIterator(
        fetch, "/items", mode="since_id", params={"since_id": 5}
    )
    result = iterator.collect()
    assert result["data"] == [{"id": 5}] and len(calls) == 1
    assert result["truncated"] is True and result["next_cursor"] is None
