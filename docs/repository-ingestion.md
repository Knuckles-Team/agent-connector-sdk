# Repository ingestion

Repository ingestion has one ownership path. A connector-owned provider client
authenticates to its Git forge and implements `RepositorySnapshotProvider`. The
SDK validates that the provider, authentication evidence, and requested
immutable revision agree; pages source blobs and tombstones; and submits bounded
source batches through the public epistemic-graph client. Epistemic-graph alone
parses files, resolves cross-file symbols, and owns every semantic or durable
graph effect.

<div class="admonition architecture" markdown>
<p class="admonition-title">Ingestion flow</p>

An authenticated provider client fetches immutable revision pages, which the
SDK batches into a bounded source batch and hands to EG's
`IndexRepository`. EG returns typed per-file outcomes and is the semantic
authority for the ingested content.

</div>

Call `index_repository_snapshot(provider, client, revision, limits=...)`. The
revision uses the provider/project identity plus immutable revision and tree
identifiers. Each file carries a normalized repository-relative POSIX path, its
content, and a verified SHA-256 blob digest. Rename and deletion evidence travels
as `RepositoryTombstone`; it is preserved in the receipt and is never disguised
as parser input.

The receipt carries a canonical `RepositorySnapshotManifest`, sorted by logical
path. Its SHA-256 `fingerprint` binds the immutable revision, tree, file content
digests and byte lengths, plus rename/delete tombstones. Batch receipts retain
paths and the native EG result, not source bodies, so completed batches release
their blob memory.

The SDK combines provider pages until an engine batch reaches a file-count or
byte bound, then calls `client.graph.index_repository(files)` exactly once for
that batch. It does not serialize the engine wire protocol itself, inspect or
rewrite native nodes and edges, or issue graph mutations. The native result is
retained unchanged in `RepositoryBatchReceipt`.

Every result must contain one ordered `file_outcomes` item per submitted file.
The SDK checks the path, source-content digest, parser-capability digest, closed
`success | unsupported | error` status, and diagnostics container. Missing,
reordered, or malformed outcomes fail closed; an empty parse result can never be
reported as success by inference.

Provider cursors are ephemeral to this fetch. Repeated cursors, revision drift,
duplicate paths across pages, oversized files, or mismatched authentication stop
the run before another engine call. Durable repository admission, watermarks,
acknowledgements, reconciliation, parsing, cross-file linking, RDF/OWL/SHACL, and
projection receipts remain epistemic-graph responsibilities.

## The ref-walk phase

Before any content is fetched, a provider that also implements
`RepositoryRefWalkProvider` (`agent_connector_sdk.repository.provider`) can be
walked with `walk_refs(provider, page_size=...)`: it lists every ref, then
walks each distinct immutable tree exactly once — refs pinned to the same tree
share one walk — and returns each ref's complete, sorted `(path, Git blob id)`
listing without blob content.

The walk visits each distinct tree only once per run and reads tree objects in
batches rather than issuing one call per object: when the provider also exposes
`prime_trees(tree_ids)`, every distinct tree id across all refs (including
nested, content-addressed subtrees shared between branches) is requested
through it up front. `LocalGitRepositoryProvider`
(`agent_connector_sdk.repository.local_git`) is the reference implementation;
its `prime_trees` reads every distinct tree through one `git cat-file --batch`
process instead of one Git invocation per tree.
