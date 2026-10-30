"""Public surface of the source client, mount and wallet-proof gate."""

from __future__ import annotations

import pytest

import agent_connector_sdk.source
import agent_connector_sdk.source.client
import agent_connector_sdk.source.mount
import agent_connector_sdk.writeback
import agent_connector_sdk.writeback.wallet_proof


@pytest.mark.parametrize(
    "exported",
    [
        agent_connector_sdk.source.BlameLine,
        agent_connector_sdk.source.BlamePage,
        agent_connector_sdk.source.BlameRequest,
        agent_connector_sdk.source.BlobPage,
        agent_connector_sdk.source.CacheEvent,
        agent_connector_sdk.source.DiffEntry,
        agent_connector_sdk.source.DiffPage,
        agent_connector_sdk.source.DiffRequest,
        agent_connector_sdk.source.HistoryEntry,
        agent_connector_sdk.source.HistoryPage,
        agent_connector_sdk.source.HistoryRequest,
        agent_connector_sdk.source.LandRequest,
        agent_connector_sdk.source.MountEntry,
        agent_connector_sdk.source.PathOutcome,
        agent_connector_sdk.source.Receipt,
        agent_connector_sdk.source.RevertRequest,
        agent_connector_sdk.source.SourceRefusal,
        agent_connector_sdk.source.SourceTransport,
        agent_connector_sdk.source.TreeEntry,
        agent_connector_sdk.source.TreePage,
        agent_connector_sdk.source.client.BlameLine,
        agent_connector_sdk.source.client.BlamePage,
        agent_connector_sdk.source.client.BlameRequest,
        agent_connector_sdk.source.client.BlobPage,
        agent_connector_sdk.source.client.CacheEvent,
        agent_connector_sdk.source.client.DiffEntry,
        agent_connector_sdk.source.client.DiffPage,
        agent_connector_sdk.source.client.DiffRequest,
        agent_connector_sdk.source.client.HistoryEntry,
        agent_connector_sdk.source.client.HistoryPage,
        agent_connector_sdk.source.client.HistoryRequest,
        agent_connector_sdk.source.client.LandRequest,
        agent_connector_sdk.source.client.PathOutcome,
        agent_connector_sdk.source.client.Receipt,
        agent_connector_sdk.source.client.RevertRequest,
        agent_connector_sdk.source.client.SourceRefusal,
        agent_connector_sdk.source.client.SourceTransport,
        agent_connector_sdk.source.client.TreeEntry,
        agent_connector_sdk.source.client.TreePage,
        agent_connector_sdk.source.mount.MountEntry,
        agent_connector_sdk.writeback.WalletProofGate,
        agent_connector_sdk.writeback.wallet_proof.WalletProofGate,
    ],
)
def test_public_names_are_exported(exported: object) -> None:
    assert exported is not None
