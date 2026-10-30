"""Independent, host-authorized paper searches under shared provider quotas."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from typing import Any, Literal

import anyio

from scion_sdk.adapters.paper_merge import merge_paper_records
from scion_sdk.adapters.paper_models import (
    PaperQuery,
    PaperRecord,
    PaperSearchResult,
    ProviderReport,
)
from scion_sdk.adapters.paper_provider import (
    PaperProvider,
    ProviderPaper,
)
from scion_sdk.adapters.paper_quota import (
    PaperQuotaPolicy,
    QuotaUnavailable,
    SharedPaperQuota,
)
from scion_sdk.adapters.paper_search_attempt import _attempts, _failed

__all__ = ["PaperSearchService", "ProviderBinding"]


@dataclass(frozen=True)
class ProviderBinding:
    """A host-selected provider and its admitted shared quota policy."""

    provider: PaperProvider
    quota: PaperQuotaPolicy
    retries: int = 2

    def __post_init__(self) -> None:
        if type(self.retries) is not int or not 0 <= self.retries <= 10:
            raise ValueError("invalid provider retry budget")
        if getattr(self.provider, "quota_policy", self.quota) != self.quota:
            raise ValueError("provider request pacing disagrees with quota")


class PaperSearchService:
    """Compose explicitly selected providers after host authorization.

    The host must bind the context to an authenticated caller. A successful
    result does not certify a connector or authorize graph ingestion.
    """

    def __init__(
        self,
        providers: Mapping[str, ProviderBinding],
        *,
        quota: SharedPaperQuota,
        authorize: Callable[[PaperQuery, Any], Awaitable[bool]],
    ) -> None:
        self._providers = dict(providers)
        self._quota = quota
        self._authorize = authorize
        if any(
            name != binding.quota.provider_id
            for name, binding in self._providers.items()
        ):
            raise ValueError("provider and quota identity differ")

    async def search(self, query: PaperQuery, context: Any) -> PaperSearchResult:
        """Return ordered provider outcomes without suppressing healthy results."""
        query = PaperQuery.model_validate(query.model_dump())
        deadline = anyio.current_time() + query.deadline_seconds
        try:
            with anyio.fail_after(query.deadline_seconds):
                admitted = await self._authorize(query, context)
        except TimeoutError:
            return _unavailable(query, "deadline_exceeded")
        except Exception:
            return _unavailable(query, "unauthorized")
        if admitted is not True:
            return _unavailable(query, "unauthorized")
        tasks = [
            asyncio.create_task(self._one(query, provider, deadline))
            for provider in query.provider_ids
        ]
        try:
            results = await _collect(query, tasks, deadline)
        except BaseException:
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            raise
        return _compose(query, results)

    async def _one(
        self, query: PaperQuery, name: str, deadline: float
    ) -> tuple[ProviderReport, tuple[ProviderPaper, ...]]:
        binding = self._providers.get(name)
        if binding is None:
            return ProviderReport(
                provider_id=name, outcome="refused", reason="unknown_provider"
            ), ()
        try:
            async with self._quota.request_slot(binding.quota) as slot:
                return await _attempts(
                    query, name, binding, slot=slot, deadline=deadline
                )
        except QuotaUnavailable as error:
            if error.reason == "busy":
                return ProviderReport(
                    provider_id=name, outcome="rate_limited", reason="rate_limited"
                ), ()
            return ProviderReport(
                provider_id=name, outcome="refused", reason="provider_failed"
            ), ()


async def _collect(query: PaperQuery, tasks: list[Any], deadline: float) -> list[Any]:
    done, pending = await asyncio.wait(
        tasks, timeout=max(0.0, deadline - anyio.current_time())
    )
    for task in pending:
        task.cancel()
    await asyncio.gather(*pending, return_exceptions=True)
    return [
        _completed(name, task) if task in done else _deadline(name)
        for name, task in zip(query.provider_ids, tasks, strict=True)
    ]


def _unavailable(query: PaperQuery, reason: Any) -> PaperSearchResult:
    reports = tuple(
        ProviderReport(provider_id=name, outcome="refused", reason=reason)
        for name in query.provider_ids
    )
    return PaperSearchResult(reports=reports, completeness="failed")


def _compose(
    query: PaperQuery, results: list[tuple[ProviderReport, tuple[ProviderPaper, ...]]]
) -> PaperSearchResult:
    records: tuple[ProviderPaper, ...] = ()
    merged: tuple[PaperRecord, ...] = ()
    reports = []
    for report, rows in results:
        report, records, merged = _merge_page(
            query, report, rows, records=records, merged=merged
        )
        reports.append(report)
    count = sum(report.outcome == "ok" for report in reports)
    completeness: Literal["failed", "complete", "partial"] = (
        "failed" if count == 0 else "complete" if count == len(reports) else "partial"
    )
    return PaperSearchResult(
        records=merged, reports=tuple(reports), completeness=completeness
    )


def _merge_page(
    query: PaperQuery,
    report: ProviderReport,
    rows: tuple[ProviderPaper, ...],
    *,
    records: tuple[ProviderPaper, ...],
    merged: tuple[PaperRecord, ...],
) -> tuple[ProviderReport, tuple[ProviderPaper, ...], tuple[PaperRecord, ...]]:
    if report.outcome != "ok":
        return report, records, merged
    try:
        candidate = merge_paper_records(query, (*records, *rows))
    except ValueError:
        return (
            ProviderReport(
                provider_id=report.provider_id,
                outcome="failed",
                reason="provider_failed",
            ),
            records,
            merged,
        )
    return report, (*records, *rows), candidate


def _completed(
    name: str, task: asyncio.Task[tuple[ProviderReport, tuple[ProviderPaper, ...]]]
) -> tuple[ProviderReport, tuple[ProviderPaper, ...]]:
    if task.cancelled():
        return _failed(name, "provider_failed")
    try:
        return task.result()
    except Exception:
        return _failed(name, "provider_failed")


def _deadline(name: str) -> tuple[ProviderReport, tuple[ProviderPaper, ...]]:
    return ProviderReport(
        provider_id=name, outcome="failed", reason="deadline_exceeded"
    ), ()
