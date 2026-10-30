"""Retry and page handling for paper provider searches."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import anyio

from scion_sdk.adapters.paper_models import (
    PaperContinuation,
    PaperQuery,
    ProviderReport,
)
from scion_sdk.adapters.paper_provider import (
    ProviderFailure,
    ProviderPage,
    ProviderPaper,
)
from scion_sdk.adapters.paper_quota import QuotaSlot

if TYPE_CHECKING:
    from scion_sdk.adapters.paper_search import ProviderBinding


async def _attempts(
    query: PaperQuery,
    name: str,
    binding: ProviderBinding,
    *,
    slot: QuotaSlot,
    deadline: float,
) -> tuple[ProviderReport, tuple[ProviderPaper, ...]]:
    continuation = query.continuation.get(name)
    cursor = continuation.cursor if continuation is not None else None
    for attempt in range(binding.retries + 1):
        try:
            page = await binding.provider.search(query, cursor)
            return _page(query, name, page)
        except ProviderFailure as error:
            failure = error
        except Exception:
            failure = ProviderFailure("provider_failed")
        result = await _retry_result(
            failure,
            name,
            binding,
            slot=slot,
            deadline=deadline,
            last=attempt == binding.retries,
        )
        if result is not None:
            return result
    raise AssertionError("unreachable")


async def _retry_result(
    error: ProviderFailure,
    name: str,
    binding: ProviderBinding,
    *,
    slot: QuotaSlot,
    deadline: float,
    last: bool,
) -> tuple[ProviderReport, tuple[ProviderPaper, ...]] | None:
    if error.reason == "rate_limited":
        stop = await _rate_limit(
            error,
            slot,
            deadline=deadline,
            spacing=binding.quota.minimum_spacing_ns / 1_000_000_000,
        )
        if stop is not None or last:
            return ProviderReport(
                provider_id=name,
                outcome="rate_limited",
                reason="rate_limited",
                retry_after_seconds=error.retry_after_seconds,
            ), ()
        return None
    if error.reason in {"unauthorized", "egress_denied", "deadline_exceeded"}:
        return _failed(name, error.reason)
    if last:
        return _failed(name, "provider_failed")
    await anyio.sleep(binding.quota.minimum_spacing_ns / 1_000_000_000)
    return None


async def _rate_limit(
    error: ProviderFailure, slot: QuotaSlot, *, deadline: float, spacing: float
) -> bool | None:
    slot.retain()
    if error.retry_after_seconds is None:
        return True
    delay = max(error.retry_after_seconds, spacing)
    if delay >= deadline - anyio.current_time():
        return True
    await anyio.sleep(delay)
    slot.release_after_delay()
    return None


def _failed(name: str, reason: Any) -> tuple[ProviderReport, tuple[ProviderPaper, ...]]:
    return ProviderReport(provider_id=name, outcome="failed", reason=reason), ()


def _page(
    query: PaperQuery, name: str, page: ProviderPage
) -> tuple[ProviderReport, tuple[ProviderPaper, ...]]:
    if not isinstance(page, ProviderPage) or len(page.records) > query.page_bound:
        raise ProviderFailure("provider_failed")
    prior = query.continuation.get(name)
    if page.cursor is not None and prior is not None and page.cursor == prior.cursor:
        raise ProviderFailure("provider_failed")
    if any(record.reference.provider_id != name for record in page.records):
        raise ProviderFailure("provider_failed")
    continuation = (
        None
        if page.cursor is None
        else PaperContinuation(
            provider_id=name,
            query_sha256=query.query_digest(),
            provider_ids=query.provider_ids,
            schema_revision=query.schema_revision,
            cursor=page.cursor,
        )
    )
    return ProviderReport(
        provider_id=name, outcome="ok", continuation=continuation
    ), page.records
