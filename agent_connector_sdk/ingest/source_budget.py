"""Bounded operations used by the declared source runner."""

from __future__ import annotations

import re
from collections.abc import Callable, Mapping
from typing import Any, Literal

import anyio

from agent_connector_sdk.ingest.model import Entity
from agent_connector_sdk.ingest.source_budget_util import (
    _binding_tool as _binding_tool,
)
from agent_connector_sdk.ingest.source_budget_util import (
    _pending_records as _pending_records,
)
from agent_connector_sdk.ingest.source_budget_util import (
    _validate_budget as _validate_budget,
)

_ENGINE_CODE = re.compile(r"\b[A-Z][A-Z0-9]*(?:_[A-Z0-9]+)+\b")


class _SourceBudgetMixin:
    """Source-call deadline and bounded page operations."""

    async def _handle_sync_error(
        self: Any, run: Any, exc: Any
    ) -> tuple[Literal["completed", "partial", "failed"], str, str | None]:
        if exc.reason == "checkpoint_conflict":
            raise exc
        if exc.reason in {"deadline_exceeded", "record_budget_exceeded"}:
            try:
                await self._flush(run)
            except self._source_error as failure:
                return await self._handle_sync_error(run, failure)
            return "partial", exc.reason, None
        found = _ENGINE_CODE.search(str(exc))
        return (
            "failed",
            exc.reason,
            found.group(0) if exc.reason == "ingest_refused" and found else None,
        )

    async def _source_page(
        self: Any,
        run: Any,
        tool: str,
        arguments: Mapping[str, Any],
        *,
        decode: Callable[[Any, Any], list[Mapping[str, Any]]],
    ) -> list[Mapping[str, Any]]:
        result = await self._budgeted_call(run, tool, arguments)
        records = decode(result, run.spec)
        run.pages += 1
        if len(records) > self._budget.max_records - run.seen:
            raise self._source_error(
                "record_budget_exceeded", "page exceeds remaining record budget"
            )
        return records

    async def _take_page(
        self: Any, run: Any, records: list[Mapping[str, Any]], tool: str
    ) -> None:
        for record in records:
            await self._take(run, record, tool)

    def _append_parent_records(
        self: Any, values: list[Any], records: list[Mapping[str, Any]], field: str
    ) -> None:
        for record in records:
            value = record.get(field)
            if value is not None and value not in values:
                values.append(value)
                if len(values) > self._budget.max_fan_out:
                    raise self._source_error(
                        "fan_out_exceeded", "parent source exceeded the fan-out budget"
                    )

    async def _budgeted_call(
        self: Any, run: Any, tool: str, arguments: Mapping[str, Any]
    ) -> Any:
        remaining = self._budget.max_seconds - (self._clock() - run.started)
        if remaining <= 0:
            raise self._source_error("deadline_exceeded", "source time budget ended")
        try:
            with anyio.fail_after(remaining):
                return await self._call(tool, arguments)
        except TimeoutError:
            raise self._source_error(
                "deadline_exceeded", "source time budget ended"
            ) from None

    async def _sweep_tool(
        self: Any,
        run: Any,
        tool: str,
        scope: Mapping[str, Any],
        *,
        decode: Callable[[Any, Any], list[Mapping[str, Any]]],
    ) -> bool:
        spec = run.spec
        page = spec.start_page
        while True:
            if self._exhausted(run):
                await self._flush(run)
                return False
            records = await self._source_page(
                run, tool, self._arguments(spec, page, scope), decode=decode
            )
            await self._take_page(run, records, tool)
            if spec.pagination != "page" or len(records) < spec.page_size:
                break
            page += 1
        await self._flush(run, tool=tool)
        return True

    async def _parent_pages(
        self: Any,
        run: Any,
        parent: Any,
        tool: str,
        *,
        scope: Mapping[str, Any],
        field: str,
        values: list[Any],
        decode: Callable[[Any, Any], list[Mapping[str, Any]]],
    ) -> None:
        page = parent.start_page
        while True:
            if self._exhausted(run):
                raise self._source_error(
                    "parent_budget_exhausted",
                    f"budget ended while reading parent {parent.source_id!r}",
                )
            result = await self._budgeted_call(
                run, tool, self._arguments(parent, page, scope)
            )
            records = decode(result, parent)
            run.pages += 1
            self._append_parent_records(values, records, field)
            if parent.pagination != "page" or len(records) < parent.page_size:
                return
            page += 1

    async def _submit_pending(
        self: Any, run: Any, binding: Any, records: dict[str, Entity]
    ) -> Any:
        from agent_connector_sdk.ingest.errors import IngestError
        from agent_connector_sdk.ingest.model import ChangeSet

        changes = ChangeSet(
            entities=tuple(records.values()),
            relationships=tuple(edge for _, edge in run.pending_edges),
            cursor=run.cursor,
        )
        try:
            return await self._ingest.submit(binding, changes)
        except self._source_error:
            raise
        except IngestError as exc:
            run.pending.clear()
            run.pending_edges.clear()
            run.pending_tool = None
            raise self._source_error("ingest_refused", str(exc)) from exc
