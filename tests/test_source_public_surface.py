"""Public surface of the source client, mount and wallet-proof gate."""

from __future__ import annotations

import pytest

import scion_sdk.source
import scion_sdk.source.client
import scion_sdk.source.mount
import scion_sdk.writeback
import scion_sdk.writeback.wallet_proof


@pytest.mark.parametrize(
    "exported",
    [
        scion_sdk.source.BlameLine,
        scion_sdk.source.BlamePage,
        scion_sdk.source.BlameRequest,
        scion_sdk.source.BlobPage,
        scion_sdk.source.CacheEvent,
        scion_sdk.source.DiffEntry,
        scion_sdk.source.DiffPage,
        scion_sdk.source.DiffRequest,
        scion_sdk.source.HistoryEntry,
        scion_sdk.source.HistoryPage,
        scion_sdk.source.HistoryRequest,
        scion_sdk.source.LandRequest,
        scion_sdk.source.MountEntry,
        scion_sdk.source.PathOutcome,
        scion_sdk.source.Receipt,
        scion_sdk.source.RevertRequest,
        scion_sdk.source.SourceRefusal,
        scion_sdk.source.SourceTransport,
        scion_sdk.source.TreeEntry,
        scion_sdk.source.TreePage,
        scion_sdk.source.client.BlameLine,
        scion_sdk.source.client.BlamePage,
        scion_sdk.source.client.BlameRequest,
        scion_sdk.source.client.BlobPage,
        scion_sdk.source.client.CacheEvent,
        scion_sdk.source.client.DiffEntry,
        scion_sdk.source.client.DiffPage,
        scion_sdk.source.client.DiffRequest,
        scion_sdk.source.client.HistoryEntry,
        scion_sdk.source.client.HistoryPage,
        scion_sdk.source.client.HistoryRequest,
        scion_sdk.source.client.LandRequest,
        scion_sdk.source.client.PathOutcome,
        scion_sdk.source.client.Receipt,
        scion_sdk.source.client.RevertRequest,
        scion_sdk.source.client.SourceRefusal,
        scion_sdk.source.client.SourceTransport,
        scion_sdk.source.client.TreeEntry,
        scion_sdk.source.client.TreePage,
        scion_sdk.source.mount.MountEntry,
        scion_sdk.writeback.WalletProofGate,
        scion_sdk.writeback.wallet_proof.WalletProofGate,
    ],
)
def test_public_names_are_exported(exported: object) -> None:
    assert exported is not None
