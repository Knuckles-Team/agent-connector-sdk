"""Types shared by bounded web crawl frontier components."""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from typing import Protocol

from ..base import SourceDocument

_FRONTIER_LIMIT = 10_000
_URL_LIMIT = 4096


class _Crawler(Protocol):
    base_url: str
    max_depth: int
    max_pages: int
    same_domain: bool

    def _fetch(self, url: str) -> str: ...
    def _document(self, url: str, depth: int, html: str) -> SourceDocument | None: ...
    def _extract_links(self, url: str, html: str) -> list[str]: ...
    def _valid_checkpoint_url(self, url: object) -> bool: ...


@dataclass
class _Frontier:
    queue: deque[tuple[str, int]]
    visited: set[str]
    queued: set[str]
