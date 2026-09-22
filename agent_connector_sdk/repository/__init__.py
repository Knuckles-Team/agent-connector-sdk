"""Branch-aware, blob-deduplicated repository transport into epistemic-graph."""

from agent_connector_sdk.repository.errors import RepositoryTransportError
from agent_connector_sdk.repository.indexing import RepositoryBatchReceipt
from agent_connector_sdk.repository.local_git import LocalGitRepositoryProvider
from agent_connector_sdk.repository.manifest import (
    RepositoryIndexManifest,
    RepositoryManifestFile,
    RepositoryRefManifest,
    RepositorySnapshotManifest,
)
from agent_connector_sdk.repository.models import (
    RepositoryAuthentication,
    RepositoryBatchLimits,
    RepositoryFile,
    RepositoryRevision,
    RepositoryTombstone,
)
from agent_connector_sdk.repository.provider import RepositorySnapshotProvider
from agent_connector_sdk.repository.refs import (
    RepositoryRef,
    RepositoryTreeEntry,
    RepositoryTreePage,
)
from agent_connector_sdk.repository.transport import (
    RepositoryIndexReceipt,
    index_repository,
)

__all__ = [
    "LocalGitRepositoryProvider",
    "RepositoryAuthentication",
    "RepositoryBatchLimits",
    "RepositoryBatchReceipt",
    "RepositoryFile",
    "RepositoryIndexManifest",
    "RepositoryIndexReceipt",
    "RepositoryManifestFile",
    "RepositoryRef",
    "RepositoryRefManifest",
    "RepositoryRevision",
    "RepositorySnapshotManifest",
    "RepositorySnapshotProvider",
    "RepositoryTombstone",
    "RepositoryTransportError",
    "RepositoryTreeEntry",
    "RepositoryTreePage",
    "index_repository",
]
