"""Vendor enrichment extractors (SCION-SOURCE-INGEST-R006).

Each module under this package ports one vendor-specific enrichment extractor
from ``agent_utilities.knowledge_graph.enrichment.extractors`` onto this SDK's
typed :class:`~scion_sdk.vendor_extractors.contract.VendorExtractor`
contract: a plain ``extract(config) -> ChangeSet`` function producing
:class:`scion_sdk.ingest.Entity`/:class:`~scion_sdk.ingest.Relationship`
records instead of agent-utilities' ``ExtractionBatch`` of
``GraphNode``/``EnrichmentEdge``. A module registers itself at import time via
:func:`~scion_sdk.vendor_extractors.contract.register_vendor_extractor`,
so porting one vendor touches no shared hub file.

``specs/SCION-SOURCE-INGEST/requirements.md`` tracks one child requirement
(``SCION-SOURCE-INGEST-R006.<n>``) per vendor module; ``uptime_kuma`` is the
first ported (``R006.1``), alongside this contract.
"""

from __future__ import annotations

from scion_sdk.vendor_extractors.contract import (
    VendorExtractFn,
    VendorExtractor,
    discover_vendor_extractors,
    get_vendor_extractor,
    list_vendor_extractors,
    register_vendor_extractor,
)

__all__ = [
    "VendorExtractFn",
    "VendorExtractor",
    "discover_vendor_extractors",
    "get_vendor_extractor",
    "list_vendor_extractors",
    "register_vendor_extractor",
]
