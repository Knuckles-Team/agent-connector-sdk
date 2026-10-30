"""Link pagination must not send authenticated requests across origins."""

from __future__ import annotations

import pytest

from scion_sdk.httpsupport.pagination import (
    AsyncPaginationIterator,
    PaginationIterator,
    PaginationOriginError,
)

pytestmark = pytest.mark.spec("SCION-CENTRALIZED-CAPABILITIES-R004.2")


@pytest.mark.parametrize(
    "target",
    [
        "https://evil.test/users",
        "//evil.test/users",
        "http://api.test/users",
        "https://api.test:0/users",
        "https://reader:secret@api.test/users",
        "https://reader:secret@evil.test/users",
        "https://api.test:secret/users",
    ],
)
def test_link_rejects_unsafe_next_before_fetch(target: str) -> None:
    fetched: list[str] = []

    def fetch(url, params):
        fetched.append(url)
        return [1], {"Link": f'<{target}>; rel="next"'}

    iterator = PaginationIterator(
        fetch, "/users", mode="link", base_url="https://api.test"
    )
    with pytest.raises(PaginationOriginError) as caught:
        list(iterator)
    assert fetched == ["/users"]
    assert "secret" not in str(caught.value)
    assert "secret" not in caught.value.problem.model_dump_json()


def test_link_without_base_refuses_before_fetch() -> None:
    fetched: list[str] = []
    iterator = PaginationIterator(
        lambda url, params: (fetched.append(url), {}), "/users", mode="link"
    )
    with pytest.raises(ValueError, match="absolute endpoint or base_url"):
        list(iterator)
    assert not fetched


def test_link_resolves_relative_next_and_stops_on_loop() -> None:
    fetched: list[str] = []

    def fetch(url, params):
        fetched.append(url)
        return [1], {"Link": '<?page=2>; rel="next"'}

    iterator = PaginationIterator(
        fetch, "/users", mode="link", base_url="https://api.test"
    )
    assert list(iterator) == [1, 1]
    assert fetched == ["/users", "https://api.test/users?page=2"]
    assert iterator.truncated
    assert iterator.next_cursor is None


async def test_async_link_rejects_cross_origin() -> None:
    fetched: list[str] = []

    async def fetch(url, params):
        fetched.append(url)
        return [1], {"Link": '<https://reader:secret@evil.test/users>; rel="next"'}

    iterator = AsyncPaginationIterator(fetch, "https://api.test/users", mode="link")
    with pytest.raises(PaginationOriginError) as caught:
        _ = [item async for item in iterator]
    assert fetched == ["https://api.test/users"]
    assert "secret" not in caught.value.problem.model_dump_json()


async def test_async_link_without_base_refuses_before_fetch() -> None:
    fetched: list[str] = []

    async def fetch(url, params):
        fetched.append(url)
        return [], {}

    iterator = AsyncPaginationIterator(fetch, "/users", mode="link")
    with pytest.raises(ValueError, match="absolute endpoint or base_url"):
        _ = [item async for item in iterator]
    assert not fetched
