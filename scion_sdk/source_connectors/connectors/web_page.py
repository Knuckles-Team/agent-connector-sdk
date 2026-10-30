"""Page validation and text extraction for the web source."""

from __future__ import annotations

import logging
import re
from collections.abc import Callable

from ..http_safety import safe_get_text
from .web_frontier_types import _URL_LIMIT

logger = logging.getLogger(__name__)


def _check_base_url(url: str) -> None:
    if not url or len(url) > _URL_LIMIT:
        raise ValueError("WebCrawlerConnector requires a valid 'base_url'")


def _html_to_text(html: str) -> str:
    """HTML → text via markitdown, falling back to a regex tag strip."""
    try:
        return _convert_html(html)
    except Exception:
        text = re.sub(r"(?is)<(script|style)[^>]*>.*?</\1>", " ", html)
        text = re.sub(r"<[^>]+>", " ", text)
        return re.sub(r"\s+", " ", text).strip()


def _convert_html(html: str) -> str:
    import tempfile

    from markitdown import MarkItDown

    with tempfile.NamedTemporaryFile(
        "w", suffix=".html", delete=True, encoding="utf-8"
    ) as tmp:
        tmp.write(html)
        tmp.flush()
        return str(MarkItDown().convert(tmp.name).text_content)


def _fetch_page_or_none(fetch: Callable[[str], str], url: str) -> str | None:
    """Fetch one page; an unreachable page yields ``None`` and must not stop a crawl."""
    try:
        return fetch(url)
    except Exception as exc:
        logger.warning("web crawl skipped %s: %s", url, exc)
        return None


def _build_safe_fetch(
    *,
    allowed_private_hosts: list[str],
    allowed_redirect_hosts: list[str],
    max_response_bytes: int,
) -> Callable[[str], str]:
    def _safe_fetch(url: str) -> str:
        return safe_get_text(
            url,
            timeout=60.0,
            max_bytes=max_response_bytes,
            allowed_private_hosts=allowed_private_hosts,
            allowed_redirect_hosts=allowed_redirect_hosts,
        )

    return _safe_fetch
