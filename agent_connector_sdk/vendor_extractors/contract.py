"""The typed vendor-extractor contract and its self-registering registry.

A vendor extractor is one function, ``extract(config) -> ChangeSet``. ``config``
carries whatever the vendor's client/session needs (a vendor API client, a
settings object); the extractor returns a :class:`~agent_connector_sdk.ingest.ChangeSet`
of :class:`~agent_connector_sdk.ingest.Entity`/:class:`~agent_connector_sdk.ingest.Relationship`
records — the SDK's native ingest model, not a bespoke per-vendor shape. The
caller submits the returned change set through
:func:`agent_connector_sdk.ingest.ingest_changes` with the vendor's
:class:`~agent_connector_sdk.ingest.IngestBinding`; this contract performs no
I/O and holds no credentials itself.

Registering a vendor extractor::

    from agent_connector_sdk.ingest import ChangeSet, Entity
    from agent_connector_sdk.vendor_extractors import register_vendor_extractor

    def extract(config) -> ChangeSet:
        ...

    register_vendor_extractor("uptime_kuma", extract, description="Uptime Kuma monitors")
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from agent_connector_sdk.ingest import ChangeSet

__all__ = [
    "VendorExtractFn",
    "VendorExtractor",
    "discover_vendor_extractors",
    "get_vendor_extractor",
    "list_vendor_extractors",
    "register_vendor_extractor",
]

logger = logging.getLogger(__name__)

# config -> ChangeSet
VendorExtractFn = Callable[[Any], ChangeSet]


@dataclass(frozen=True)
class VendorExtractor:
    category: str
    extract: VendorExtractFn
    description: str = ""


_REGISTRY: dict[str, VendorExtractor] = {}


def register_vendor_extractor(
    category: str, extract: VendorExtractFn, description: str = ""
) -> None:
    """Register a vendor extractor under a unique category key (idempotent)."""
    if category in _REGISTRY and _REGISTRY[category].extract is not extract:
        logger.debug("Overriding vendor extractor for category %s", category)
    _REGISTRY[category] = VendorExtractor(category, extract, description)


def get_vendor_extractor(category: str) -> VendorExtractor | None:
    return _REGISTRY.get(category)


def list_vendor_extractors() -> list[VendorExtractor]:
    return sorted(_REGISTRY.values(), key=lambda v: v.category)


def discover_vendor_extractors() -> int:
    """Import every module under ``vendor_extractors/`` so they self-register.

    Called once; a newly ported vendor module is picked up with no shared-file
    edits. Returns the number of modules imported.
    """
    import importlib
    import pkgutil

    from agent_connector_sdk import vendor_extractors as _pkg

    count = 0
    for mod in pkgutil.iter_modules(_pkg.__path__):
        if mod.name == "contract":
            continue
        try:
            importlib.import_module(f"{_pkg.__name__}.{mod.name}")
            count += 1
        except Exception as exc:  # pragma: no cover - optional vendor deps
            logger.debug(
                "Configured vendor extractor not loaded (%s)", type(exc).__name__
            )
    return count
