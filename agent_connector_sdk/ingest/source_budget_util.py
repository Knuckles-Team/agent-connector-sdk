"""Validated numeric limits and pending source-page helpers."""

from __future__ import annotations

from typing import Any

from agent_connector_sdk.ingest.model import Entity
from agent_connector_sdk.runner.backoff import Backoff, _finite_number


def _validate_budget(budget: Any) -> None:
    limits = (
        budget.max_pages,
        budget.max_records,
        budget.batch_size,
        budget.attempts,
        budget.max_fan_out,
    )
    if any(type(value) is not int or value < 1 for value in limits):
        raise ValueError("sync count limits must be positive integers")
    if not _finite_number(budget.max_seconds) or budget.max_seconds <= 0:
        raise ValueError("sync time budget must be a positive finite number")
    Backoff(budget.backoff_initial_seconds, budget.backoff_max_seconds)


def _binding_tool(run: Any, tool: str | None) -> str:
    return str(tool or run.pending_tool or run.spec.tools[0])


def _pending_records(run: Any) -> dict[str, Entity]:
    records = {entity.id: entity for entity, _ in run.pending}
    for target, _ in run.pending_edges:
        if target is not None:
            records.setdefault(target.id, target)
    return records
