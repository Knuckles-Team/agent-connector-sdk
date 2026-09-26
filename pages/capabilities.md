# Capabilities

Agent Connector SDK provides one governed connector lifecycle from MCP serving
through source synchronization and source-side effects. These capabilities are
part of the current public package.

| Surface | Current capability | Primary guide |
|---|---|---|
| MCP server | FastMCP construction, authentication, exposure checks, health, visibility, rate limiting, change subscriptions, and tool registration | [Connector servers](connector-servers.md) |
| Connector content | Typed publication and capture of tools, skills, prompts, resources, ontologies, SHACL shapes, and manifests | [Content over MCP](content-over-mcp.md) |
| Source synchronization | Certified discovery, bounded extraction, explicit lifecycle modes, durable status reads, and receipt-verified checkpoint progression | [Connector sync](connector-sync.md) |
| ConnectorPack | Deterministic archives whose exact served content crosses generated Epistemic Graph contracts | [Architecture](architecture.md#connectorpack-lifecycle) |
| Repository ingestion | Authenticated immutable snapshots, stable manifests, bounded object transfer, tombstones, and typed per-file outcomes | [Repository ingestion](repository-ingestion.md) |
| Write-back | Side-effect-free preview, authorization verification, optimistic source versions, idempotent apply, and uncertain-effect reconciliation | [Architecture](architecture.md#writeback-lifecycle) |
| Extension system | Typed source, artifact, transport, sink, registry, authorization, and write-back ports with exact distribution certification | [Extension interfaces](extension-ports.md) |
| Connector operations | Supervised scheduling, retry and progress state, dependency-aware health, credential references, and governed HTTP/TLS | [Connector sync](connector-sync.md#health) |

## Contract boundary

The SDK depends on `epistemic-graph>=2.27.0`. SourceIngest, ConnectorPack,
IndexRepository, and WriteBack graph models come from Epistemic Graph's
generated surface. Graph OS supplies the verified client, identity, and live
authority required for graph-bound runtime composition.

The SDK owns connector transport and lifecycle behavior. Connector packages own
vendor semantics, while Epistemic Graph remains the durable graph, mapping,
checkpoint, content-identity, provenance, and receipt authority.

## Verification

Connector distributions can use the [conformance kit](conformance-kit.md), and
running MCP packages can be checked with
[`connector-certify`](connector-certify.md). Repository gates verify public API
wiring, live schema fingerprints, generated contract freshness, type safety,
tests, packaging, and this documentation surface.
