"""Single-consumer iteration over a pagination walk."""

from __future__ import annotations

from collections.abc import AsyncIterator, Iterator
from contextlib import contextmanager
from typing import Any


@contextmanager
def _claim(owner: Any) -> Iterator[None]:
    if not owner._iteration_lock.acquire(blocking=False):
        raise RuntimeError("pagination iterator already has an active consumer")
    try:
        yield
    finally:
        owner._iteration_lock.release()


def _iterate(owner: Any) -> Iterator[Any]:
    with _claim(owner):
        owner._begin(owner._new_walk())
        request = owner._walk.start()
        while request is not None:
            url, params = request
            data, headers = owner._fetch_page(url, params or None)
            items = owner._extract_items(data)
            to_yield, request = owner._consume_page(items, data, headers)
            yield from to_yield


async def _iterate_async(owner: Any) -> AsyncIterator[Any]:
    with _claim(owner):
        owner._begin(owner._new_walk())
        request = owner._walk.start()
        while request is not None:
            url, params = request
            data, headers = await owner._fetch_page(url, params or None)
            items = owner._extract_items(data)
            to_yield, request = owner._consume_page(items, data, headers)
            for item in to_yield:
                yield item
