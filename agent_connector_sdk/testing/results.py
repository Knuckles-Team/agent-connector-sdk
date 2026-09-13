"""Conformance result types."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass

from agent_connector_sdk.ports.session import McpSession

__all__ = [
    "ConformanceFailure",
    "ConformanceResult",
    "SessionFactory",
    "assert_conformant",
]

#: Opens a fresh session per call.
SessionFactory = Callable[[], AbstractAsyncContextManager[McpSession]]


class ConformanceFailure(AssertionError):
    """One or more conformance checks failed."""


@dataclass(frozen=True)
class ConformanceResult:
    """The outcome of one check."""

    check: str
    passed: bool
    detail: str = ""


def assert_conformant(results: Sequence[ConformanceResult]) -> None:
    """Raise :class:`ConformanceFailure` listing every failed check."""
    failed = [result for result in results if not result.passed]
    if failed:
        raise ConformanceFailure(
            "; ".join(f"{result.check}: {result.detail}" for result in failed)
        )
