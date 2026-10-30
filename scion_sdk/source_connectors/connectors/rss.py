"""Native RSS/Atom feed document-source connector (zero-infra).

CONCEPT:AU-KG.ingest.rss-feed-connector — native zero-infra RSS/Atom feed extractor and unified feed source.
Point it at one or more feed URLs and it yields each entry as a
:class:`SourceDocument`, with NO
external service required (unlike the FreshRSS feeder, which aggregates many feeds
behind its own server). It is the RSS analog of the zero-infra ``filesystem`` /
``web`` connectors.

Parsing uses ``feedparser`` (imported lazily so the module imports without it;
a clear error is raised only when an actual parse is attempted), which robustly
handles RSS 0.9x/1.0/2.0 + Atom + malformed feeds. Each entry is emitted with a
``metadata["record"]`` envelope (``categories`` + ``origin``) so it flows through
the SAME ``WorldModelPipelineRunner`` gate as the FreshRSS and ScholarX sources —
arXiv/research entries route to the research path, news entries to the world-model
gate. The incremental ``poll`` advances on the entry publish date plus a seen-id
belt for feeds with missing/equal dates.
"""

from __future__ import annotations

from collections.abc import Iterator

from ..base import (
    CheckpointedBatch,
    ConnectorCheckpoint,
    LoadConnector,
    PollConnector,
    SourceDocument,
    default_external_access,
)
from ..http_safety import require_safe_source_url
from ..registry import register_source
from ._feed_common import _checkpointed_delta
from ._rss_entries import (
    FetchFn,
    _build_safe_fetch,
    _entry_document,
    _normalize_feed_urls,
    _parse_feed,
)

#: Max feeds fetched concurrently per sweep (bounds sockets/threads; the sweep
#: scales to many feeds without a serial stall — the 2000-reviews/hr path).
_FEED_FETCH_CONCURRENCY = 12


@register_source("rss")
class RssConnector(LoadConnector, PollConnector):
    """Fetch + parse arbitrary RSS/Atom feeds into documents (CONCEPT:AU-KG.ingest.rss-feed-connector).

    Config:
        feed_urls: One URL or a list of feed URLs (required).
        max_items: Per-feed entry cap (default 200).
        doc_type: Document-type hint stamped on each item (default ``feed_item``).
        source_name: ``source_system`` provenance label (default ``rss``).
        fetch_fn: Optional ``(url) -> feed_content`` injectable for offline tests.
    """

    provider = "RSS/Atom Feed"

    def configure(
        self,
        *,
        feed_urls: list[str] | str | tuple[str, ...] = (),
        max_items: int = 200,
        doc_type: str = "feed_item",
        source_name: str = "rss",
        fetch_fn: FetchFn | None = None,
        allowed_private_hosts: list[str] | None = None,
        allowed_redirect_hosts: list[str] | None = None,
        max_response_bytes: int = 10 * 1024 * 1024,
        **_: object,
    ) -> None:
        self.feed_urls = _normalize_feed_urls(feed_urls)
        private_hosts = list(allowed_private_hosts or [])
        for url in self.feed_urls:
            require_safe_source_url(
                url, allowed_private_hosts=private_hosts, resolve_dns=False
            )
        self.max_items = min(10_000, max(1, int(max_items)))
        self.doc_type = doc_type
        self.source_name = source_name
        self.external_access = default_external_access()
        self._fetch = fetch_fn or _build_safe_fetch(
            allowed_private_hosts=private_hosts,
            allowed_redirect_hosts=list(allowed_redirect_hosts or []),
            max_response_bytes=max_response_bytes,
        )

    def health_check(self) -> bool:
        return bool(self.feed_urls)

    # -- parsing -----------------------------------------------------------

    def _entries(self, url: str) -> tuple[list[SourceDocument], bool]:
        """Fetch + parse one feed into SourceDocuments (a dead feed → ``[]``)."""
        try:
            content = self._fetch(url)
        except Exception:
            return [], False
        parsed = _parse_feed(content)
        feed_title = str((parsed.feed or {}).get("title") or url)
        out = [
            doc
            for entry in (parsed.entries or [])[: self.max_items]
            if (
                doc := _entry_document(
                    entry,
                    url=url,
                    feed_title=feed_title,
                    doc_type=self.doc_type,
                    source_name=self.source_name,
                    external_access=self.external_access,
                )
            )
            is not None
        ]
        return out, not bool(parsed.bozo)

    def _all_documents(self) -> tuple[list[SourceDocument], bool]:
        """Fetch + parse every feed CONCURRENTLY so one slow feed can't stall the
        sweep. Each ``_entries`` call is bounded by the per-feed fetch timeout and
        degrades to ``[]`` on error, so the whole pass costs ~the slowest single
        feed (x ceil(N / concurrency)) instead of the serial sum — the throughput
        unlock for many-feed sweeps (the 2000-reviews/hr path). (CONCEPT:AU-KG.ingest.rss-feed-connector)"""
        urls = self.feed_urls
        if len(urls) <= 1:
            return self._entries(urls[0]) if urls else ([], True)
        from concurrent.futures import ThreadPoolExecutor

        docs: list[SourceDocument] = []
        complete = True
        workers = min(len(urls), _FEED_FETCH_CONCURRENCY)
        with ThreadPoolExecutor(
            max_workers=workers, thread_name_prefix="rss-fetch"
        ) as ex:
            # ex.map preserves feed order; _entries never raises (dead feed → []).
            for batch, succeeded in ex.map(self._entries, urls):
                docs.extend(batch)
                complete = complete and succeeded
        return docs, complete

    # -- LoadConnector -----------------------------------------------------

    def load(self) -> Iterator[SourceDocument]:
        documents, _complete = self._all_documents()
        yield from documents

    # -- PollConnector -----------------------------------------------------

    def poll(self, checkpoint: ConnectorCheckpoint | None = None) -> CheckpointedBatch:
        """Emit only entries newer than the prior watermark AND not already seen.

        Dual guard (CONCEPT:AU-KG.ingest.rss-feed-connector): the publish-date watermark is the primary
        delta; the seen-id belt catches feeds with missing or identical dates so a
        re-poll never re-emits an unchanged entry.
        """
        all_docs, complete = self._all_documents()
        return _checkpointed_delta(checkpoint, all_docs, complete=complete)
