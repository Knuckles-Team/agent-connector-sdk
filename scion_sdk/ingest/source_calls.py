"""Bounded tool-call helpers used by the declared source runner."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from scion_sdk.ingest.sources import IngestSourceSpec
from scion_sdk.runner.backoff import Backoff


class _SourceCalls:
    """Page arguments, budget exhaustion and retried source calls."""

    def _exhausted(self: Any, run: Any) -> bool:
        budget = self._budget
        return bool(
            run.pages >= budget.max_pages
            or run.seen >= budget.max_records
            or self._clock() - run.started >= budget.max_seconds
        )

    @staticmethod
    def _arguments(
        spec: IngestSourceSpec, page: int, scope: Mapping[str, Any] | None = None
    ) -> dict[str, Any]:
        arguments: dict[str, Any] = {**spec.arguments, **(scope or {})}
        if spec.pagination == "page" and spec.page_param:
            arguments[spec.page_param] = page
            if spec.page_size_param:
                arguments[spec.page_size_param] = spec.page_size
        return arguments

    async def _call(self: Any, tool: str, arguments: Mapping[str, Any]) -> Any:
        budget = self._budget
        backoff = Backoff(budget.backoff_initial_seconds, budget.backoff_max_seconds)
        failure: Exception | None = None
        for attempt in range(budget.attempts):
            try:
                return await self._session.call_tool(tool, arguments)
            except Exception as exc:
                failure = exc
            if attempt + 1 < budget.attempts:
                await self._sleep(backoff.next_delay())
        raise self._source_error(
            "tool_failed", f"{tool} failed ({type(failure).__name__})"
        ) from failure
