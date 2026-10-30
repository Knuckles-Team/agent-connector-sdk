"""Public surface of the write-back sinks: every exported name resolves from its module."""

from __future__ import annotations

import importlib


def test_writeback_sinks_exports() -> None:
    module = importlib.import_module("scion_sdk.writeback_sinks")
    exported = (module.WritebackInvocation,)
    assert len(exported) == 1
    assert all(item is not None for item in exported)


def test_writeback_sinks__env_exports() -> None:
    module = importlib.import_module("scion_sdk.writeback_sinks._env")
    exported = (
        module.runtime_dir,
        module.run_sync_isolated,
        module.stamp_bitemporal,
    )
    assert len(exported) == 3
    assert all(item is not None for item in exported)


def test_writeback_sinks_core_exports() -> None:
    module = importlib.import_module("scion_sdk.writeback_sinks.core")
    exported = (
        module.resolve_writeback_client,
        module.WritebackClientMixin,
        module.resolve_external_id,
    )
    assert len(exported) == 3
    assert all(item is not None for item in exported)


def test_writeback_sinks_governed_exports() -> None:
    module = importlib.import_module("scion_sdk.writeback_sinks.governed")
    exported = (
        module.GovernedOutcome,
        module.SinkWriteBackTransport,
        module.ledger_root,
    )
    assert len(exported) == 3
    assert all(item is not None for item in exported)


def test_writeback_sinks_sinks_capability_exports() -> None:
    module = importlib.import_module("scion_sdk.writeback_sinks.sinks.capability")
    exported = (
        module.make_writeback_fn,
        module.resolve_writeback_fn,
    )
    assert len(exported) == 2
    assert all(item is not None for item in exported)


def test_writeback_sinks_sinks_leanix_exports() -> None:
    module = importlib.import_module("scion_sdk.writeback_sinks.sinks.leanix")
    exported = (module.build_relation_field_resolver,)
    assert len(exported) == 1
    assert all(item is not None for item in exported)
