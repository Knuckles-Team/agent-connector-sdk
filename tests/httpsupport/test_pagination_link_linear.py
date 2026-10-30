"""Link parsing preserves its first-match grammar on adversarial headers."""

from __future__ import annotations

import random
import re

import pytest

from scion_sdk.httpsupport.pagination import PaginationIterator
from scion_sdk.httpsupport.pagination_link import next_link


@pytest.mark.spec("SCION-CENTRALIZED-CAPABILITIES-R004.3")
def test_link_parser_matches_existing_grammar():
    original = re.compile(r'<(?P<url>[^>]+)>\s*;[^,]*\brel="?next"?')
    rng = random.Random(4)
    parts = ("<", ">", ";", ",", " ", "rel", "next", '"', "x", "\n", "=")
    cases = [
        '<one>; rel="prev", <two>; rel="next"',
        "<a<b>; rel=next",
        '<a>; xrel=next; rel="next"',
        '<a>; title="rel=next"',
    ]
    cases.extend("".join(rng.choices(parts, k=rng.randrange(30))) for _ in range(5000))
    for raw in cases:
        match = original.search(raw)
        assert next_link(raw) == (match.group("url") if match else None)


@pytest.mark.spec("SCION-CENTRALIZED-CAPABILITIES-R004.3")
@pytest.mark.parametrize("header", ["<" * 100_000, "<x>; a=1 " * 20_000])
def test_link_parser_handles_large_malformed_header(header):
    calls = []

    def fetch(url, params):
        calls.append(url)
        return [1], {"Link": header}

    result = PaginationIterator(
        fetch, "https://example.test/items", mode="link", max_pages=2
    ).collect()
    assert result["data"] == [1]
    assert len(calls) == 1
