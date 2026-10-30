"""The ``next_url`` pagination mode follows a same-origin next URL in the body."""

from __future__ import annotations

import pytest

from scion_sdk.http.errors import HttpProblemError
from scion_sdk.httpsupport import PaginationOriginError as Exported
from scion_sdk.httpsupport.pagination import (
    AsyncPaginationIterator,
    PaginationIterator,
    PaginationOriginError,
)

pytestmark = [pytest.mark.spec("SCION-CENTRALIZED-CAPABILITIES-R004")]

BASE = "https://tower.test/api/v2/"


def _pages(pages: dict[str, dict], fetched: list[str]):
    def fetch(url, params):
        fetched.append(url)
        return pages[url], {}

    return fetch


def _iterator(pages: dict[str, dict], fetched: list[str], **options):
    return PaginationIterator(
        _pages(pages, fetched),
        "hosts/",
        mode="next_url",
        base_url=BASE,
        items_path="results",
        **options,
    )


def test_follows_relative_and_absolute_next_and_stops_on_null():
    fetched: list[str] = []
    pages = {
        "hosts/": {"results": [1], "next": "/api/v2/hosts/?page=2"},
        "https://tower.test/api/v2/hosts/?page=2": {
            "results": [2],
            "next": "https://tower.test:443/api/v2/hosts/?page=3",
        },
        "https://tower.test:443/api/v2/hosts/?page=3": {"results": [3], "next": None},
    }
    iterator = _iterator(pages, fetched)
    assert list(iterator) == [1, 2, 3]
    assert fetched == list(pages)
    assert iterator.truncated is False
    assert iterator.next_cursor is None


def test_relative_next_resolves_against_the_request_url():
    fetched: list[str] = []
    pages = {
        "hosts/": {"results": [1], "next": "?page=2"},
        "https://tower.test/api/v2/hosts/?page=2": {"results": [2], "next": ""},
    }
    assert list(_iterator(pages, fetched)) == [1, 2]


def test_custom_body_key():
    fetched: list[str] = []
    pages = {
        "hosts/": {"results": [1], "links": {"next_page": "/api/v2/hosts/?page=2"}},
        "https://tower.test/api/v2/hosts/?page=2": {"results": [2]},
    }
    assert list(_iterator(pages, fetched, next_path="links.next_page")) == [1, 2]


@pytest.mark.parametrize(
    "next_url",
    [
        "https://evil.test/api/v2/hosts/?page=2",
        "//evil.test/api/v2/hosts/?page=2",
        "http://tower.test/api/v2/hosts/?page=2",
        "https://tower.test:8443/api/v2/hosts/?page=2",
        "https://tower.test:0/api/v2/hosts/?page=2",
    ],
    ids=[
        "cross-host",
        "scheme-relative-host",
        "cross-scheme",
        "port-change",
        "zero-port",
    ],
)
def test_rejects_cross_origin_next(next_url: str):
    fetched: list[str] = []
    pages = {"hosts/": {"results": [1], "next": next_url}}
    with pytest.raises(PaginationOriginError) as caught:
        list(_iterator(pages, fetched))
    assert isinstance(caught.value, HttpProblemError)
    assert caught.value.problem.type.endswith("cross-origin-next-url")
    assert fetched == ["hosts/"]


@pytest.mark.spec("SCION-CENTRALIZED-CAPABILITIES-R004.1")
@pytest.mark.parametrize(
    "next_url",
    [
        "https://reader:secret@tower.test/api/v2/hosts/",
        "https://reader:secret@evil.test/api/v2/hosts/",
        "https://tower.test:secret/api/v2/hosts/",
        "https://[secret/api/v2/hosts/",
    ],
)
def test_rejects_unsafe_next_without_exposing_credentials(next_url: str):
    fetched: list[str] = []
    pages = {"hosts/": {"results": [1], "next": next_url}}
    with pytest.raises(PaginationOriginError) as caught:
        list(_iterator(pages, fetched))
    assert fetched == ["hosts/"]
    assert "secret" not in str(caught.value)
    assert "secret" not in caught.value.problem.model_dump_json()


