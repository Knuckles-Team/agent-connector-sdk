"""Reject malformed pagination item collections without exposing response data."""

from __future__ import annotations

from typing import Any

from agent_connector_sdk.http.errors import HttpProblemError
from agent_connector_sdk.http.problems import ProblemDetails


class PaginationPageError(HttpProblemError):
    """A page did not contain the declared list of records."""


def _require_items(value: Any) -> list[Any]:
    if not isinstance(value, list):
        raise PaginationPageError(
            ProblemDetails.sdk(
                "invalid-pagination-page",
                "Pagination page has no record list",
                detail="The response does not match the declared page shape",
            )
        )
    return value
