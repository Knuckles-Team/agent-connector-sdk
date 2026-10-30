"""Errors raised by the knowledge-ingest facade."""

from __future__ import annotations

__all__ = [
    "ContractNotAcceptedError",
    "IngestConflictError",
    "IngestError",
    "IngestUnavailableError",
    "UndeclaredNestedValueError",
]


class IngestError(RuntimeError):
    """A change set was not committed; the message is safe to surface."""


class IngestUnavailableError(IngestError):
    """No epistemic-graph ingest channel is configured or reachable here."""


class IngestConflictError(IngestError):
    """The stream checkpoint moved concurrently and the retry budget ran out."""


class ContractNotAcceptedError(IngestError):
    """The engine has not accepted this connector's local ingest contract."""

    code = "contract_not_accepted"


class UndeclaredNestedValueError(IngestError):
    """A nested dictionary value has no declared mapping in the contract."""

    code = "undeclared_nested_value"
