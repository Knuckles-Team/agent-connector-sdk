"""The ``DescribesCapabilities`` port: the descriptor half of a source adapter."""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from agent_connector_sdk.contracts import CapabilityDescriptor

__all__ = ["DescribesCapabilities"]


@runtime_checkable
class DescribesCapabilities(Protocol):
    """The subset of ``SourceAdapter`` needed to check its capability descriptor.

    Conformance checks that only inspect ``describe()``/``kind`` (e.g.
    ``check_capability_descriptor``) should depend on this, not the full
    ``SourceAdapter``, so a conformance-only test double never needs to also
    implement ``discover``/``extract``/``reconcile``.
    """

    kind: str

    def describe(self) -> CapabilityDescriptor:
        """Declare the adapter's capabilities; must not perform I/O."""
        ...
