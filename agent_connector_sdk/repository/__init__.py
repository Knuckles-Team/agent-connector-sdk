"""Authenticated repository snapshot transport into epistemic-graph."""

from agent_connector_sdk.repository.errors import RepositoryTransportError
from agent_connector_sdk.repository.indexing import RepositoryBatchReceipt
from agent_connector_sdk.repository.local_git import LocalGitRepositoryProvider
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
from agent_connector_sdk.repository.provider import (
    RepositoryRefWalkProvider,
    RepositorySnapshotProvider,
)
from agent_connector_sdk.repository.refs import (
    RepositoryRef,
    RepositoryTreeEntry,
    RepositoryTreePage,
)
from agent_connector_sdk.repository.transport import (
    RepositoryIndexReceipt,
    index_repository_snapshot,
)
from agent_connector_sdk.repository.walk import RefTree, walk_refs

__all__ = [
    "LocalGitRepositoryProvider",
    "RefTree",
    "RepositoryAuthentication",
    "RepositoryBatchLimits",
    "RepositoryBatchReceipt",
    "RepositoryFile",
    "RepositoryIndexReceipt",
    "RepositoryManifestFile",
    "RepositoryPage",
    "RepositoryRef",
    "RepositoryRefWalkProvider",
    "RepositoryRevision",
    "RepositorySnapshotManifest",
    "RepositorySnapshotProvider",
    "RepositoryTombstone",
    "RepositoryTransportError",
    "RepositoryTreeEntry",
    "RepositoryTreePage",
    "index_repository_snapshot",
    "walk_refs",
]
