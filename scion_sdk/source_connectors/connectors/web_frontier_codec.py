"""Validate and serialize a bounded web crawl frontier."""

from __future__ import annotations

from collections import deque
from typing import Any

from ..base import ConnectorCheckpoint
from .web_frontier_types import _FRONTIER_LIMIT, _Crawler, _Frontier


class _FrontierCodec:
    def __init__(self, crawler: _Crawler) -> None:
        self.crawler = crawler

    def state(self, frontier: _Frontier) -> dict[str, Any]:
        if not frontier.queue:
            return {}
        return {
            "base_url": self.crawler.base_url,
            "max_depth": self.crawler.max_depth,
            "same_domain": self.crawler.same_domain,
            "queue": list(frontier.queue),
            "visited": sorted(frontier.visited),
        }

    def resume(self, checkpoint: ConnectorCheckpoint | None) -> _Frontier:
        if checkpoint is None or not checkpoint.has_more:
            base = self.crawler.base_url
            return _Frontier(deque([(base, 0)]), set(), {base})
        state = checkpoint.state
        self._validate_scope(state)
        visited = self._parse_visited(state.get("visited"))
        queue = self._parse_queue(state.get("queue"), visited)
        return _Frontier(queue, visited, {url for url, _depth in queue})

    def _validate_scope(self, state: dict[str, Any]) -> None:
        depth = state.get("max_depth")
        if (
            state.get("base_url") != self.crawler.base_url
            or not isinstance(depth, int)
            or isinstance(depth, bool)
            or depth != self.crawler.max_depth
            or state.get("same_domain") is not self.crawler.same_domain
        ):
            raise ValueError("web crawl checkpoint does not match this source")

    def _parse_visited(self, raw: object) -> set[str]:
        if not isinstance(raw, list) or len(raw) > _FRONTIER_LIMIT:
            raise ValueError("web crawl checkpoint frontier is invalid")
        visited: set[str] = set()
        for url in raw:
            if not self.crawler._valid_checkpoint_url(url) or url in visited:
                raise ValueError("web crawl checkpoint frontier is invalid")
            visited.add(url)
        return visited

    def _parse_queue(self, raw: object, visited: set[str]) -> deque[tuple[str, int]]:
        if not isinstance(raw, list) or not raw or len(raw) > _FRONTIER_LIMIT:
            raise ValueError("web crawl checkpoint frontier is invalid")
        queue: deque[tuple[str, int]] = deque()
        queued: set[str] = set()
        for entry in raw:
            url, depth = self._parse_entry(entry)
            if url in visited or url in queued:
                raise ValueError("web crawl checkpoint frontier is invalid")
            queue.append((url, depth))
            queued.add(url)
        return queue

    def _parse_entry(self, entry: object) -> tuple[str, int]:
        if not isinstance(entry, (list, tuple)) or len(entry) != 2:
            raise ValueError("web crawl checkpoint frontier is invalid")
        url, depth = entry
        if not isinstance(url, str) or not self.crawler._valid_checkpoint_url(url):
            raise ValueError("web crawl checkpoint frontier is invalid")
        if (
            not isinstance(depth, int)
            or isinstance(depth, bool)
            or not 0 <= depth <= self.crawler.max_depth
        ):
            raise ValueError("web crawl checkpoint frontier is invalid")
        return url, depth
