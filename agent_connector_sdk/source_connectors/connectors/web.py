"""Recursive web-crawler document-source connector.

CONCEPT:AU-ECO.connector.document-source-framework — reference ``Load`` + ``Poll`` connector.
CONCEPT:AU-ECO.connector.incremental-poll-watermark — incremental poll keyed on a crawl-time watermark + seen ids.

A same-domain breadth-first crawler. Pages are fetched (lazy ``httpx``; the caller
may inject a ``fetch_fn`` for offline tests), converted HTML→text via the
``markitdown`` soft-dep (falling back to a light tag strip — the same degradation
the ingestion engine's URL path uses), and yielded as :class:`SourceDocument`s.
No new hard dependency is added: ``httpx`` is imported lazily and a clear
RuntimeError is raised only when an actual network fetch is attempted without it.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Callable, Iterator
from urllib.parse import urldefrag, urljoin, urlparse

from ..base import (
    CheckpointedBatch,
    ConnectorCheckpoint,
    LoadConnector,
    PollConnector,
    SourceDocument,
    default_external_access,
)
from ..http_safety import require_safe_source_url, safe_get_text
from ..registry import register_source
from .web_frontier import _FrontierRunner
from .web_frontier_codec import _FrontierCodec
from .web_frontier_types import _URL_LIMIT
from .web_page import _check_base_url, _html_to_text

logger = logging.getLogger(__name__)

FetchFn = Callable[[str], str]

_LINK_RE = re.compile(r'href=["\']([^"\'#]+)["\']', re.IGNORECASE)
_TITLE_RE = re.compile(r"<title[^>]*>(.*?)</title>", re.IGNORECASE | re.DOTALL)


@register_source("web")
class WebCrawlerConnector(LoadConnector, PollConnector):
    """Recursively crawl a website, same-domain, into documents.

    CONCEPT:AU-ECO.connector.document-source-framework.

    Config:
        base_url: Seed URL (required).
        max_depth: Link-following depth from the seed (default 1).
        max_pages: Hard cap on pages fetched per poll or load (default 50).
        same_domain: Restrict to the seed's host (default True).
        fetch_fn: Optional ``(url) -> html`` injectable for offline tests.
    """

    provider = "Web Crawler"

    def configure(
        self,
        *,
        base_url: str = "",
        max_depth: int = 1,
        max_pages: int = 50,
        same_domain: bool = True,
        fetch_fn: FetchFn | None = None,
        allowed_private_hosts: list[str] | None = None,
        allowed_redirect_hosts: list[str] | None = None,
        max_response_bytes: int = 10 * 1024 * 1024,
        **_: object,
    ) -> None:
        _check_base_url(base_url)
        allowed_private_hosts = list(allowed_private_hosts or [])
        self._allowed_private_hosts = allowed_private_hosts
        self._host = require_safe_source_url(
            base_url,
            allowed_private_hosts=allowed_private_hosts,
            resolve_dns=False,
        )
        self.base_url = base_url
        self.max_depth = min(10, max(0, int(max_depth)))
        self.max_pages = min(10_000, max(1, int(max_pages)))
        self.same_domain = same_domain
        self.external_access = default_external_access()
        if fetch_fn is not None:
            self._fetch = fetch_fn
        else:
            redirect_hosts = list(allowed_redirect_hosts or [])

            def _safe_fetch(url: str) -> str:
                return safe_get_text(
                    url,
                    timeout=60.0,
                    max_bytes=max_response_bytes,
                    allowed_private_hosts=allowed_private_hosts,
                    allowed_redirect_hosts=redirect_hosts,
                )

            self._fetch = _safe_fetch

    def health_check(self) -> bool:
        return bool(self.base_url)

    def _same_domain(self, url: str) -> bool:
        return (not self.same_domain) or (
            (urlparse(url).hostname or "").lower().rstrip(".") == self._host
        )

    def _extract_links(self, base: str, html: str) -> list[str]:
        out: list[str] = []
        for href in _LINK_RE.findall(html):
            absolute, _ = urldefrag(urljoin(base, href))
            if absolute.startswith(("http://", "https://")) and self._same_domain(
                absolute
            ):
                out.append(absolute)
        return out

    def _crawl(self, skip_ids: set[str] | None = None) -> Iterator[SourceDocument]:
        """BFS from the seed up to ``max_depth`` / ``max_pages``.

        ``skip_ids`` lets the incremental poll avoid re-emitting already-seen URLs.
        """
        skip = skip_ids or set()
        seen: set[str] = set()
        queue: list[tuple[str, int]] = [(self.base_url, 0)]
        while queue and len(seen) < self.max_pages:
            url, depth = queue.pop(0)
            if url in seen:
                continue
            seen.add(url)
            try:
                html = self._fetch(url)
            except Exception as exc:  # one unreachable page must not stop the crawl
                logger.warning("web crawl skipped %s: %s", url, exc)
                continue
            document = self._document(url, depth, html)
            if document is not None and url not in skip:
                yield document
            if depth >= self.max_depth:
                continue
            for link in self._extract_links(url, html):
                if link not in seen:
                    queue.append((link, depth + 1))

    # -- LoadConnector -----------------------------------------------------

    def load(self) -> Iterator[SourceDocument]:
        yield from self._crawl()

    def _document(self, url: str, depth: int, html: str) -> SourceDocument | None:
        text = _html_to_text(html)
        if not text.strip():
            return None
        title_match = _TITLE_RE.search(html)
        title = (title_match.group(1).strip() if title_match else url)[:200]
        return SourceDocument(
            id=url,
            source_uri=url,
            title=title,
            text=text,
            doc_type="webpage",
            metadata={"depth": depth},
            external_access=self.external_access.model_copy(deep=True),
        )

    # -- PollConnector -----------------------------------------------------

    def poll(self, checkpoint: ConnectorCheckpoint | None = None) -> CheckpointedBatch:
        """Fetch at most ``max_pages`` and resume an unfinished crawl."""
        prior_ids = set(checkpoint.seen_ids) if checkpoint else set()
        codec = _FrontierCodec(self)
        frontier = codec.resume(checkpoint)
        documents = _FrontierRunner(self).drain(frontier, prior_ids)
        cp = ConnectorCheckpoint(
            has_more=bool(frontier.queue),
            seen_ids=sorted(prior_ids | {d.id for d in documents}),
            state=codec.state(frontier),
        )
        return CheckpointedBatch(documents=documents, checkpoint=cp)

    def _valid_checkpoint_url(self, url: object) -> bool:
        if not isinstance(url, str) or len(url) > _URL_LIMIT:
            return False
        try:
            require_safe_source_url(
                url,
                allowed_private_hosts=self._allowed_private_hosts,
                resolve_dns=False,
            )
            return self._same_domain(url)
        except ValueError:
            return False
