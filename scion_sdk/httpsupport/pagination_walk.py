"""The pure pagination state machine and its origin guard."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any
from urllib.parse import urljoin, urlsplit

from scion_sdk.http.errors import HttpProblemError
from scion_sdk.http.pagination import _origin
from scion_sdk.http.problems import ProblemDetails
from scion_sdk.httpsupport.pagination_link import _link_next_url
from scion_sdk.httpsupport.pagination_page import _dig
from scion_sdk.httpsupport.pagination_tokens import (
    _advance_cursor,
    _advance_numbered,
    _advance_since,
    _TokenHistory,
)

#: Pagination dialects supported by the iterators.
PAGINATION_MODES = ("cursor", "page", "offset", "link", "since_id", "next_url")


class PaginationOriginError(HttpProblemError):
    """A next-page URL leaves the scheme, host, or port of the first request."""

    @classmethod
    def for_url(cls, url: str) -> PaginationOriginError:
        del url
        return cls(
            ProblemDetails.sdk(
                "cross-origin-next-url",
                "Pagination URL is outside the permitted origin",
                detail="Pagination URL is invalid or not permitted",
            )
        )


def _safe_origin(url: str) -> tuple[str, str, int | None]:
    """Validate an HTTP(S) origin without copying credentials into errors."""
    try:
        parts = urlsplit(url)
        port = parts.port
    except ValueError:
        raise PaginationOriginError.for_url("") from None
    if (
        parts.scheme not in {"http", "https"}
        or not parts.hostname
        or parts.username is not None
        or parts.password is not None
    ):
        raise PaginationOriginError.for_url("")
    if port is None:
        port = 443 if parts.scheme == "https" else 80
    return parts.scheme, parts.hostname.casefold(), port


class _PageWalk:
    """Pure pagination state machine shared by the sync and async iterators.

    Holds no I/O: :meth:`start` yields the first ``(endpoint, params)`` and
    :meth:`advance` consumes one page's ``(items, data, headers)`` to produce
    the next request — or ``None`` when the collection is exhausted.
    """

    def __init__(
        self,
        endpoint: str,
        *,
        mode: str,
        params: dict[str, Any] | None,
        cursor_param: str,
        cursor_path: str,
        page_param: str,
        page_size_param: str,
        page_size: int | None,
        start_page: int,
        offset_param: str,
        limit_param: str,
        since_param: str,
        id_field: str,
        next_path: str = "next",
        base_url: str | None = None,
    ) -> None:
        if mode not in PAGINATION_MODES:
            raise ValueError(f"mode must be one of {PAGINATION_MODES}, got {mode!r}")
        self.mode = mode
        self.next_path = next_path
        try:
            self._current_url = urljoin(base_url or "", endpoint)
        except ValueError:
            if mode not in {"next_url", "link"}:
                raise
            raise PaginationOriginError.for_url("") from None
        if mode in {"next_url", "link"} and not urlsplit(self._current_url).scheme:
            raise ValueError(f"{mode} mode needs an absolute endpoint or base_url")
        self._first_origin = (
            _safe_origin(self._current_url)
            if mode in {"next_url", "link"}
            else _origin(self._current_url)
        )
        self._seen_urls = {self._current_url}
        #: Set when a repeated next URL ended a link or next-URL sweep.
        self.loop_detected = False
        self.endpoint = endpoint
        self.base_params = dict(params or {})
        token_param = {"cursor": cursor_param, "since_id": since_param}.get(mode, "")
        self._tokens = _TokenHistory(self.base_params.get(token_param))
        self.cursor_param = cursor_param
        self.cursor_path = cursor_path
        self.page_param = page_param
        self.page_size_param = page_size_param
        self.page_size = page_size
        self.offset_param = offset_param
        self.limit_param = limit_param
        self.since_param = since_param
        self.id_field = id_field
        self._page = start_page
        self._offset = 0
        #: Resume token after iteration (cursor / link / since_id modes).
        self.next_cursor: str | None = None

    def start(self) -> tuple[str, dict[str, Any]]:
        params = dict(self.base_params)
        if self.mode == "page":
            params[self.page_param] = self._page
            if self.page_size is not None:
                params[self.page_size_param] = self.page_size
        elif self.mode == "offset":
            params[self.offset_param] = self._offset
            if self.page_size is not None:
                params[self.limit_param] = self.page_size
        return self.endpoint, params

    def advance(
        self,
        items: list[Any],
        data: Any,
        headers: Mapping[str, str],
    ) -> tuple[str, dict[str, Any]] | None:
        if self.mode == "cursor":
            cursor = _dig(data, self.cursor_path) if self.cursor_path else None
            return _advance_cursor(self, cursor)

        if self.mode == "link":
            return self._advance_link(headers)

        if self.mode == "next_url":
            return self._advance_next_url(data)

        if self.mode == "since_id":
            return _advance_since(self, items)

        return _advance_numbered(self, items)

    def _advance_link(
        self, headers: Mapping[str, str]
    ) -> tuple[str, dict[str, Any]] | None:
        next_url = _link_next_url(headers)
        if not next_url:
            self.next_cursor = None
            return None
        return self._follow_url(next_url)

    def _advance_next_url(self, data: Any) -> tuple[str, dict[str, Any]] | None:
        raw = _dig(data, self.next_path)
        if not raw or not isinstance(raw, str):
            self.next_cursor = None
            return None
        return self._follow_url(raw)

    def _follow_url(self, raw: str) -> tuple[str, dict[str, Any]] | None:
        """Follow one same-origin link or stop if the URL was already read."""
        try:
            absolute = urljoin(self._current_url, raw)
        except ValueError:
            raise PaginationOriginError.for_url("") from None
        if _safe_origin(absolute) != self._first_origin:
            raise PaginationOriginError.for_url(absolute)
        if absolute in self._seen_urls:
            self.loop_detected = True
            self.next_cursor = None
            return None
        self._seen_urls.add(absolute)
        self._current_url = absolute
        self.next_cursor = absolute
        # The next URL already carries the full query string.
        return absolute, {}
