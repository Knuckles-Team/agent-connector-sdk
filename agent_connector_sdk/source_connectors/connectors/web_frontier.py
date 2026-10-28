"""Consume a bounded web crawl frontier."""

from __future__ import annotations

import logging

from ..base import SourceDocument
from .web_frontier_types import _FRONTIER_LIMIT, _URL_LIMIT, _Crawler, _Frontier

logger = logging.getLogger(__name__)


class _FrontierRunner:
    def __init__(self, crawler: _Crawler) -> None:
        self.crawler = crawler

    def drain(self, frontier: _Frontier, prior_ids: set[str]) -> list[SourceDocument]:
        documents: list[SourceDocument] = []
        fetched = 0
        while frontier.queue and fetched < self.crawler.max_pages:
            url, depth = frontier.queue.popleft()
            frontier.queued.remove(url)
            if len(frontier.visited) >= _FRONTIER_LIMIT:
                raise ValueError("web crawl frontier exceeds its bound")
            frontier.visited.add(url)
            fetched += 1
            document = self._fetch_one(frontier, url, depth)
            if document is not None and url not in prior_ids:
                documents.append(document)
        return documents

    def _fetch_one(
        self, frontier: _Frontier, url: str, depth: int
    ) -> SourceDocument | None:
        try:
            html = self.crawler._fetch(url)
        except Exception as exc:
            logger.warning("web crawl skipped %s: %s", url, exc)
            return None
        if depth < self.crawler.max_depth:
            self._enqueue_links(frontier, url, depth, html)
        return self.crawler._document(url, depth, html)

    def _enqueue_links(
        self, frontier: _Frontier, url: str, depth: int, html: str
    ) -> None:
        for link in self.crawler._extract_links(url, html):
            if link in frontier.visited or link in frontier.queued:
                continue
            if len(link) > _URL_LIMIT or len(frontier.queue) >= _FRONTIER_LIMIT:
                raise ValueError("web crawl frontier exceeds its bound")
            if self.crawler._valid_checkpoint_url(link):
                frontier.queue.append((link, depth + 1))
                frontier.queued.add(link)
