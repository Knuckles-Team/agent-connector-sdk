# Knowledge ingest

A connector pushes what it observed into Epistemic Graph with
`agent_connector_sdk.ingest`. It describes records as a typed `ChangeSet`; the SDK
turns the change set into one generated `SourceIngest` request against the
stream's durable checkpoint and returns the generated receipt. Epistemic Graph
resolves every record and relationship against the connector's published
Connector Manifest, admits raw content, projects nodes and edges, and commits
the checkpoint in one transaction.

## A tool that ingests what it returns

```python
from agent_connector_sdk.ingest import (
    ChangeSet, Document, Entity, IngestBinding, IngestError, Relationship,
    ingest_changes,
)

BINDING = IngestBinding(connector="demo-mcp", stream="search")

def ingest_results(query_id: str, query: str, results: list[dict]) -> int:
    changes = ChangeSet(
        entities=(Entity(query_id, "SearchQuery", {"queryText": query}),),
        documents=tuple(
            Document(f"demo:result:{r['url']}", r["content"], title=r["title"],
                     source_uri=r["url"])
            for r in results
        ),
        relationships=tuple(
            Relationship(f"demo:result:{r['url']}", query_id, "resultOf")
            for r in results
        ),
    )
    return ingest_changes(BINDING, changes).affected_count
```

`aingest_changes` is the async form. Both raise `IngestError` when the change set
is malformed or Epistemic Graph refuses it, `IngestConflictError` when the
checkpoint kept moving, and `IngestUnavailableError` when the process has no
ingest channel.

## Change sets

| Type | Becomes |
|---|---|
| `Entity(id, node_type, properties)` | a record mapped by `schema_mappings/<node_type>` |
| `Document(id, text, title=, source_uri=)` | a `Document` record with the text and its SHA-256 `content_hash`; Epistemic Graph chunks, embeds and enriches it |
| `MediaAsset(data, mime_type, id=, name=)` | bytes stored in Blob CAS first, then a `MediaAsset` record carrying `blob_digest`, `mime_type` and `size_bytes`; the id defaults to `blob:<digest>` |
| `Relationship(source, target, relationship)` | an edge referencing `resources/<source type>/relations/<relationship>` |
| `Withdrawal(id, reason)` | an explicit delta tombstone |

A relationship's source type comes from an `EntityRef(id, node_type)` or from an
entity, document or asset in the same change set; the SDK never guesses it.
`ChangeSet.mode` is `delta` by default. `reconcile` needs the complete
`live_ids`, and Epistemic Graph derives the tombstones. `IngestBinding` names the
manifest `connector`, the `stream`, and the `document_type` and `media_type`
resources (default `Document` and `MediaAsset`).

Every `node_type`, relationship, `Document` and `MediaAsset` a connector emits
must be declared in its Connector Manifest, with an ontology class, and the
manifest must be published for the tenant. Anything else is refused with the
engine's reason.

## Connecting a process

The service a process uses is the one installed with `install_ingest(...)`, else
one connected on first use from these settings, else none:

| Setting | Meaning |
|---|---|
| `EPISTEMIC_GRAPH_ENDPOINT` | `tls://host:port`, loopback `tcp://host:port`, or `unix:///path`; unset means no ingest |
| `EPISTEMIC_GRAPH_AUTH_SECRET_REF` | a secret reference to the engine authentication secret |
| `EPISTEMIC_GRAPH_TENANT` / `EPISTEMIC_GRAPH_GRAPH` | where records land |
| `EPISTEMIC_GRAPH_PRINCIPAL` | the service principal (default `service:connector`) |
| `EPISTEMIC_GRAPH_POLICY_VERSION` | the policy claim (default `policy:current`) |

TLS material comes from the `epistemic-graph` TLS profile. The session asks only
for `source:ingest` and `blob:write`. The client runs on one background event
loop; synchronous tool handlers block on it and async handlers await it.

Submissions for one stream are serialized in the process. When another replica
advances the checkpoint first, the submission re-reads it and rebuilds, up to
three attempts.

## Polled document sources

The push API above uses an SDK sequence checkpoint. A provider that owns a
resumable cursor uses `DocumentPollAdapter` and `sync_document_source` from
`agent_connector_sdk.runner.document_source` instead. The provider callback
receives EG's last accepted `SourceCheckpoint` and returns one
`DocumentProviderPage` with its actual JSON cursor in `position`. The runner
commits each page before invoking the callback again. A checkpoint conflict
stops the run so the provider can resume from EG status on a new run.

The adapter requires a `ConnectorManifest` with an exact `schema_mappings` key
whose ontology class is `Document` and `external_access` in
`permissions.acl_fields`. Its `fields` must preserve `text`, `title`,
`doc_type`, `metadata`, and `external_access` under those same names; EG drops
source fields omitted by a mapping. The mapping must also be published through
`ConnectorPack` in the target tenant; the EG `SourceIngest` commit verifies
that authority. Each document carries an explicit ACL payload or receives a
quarantine marking; served EG read policy must enforce those properties. The
`provider_contract_sha256` is a real pin for the provider adapter contract;
the runner rejects an absent pin and never invents a mapping or cursor.

Pass `EpistemicGraphIngestTransport` constructed from the caller's existing
verified EG client as the sink. The callback can adapt a connector's `poll()`
page by serializing its checkpoint into `DocumentProviderPage.position`; do
not drain all pages into one synthetic checkpoint. The SDK does not import a
provider package or open a second client for this path.
