"""Authenticated repository snapshot transport into epistemic-graph."""

from agent_connector_sdk.repository.errors import RepositoryTransportError
from agent_connector_sdk.repository.indexing import RepositoryBatchReceipt
from agent_connector_sdk.repository.manifest import (
    RepositoryManifestFile,
    RepositorySnapshotManifest,
)
from agent_connector_sdk.repository.models import (
    RepositoryAuthentication,
    RepositoryBatchLimits,
    RepositoryFile,
    RepositoryPage,
    RepositoryRevision,
    RepositoryTombstone,
)
from agent_connector_sdk.repository.provider import RepositorySnapshotProvider
from agent_connector_sdk.repository.transport import (
    RepositoryIndexReceipt,
    index_repository_snapshot,
)

__all__ = [
    "RepositoryAuthentication",
    "RepositoryBatchLimits",
    "RepositoryBatchReceipt",
    "RepositoryFile",
    "RepositoryIndexReceipt",
    "RepositoryManifestFile",
    "RepositoryPage",
    "RepositoryRevision",
    "RepositorySnapshotManifest",
    "RepositorySnapshotProvider",
    "RepositoryTombstone",
    "RepositoryTransportError",
    "index_repository_snapshot",
]
