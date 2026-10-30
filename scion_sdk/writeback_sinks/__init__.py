"""Vendor write-back sinks run through the governed write-back contract.

Each sink under :mod:`scion_sdk.writeback_sinks.sinks` registers a
target system's write-back adapter. :func:`run_writeback` is the single
fail-closed, dry-run-first entry point; every live call is executed through
the governed change-set, audit-reservation and ledger path in
:mod:`scion_sdk.writeback_sinks.governed`. SCION-SOURCE-INGEST-R600
owns this package.
"""

from __future__ import annotations

from importlib import import_module

from scion_sdk.writeback_sinks.core import (
    PROVENANCE_TAG,
    WritebackContext,
    WritebackInvocation,
    WritebackResult,
    WritebackSink,
    get_sink,
    list_sinks,
    register_sink,
    run_writeback,
)

_SINK_MODULES = (
    "ansible",
    "archimate",
    "capability",
    "ciso_assistant",
    "egeria",
    "emerald",
    "erpnext",
    "home_assistant",
    "identity",
    "issue_tracker",
    "leanix",
    "legal",
    "mealie",
    "nextcloud",
    "ops",
    "process",
    "salesforce",
    "servicenow",
    "twenty",
    "wger",
)

for _name in _SINK_MODULES:
    import_module(f"scion_sdk.writeback_sinks.sinks.{_name}")

__all__ = [
    "PROVENANCE_TAG",
    "WritebackContext",
    "WritebackInvocation",
    "WritebackResult",
    "WritebackSink",
    "get_sink",
    "list_sinks",
    "register_sink",
    "run_writeback",
]
