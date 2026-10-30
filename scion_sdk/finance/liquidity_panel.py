"""Read sourced FRED graph records and call the graph-owned liquidity panel."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from scion_sdk.finance.liquidity_records import _milliseconds, _observation
from scion_sdk.ports.errors import SourceContractError

__all__ = ["read_liquidity_panel"]

_QUERY = (
    "MATCH (n) WHERE n.source_stream = 'macro_series_fed_balance_sheet' "
    "OR n.source_stream = 'macro_series_treasury_general_account' "
    "OR n.source_stream = 'macro_series_reverse_repo_overnight' "
    "RETURN n LIMIT 10001"
)


def _policy(as_of: datetime, max_age: timedelta) -> tuple[int, int]:
    try:
        as_of_ms = _milliseconds(as_of)
    except (ValueError, TypeError, OverflowError, AttributeError):
        raise SourceContractError("invalid liquidity panel request") from None
    if not isinstance(max_age, timedelta):
        raise SourceContractError("invalid liquidity panel request")
    max_age_ms = (
        max_age.days * 86400 + max_age.seconds
    ) * 1000 + max_age.microseconds // 1000
    if not 0 < max_age_ms <= (1 << 63) - 1:
        raise SourceContractError("invalid liquidity panel request")
    return as_of_ms, max_age_ms


def _parse_rows(rows: list[Any]) -> list[dict[str, Any]]:
    nodes = [row["n"] for row in rows]
    if any(not isinstance(node, dict) for node in nodes):
        raise ValueError("invalid graph result")
    return [item for node in nodes if (item := _observation(node)) is not None]


def _observations(rows: Any) -> list[dict[str, Any]]:
    if not isinstance(rows, list) or len(rows) >= 10001:
        raise SourceContractError("liquidity source query exceeds its record budget")
    try:
        return _parse_rows(rows)
    except (ValueError, TypeError, OverflowError, KeyError, AttributeError):
        raise SourceContractError("invalid liquidity source record") from None


async def read_liquidity_panel(
    client: Any, *, as_of: datetime, max_age: timedelta
) -> Any:
    """Read FRED graph nodes and ask EG for the versioned panel.

    ``observed_at`` records capture, not historical release time. Inputs with no
    trustworthy capture time or an unsupported decimal precision refuse.
    """
    as_of_ms, max_age_ms = _policy(as_of, max_age)
    observations = _observations(await client.query.cypher_read(_QUERY))
    return await client.finance.market(
        "liquidity_panel",
        request={
            "version": 1,
            "as_of_ms": as_of_ms,
            "max_age_ms": max_age_ms,
            "observations": observations,
        },
    )
