"""Malformed record collections cannot masquerade as an empty page."""

from __future__ import annotations

import pytest

from scion_sdk.httpsupport.pagination import (
    AsyncPaginationIterator,
    PaginationIterator,
    PaginationPageError,
)


@pytest.mark.spec("SCION-CENTRALIZED-CAPABILITIES-R004.6")
@pytest.mark.parametrize(
    "body", [{}, {"items": None}, {"items": {"secret": "private"}}]
)
def test_malformed_record_collection_refuses_without_leaking_body(body):
    def fetch(_url, _params):
        return body, {}

    iterator = PaginationIterator(fetch, "/items", items_path="items")
    with pytest.raises(PaginationPageError) as caught:
        list(iterator)
    assert "private" not in caught.value.problem.model_dump_json()
    assert iterator.pages_fetched == 0
    assert iterator.next_cursor is None


@pytest.mark.spec("SCION-CENTRALIZED-CAPABILITIES-R004.6")
async def test_async_malformed_page_does_not_advance_cursor():
    calls = []

    async def fetch(_url, params):
        calls.append(params)
        if len(calls) == 1:
            return {"items": [1], "next_cursor": "page-two"}, {}
        return {"items": {"unexpected": "data"}, "next_cursor": "page-three"}, {}

    iterator = AsyncPaginationIterator(
        fetch, "/items", mode="cursor", items_path="items"
    )
    values = []
    with pytest.raises(PaginationPageError):
        async for item in iterator:
            values.append(item)
    assert values == [1]
    assert len(calls) == 2
    assert iterator.next_cursor == "page-two"
    assert iterator.pages_fetched == 1


@pytest.mark.spec("SCION-CENTRALIZED-CAPABILITIES-R004.6")
def test_empty_list_remains_valid():
    def fetch(_url, _params):
        return {"items": []}, {}

    assert (
        PaginationIterator(fetch, "/items", items_path="items").collect()["data"] == []
    )
