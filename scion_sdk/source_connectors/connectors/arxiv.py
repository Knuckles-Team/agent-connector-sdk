"""Native arXiv document-source connector (zero-infra, CONCEPT:AU-KG.ingest.arxiv-feed-connector).

Drives the public ``export.arxiv.org`` Atom query API directly — no external MCP
server or account is required, mirroring the zero-infra ``rss``/``web`` connectors
(CONCEPT:AU-ECO.connector.document-source-framework). This is deliberately a THIRD, narrower research feed
alongside ``freshrss`` (curated world-model RSS, gated by ``WorldModelPipelineRunner``)
and ScholarX (paper search/dedup service reached via ``scholarx-mcp``): it is the raw
per-category arXiv listing, useful when neither of those is deployed.

Each entry is emitted with the SAME ``metadata["record"]`` envelope shape as
:func:`the host feed collector` and the
native ``rss`` connector (``canonical`` + ``origin.streamId``), so it converges on
the identical canonical ``arxiv:<id>`` node the moment ``WorldModelPipelineRunner``
(CONCEPT:AU-KG.ingest.worldmodel-gated-ingestion) routes it to the research path — one paper arriving via
FreshRSS-arXiv, ScholarX, AND this connector collapses to one KG node, never three.

**Budget-bounded by construction, never a firehose (the ★ critical constraint of
CONCEPT:AU-KG.ingest.arxiv-feed-connector):** ``categories`` has NO default — an operator must opt in
explicitly (``KG_ARXIV_CATEGORIES``) — and ``max_results`` caps each category's
per-poll page size. The connector itself does no relevance scoring; every entry it
yields still passes through the SAME downstream gate as every other research feed
(``grade_and_enqueue_paper`` — keyword score + novelty dedup + KG-stored watchlists),
so this connector only ever WIDENS the funnel's mouth, never bypasses its throat.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Iterator
from typing import Any

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
from ._arxiv_entries import _entry_document
from ._feed_common import _checkpointed_delta

FetchFn = Callable[[str, dict[str, Any]], str]

#: The public arXiv Atom query API (no auth, no key — export.arxiv.org's documented
#: rate-limit courtesy window is ~1 request/3s per the arXiv API terms of use; the
#: per-category cap plus the sweep cadence keeps this connector well under that).
logger = logging.getLogger(__name__)

_ARXIV_API_URL = "https://export.arxiv.org/api/query"
#: Hard ceiling on ``max_results`` — arXiv's own API caps a single page at 2000, but
#: nothing here needs to approach that; the operator-facing default is far lower.
_MAX_RESULTS_CEILING = 500
_FETCH_TIMEOUT_S = 20.0


@register_source("arxiv")
class ArxivConnector(LoadConnector, PollConnector):
    """Fetch + parse the arXiv Atom query API into research-paper documents.

    Config:
        categories: One or more arXiv category codes (e.g. ``cs.AI``), REQUIRED —
            there is no default; an unscoped query is not a valid arXiv listing and
            would be an unbounded firehose (CONCEPT:AU-KG.ingest.arxiv-feed-connector).
        max_results: Per-category, per-poll page cap (default 50, capped at 500).
        doc_type: Document-type hint stamped on each item (default ``paper``).
        source_name: ``source_system`` provenance label (default ``arxiv``).
        fetch_fn: Optional ``(url, params) -> atom_xml`` injectable for offline tests.
    """

    provider = "arXiv API"

    def configure(
        self,
        *,
        categories: list[str] | str | tuple[str, ...] = (),
        max_results: int = 50,
        doc_type: str = "paper",
        source_name: str = "arxiv",
        fetch_fn: FetchFn | None = None,
        allowed_private_hosts: list[str] | None = None,
        max_response_bytes: int = 10 * 1024 * 1024,
        **_: object,
    ) -> None:
        cats = [categories] if isinstance(categories, str) else list(categories or [])
        self.categories = [c for c in (s.strip() for s in cats) if c]
        if not self.categories:
            raise ValueError(
                "ArxivConnector requires one or more 'categories' — an unscoped "
                "query is not supported (would be an unbounded firehose)"
            )
        if len(self.categories) > 50:
            raise ValueError("ArxivConnector accepts at most 50 categories")
        self.max_results = min(_MAX_RESULTS_CEILING, max(1, int(max_results)))
        self.doc_type = doc_type
        self.source_name = source_name
        self.external_access = default_external_access()
        require_safe_source_url(
            _ARXIV_API_URL,
            allowed_private_hosts=list(allowed_private_hosts or []),
            resolve_dns=False,
        )
        if fetch_fn is not None:
            self._fetch = fetch_fn
        else:

            def _safe_fetch(url: str, params: dict[str, Any]) -> str:
                return safe_get_text(
                    url,
                    params=params,
                    timeout=_FETCH_TIMEOUT_S,
                    headers={"User-Agent": "agent-utilities-arxiv/1.0"},
                    max_bytes=max_response_bytes,
                    allowed_private_hosts=list(allowed_private_hosts or []),
                )

            self._fetch = _safe_fetch

    def health_check(self) -> bool:
        return bool(self.categories)

    # -- parsing -----------------------------------------------------------

    def _parse(self, content: str) -> Any:
        try:
            import feedparser
        except (
            ImportError
        ) as exc:  # pragma: no cover - dependency declared in pyproject
            raise RuntimeError(
                "ArxivConnector needs 'feedparser' to parse the Atom response "
                "(declared in pyproject dependencies)."
            ) from exc
        return feedparser.parse(content)

    def _category_entries(self, category: str) -> tuple[list[SourceDocument], bool]:
        """Fetch + parse one category's most recent entries (a dead category → [])."""
        params = {
            "search_query": f"cat:{category}",
            "sortBy": "submittedDate",
            "sortOrder": "descending",
            "start": 0,
            "max_results": self.max_results,
        }
        try:
            content = self._fetch(_ARXIV_API_URL, params)
        except Exception as exc:
            # Never a bare `return []`: an outage for this category would then be
            # indistinguishable from "arXiv published nothing new", which is the
            # swallowed-error anti-pattern this repo bans. Degrade the SWEEP, not
            # the diagnosis — the cause is kept.
            logger.warning(
                "arXiv category %s could not be fetched — treating it as empty "
                "for this sweep: %s",
                category,
                exc,
                exc_info=exc,
            )
            return [], False
        parsed = self._parse(content)
        if parsed.bozo:
            logger.warning("arXiv category %s returned a malformed feed", category)
            return [], False
        out = [
            doc
            for entry in parsed.entries or []
            if (
                doc := _entry_document(
                    entry,
                    category=category,
                    doc_type=self.doc_type,
                    source_name=self.source_name,
                    external_access=self.external_access,
                )
            )
            is not None
        ]
        return out, True

    def _all_documents(self) -> tuple[list[SourceDocument], bool]:
        """Fetch every configured category, deduping papers cross-listed in >1."""
        seen: set[str] = set()
        docs: list[SourceDocument] = []
        complete = True
        for category in self.categories:
            entries, succeeded = self._category_entries(category)
            complete = complete and succeeded
            for doc in entries:
                if doc.id in seen:
                    continue
                seen.add(doc.id)
                docs.append(doc)
        return docs, complete

    # -- LoadConnector -------------------------------------------------------

    def load(self) -> Iterator[SourceDocument]:
        documents, _complete = self._all_documents()
        yield from documents

    # -- PollConnector ---------------------------------------------------------

    def poll(self, checkpoint: ConnectorCheckpoint | None = None) -> CheckpointedBatch:
        """Emit only entries newer than the prior watermark AND not already seen.

        Same dual-guard shape as the native ``rss`` connector: the submitted-date
        watermark is the primary delta, the seen-id belt catches same-date dupes.
        arXiv's API has no server-side "since" filter, so each poll re-fetches the
        (bounded) most-recent page per category and filters client-side — the
        ``max_results`` cap is what keeps this a bounded read, not a full re-scan.
        """
        all_docs, complete = self._all_documents()
        return _checkpointed_delta(checkpoint, all_docs, complete=complete)
