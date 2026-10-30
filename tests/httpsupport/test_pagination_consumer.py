"""One pagination iterator cannot share its mutable walk across consumers."""

from __future__ import annotations

import pytest

from scion_sdk.httpsupport.pagination import (
    AsyncPaginationIterator,
    PaginationIterator,
)


@pytest.mark.spec("SCION-CENTRALIZED-CAPABILITIES-R004.7")
def test_sync_iterator_refuses_overlapping_consumer_and_can_reuse():
    def fetch(_url, _params):
        return [1, 2], {}

    iterator = PaginationIterator(fetch, "/items", mode="page", max_pages=1)
    first = iter(iterator)
    assert next(first) == 1
    second = iter(iterator)
    with pytest.raises(RuntimeError, match="active consumer"):
        next(second)
    assert list(first) == [2]
    assert list(iterator) == [1, 2]


@pytest.mark.spec("SCION-CENTRALIZED-CAPABILITIES-R004.7")
async def test_async_iterator_refuses_overlap_and_releases_on_close():
    async def fetch(_url, _params):
        return [1, 2], {}

    iterator = AsyncPaginationIterator(fetch, "/items", mode="page", max_pages=1)
    first = aiter(iterator)
    assert await anext(first) == 1
    second = aiter(iterator)
    with pytest.raises(RuntimeError, match="active consumer"):
        await anext(second)
    await first.aclose()
    assert [item async for item in iterator] == [1, 2]


@pytest.mark.spec("SCION-CENTRALIZED-CAPABILITIES-R004.7")
def test_failed_fetch_releases_consumer_claim():
    attempts = 0

    def fetch(_url, _params):
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise ValueError("provider failure")
        return [], {}

    iterator = PaginationIterator(fetch, "/items", mode="page", max_pages=1)
    with pytest.raises(ValueError, match="provider failure"):
        list(iterator)
    assert list(iterator) == []