@pytest.mark.spec("SCION-CENTRALIZED-CAPABILITIES-R004.1")
@pytest.mark.parametrize(
    "endpoint", ["https://reader:secret@tower.test/", "https://tower.test:secret/"]
)
def test_rejects_unsafe_initial_url_before_fetch(endpoint: str):
    fetched: list[str] = []
    iterator = PaginationIterator(_pages({}, fetched), endpoint, mode="next_url")
    with pytest.raises(PaginationOriginError) as caught:
        list(iterator)
    assert not fetched
    assert "secret" not in str(caught.value)
    assert "secret" not in caught.value.problem.model_dump_json()


@pytest.mark.spec("SCION-CENTRALIZED-CAPABILITIES-R004.1")
@pytest.mark.parametrize(
    "next_url",
    [
        "https://reader:secret@tower.test/",
        "https://reader:secret@evil.test/",
        "https://tower.test:secret/",
    ],
)
async def test_async_rejects_unsafe_next_before_fetch(next_url: str):
    fetched: list[str] = []

    async def fetch(url, params):
        fetched.append(url)
        return {"results": [1], "next": next_url}, {}

    iterator = AsyncPaginationIterator(
        fetch, "hosts/", mode="next_url", base_url=BASE, items_path="results"
    )
    with pytest.raises(PaginationOriginError) as caught:
        _ = [item async for item in iterator]
    assert fetched == ["hosts/"]
    assert "secret" not in str(caught.value)
    assert "secret" not in caught.value.problem.model_dump_json()


@pytest.mark.spec("SCION-CENTRALIZED-CAPABILITIES-R004.1")
async def test_async_rejects_unsafe_initial_url_before_fetch():
    fetched: list[str] = []

    async def fetch(url, params):
        fetched.append(url)
        return {}, {}

    iterator = AsyncPaginationIterator(
        fetch, "https://reader:secret@tower.test/", mode="next_url"
    )
    with pytest.raises(PaginationOriginError) as caught:
        _ = [item async for item in iterator]
    assert not fetched
    assert "secret" not in str(caught.value)


def test_loop_guard_stops_on_a_repeated_url():
    fetched: list[str] = []
    page2 = "https://tower.test/api/v2/hosts/?page=2"
    pages = {
        "hosts/": {"results": [1], "next": page2},
        page2: {"results": [2], "next": "/api/v2/hosts/?page=2"},
    }
    iterator = _iterator(pages, fetched)
    assert list(iterator) == [1, 2]
    assert fetched == ["hosts/", page2]
    assert iterator.truncated is True


def test_page_cap_bounds_the_sweep():
    def fetch(url, params):
        page = int(url.rsplit("=", 1)[1]) if "=" in url else 1
        return {"results": [page], "next": f"?page={page + 1}"}, {}

    iterator = PaginationIterator(
        fetch,
        "hosts/",
        mode="next_url",
        base_url=BASE,
        items_path="results",
        max_pages=3,
    )
    assert list(iterator) == [1, 2, 3]
    assert iterator.truncated is True


def test_relative_endpoint_without_base_url_is_rejected():
    with pytest.raises(ValueError, match="base_url"):
        list(PaginationIterator(lambda u, p: ({}, {}), "hosts/", mode="next_url"))


async def test_async_next_url():
    async def fetch(url, params):
        if url == "hosts/":
            return {"results": [1], "next": "/api/v2/hosts/?page=2"}, {}
        return {"results": [2], "next": None}, {}

    iterator = AsyncPaginationIterator(
        fetch, "hosts/", mode="next_url", base_url=BASE, items_path="results"
    )
    assert [item async for item in iterator] == [1, 2]
    assert Exported is PaginationOriginError
