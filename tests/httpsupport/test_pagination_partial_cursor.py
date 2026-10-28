"""A truncated provider page cannot expose its later-page cursor."""

import pytest

from agent_connector_sdk.httpsupport.pagination import (
    AsyncPaginationIterator,
    PaginationIterator,
)


def _page(params):
    start = int((params or {}).get("cursor", 0))
    return {"items": list(range(start, start + 3)), "next_cursor": str(start + 3)}, {}


@pytest.mark.spec("SDK-CENTRALIZED-CAPABILITIES-R004.5")
async def test_async_partial_page_never_reports_later_cursor():
    calls = []

    async def fetch(url, params):
        calls.append(params)
        return _page(params)

    iterator = AsyncPaginationIterator(
        fetch, "/items", mode="cursor", items_path="items", max_items=4
    )
    result = await iterator.collect()
    assert result["data"] == [0, 1, 2, 3]
    assert result["truncated"] is True
    assert result["next_cursor"] is None
    assert len(calls) == 2


@pytest.mark.spec("SDK-CENTRALIZED-CAPABILITIES-R004.5")
def test_complete_page_budget_keeps_provider_cursor():
    def fetch(url, params):
        return _page(params)

    result = PaginationIterator(
        fetch, "/items", mode="cursor", items_path="items", max_items=3
    ).collect()
    assert result["data"] == [0, 1, 2]
    assert result["truncated"] is True
    assert result["next_cursor"] == "3"
