# Architecture

The Agent Connector SDK is the connector transport and lifecycle layer between
MCP clients, vendor systems, GraphOS, and epistemic-graph. It keeps vendor I/O
replaceable while one generated graph contract owns durable identity and state.

![Agent ecosystem runtime architecture](assets/runtime-architecture.svg)

## Responsibility boundary

<div class="site-ownership">
  <div class="site-ownership__grid">
    <div class="site-ownership__item">
      <div class="site-ownership__label">Connector</div>
      <div class="site-ownership__value">Vendor API models, requests, paging tokens, source versions, and external effects.</div>
    </div>
    <div class="site-ownership__item">
      <div class="site-ownership__label">Agent Connector SDK</div>
      <div class="site-ownership__value">MCP serving, source capture, bounded transport, certification, scheduling, and governed effect execution.</div>
    </div>
    <div class="site-ownership__item">
      <div class="site-ownership__label">epistemic-graph</div>
      <div class="site-ownership__value">Generated contracts, graph schemas, source checkpoints, content identity, provenance, reasoning, and durable receipts.</div>
    </div>
    <div class="site-ownership__item">
      <div class="site-ownership__label">GraphOS</div>
      <div class="site-ownership__value">Verified runtime identity, authority injection, service composition, and external protocol exposure.</div>
    </div>
  </div>
</div>

The SDK depends directly on `epistemic-graph>=2.27`. Generated SourceIngest,
ConnectorPack, and WriteBack models and clients are the sole graph boundary. The
SDK does not copy graph request DTOs, receipt types, or digest algorithms.

## Shared runtime

<ol class="site-flow">
  <li class="site-flow__step">
    <div class="site-flow__title">Serve</div>
    <div class="site-flow__body">An AI or MCP client talks MCP to the connector server, which talks governed HTTP to the vendor API.</div>
  </li>
  <li class="site-flow__step">
    <div class="site-flow__title">Authorize</div>
    <div class="site-flow__body">Graph OS hands the SDK runtime a verified identity and authority; the runtime discovers and extracts through the connector server.</div>
  </li>
  <li class="site-flow__step">
    <div class="site-flow__title">Write back</div>
    <div class="site-flow__body">The runtime's generated EG client receives an authorized change set from epistemic-graph, then previews, applies, and reconciles against the vendor API.</div>
  </li>
</ol>

The same SDK policies guard connector serving and background source work.
Transport changes do not create another content catalog, checkpoint store, or
authorization model.

## Source lifecycle

<ol class="site-flow">
  <li class="site-flow__step">
    <div class="site-flow__title">Discover</div>
    <div class="site-flow__body">The SDK verifies the live MCP tool contract against the connector manifest and certified fingerprints.</div>
  </li>
  <li class="site-flow__step">
    <div class="site-flow__title">Extract</div>
    <div class="site-flow__body">A source adapter returns one bounded page with raw records, provenance, lifecycle mode, and the provider checkpoint.</div>
  </li>
  <li class="site-flow__step">
    <div class="site-flow__title">Commit</div>
    <div class="site-flow__body">The SDK submits EG's generated SourceIngestionRequest with a stable idempotency key and the expected durable checkpoint.</div>
  </li>
  <li class="site-flow__step">
    <div class="site-flow__title">Acknowledge</div>
    <div class="site-flow__body">epistemic-graph maps, validates, deduplicates, persists provenance and outbox state, compare-and-swaps the checkpoint, and returns the sole receipt.</div>
  </li>
</ol>

`full`, `delta`, and `reconcile` modes are explicit. Authoritative empty-source
operations require a non-empty approval descriptor and verified capability.
Provider content hashes are echoed when supplied and are never invented. The
next page starts only from the checkpoint bound by the matching receipt.

## ConnectorPack lifecycle

Connector content is listed through its own MCP server and captured once into
the generated ConnectorPack archive. Ontology and SHACL bodies remain the exact
served UTF-8/LF `text/turtle` bytes. The SDK does not parse or reserialize
identity-bearing Turtle.

The generated archive builder owns section hashes, URI ordering, and the
`mcp-server://<connector>` entry. epistemic-graph binds the archive to the
current catalog snapshot and computes the canonical pack digest. A matching
head is an acknowledged no-op. A concurrent head change causes one fresh status
read and a deterministic retry; every other typed rejection fails the cycle.

Pack annotations carry declared capability, modality, cost, latency, contract
version, and served MCP safety hints. Conflicting declarations fail closed.

## WriteBack lifecycle

<div class="admonition architecture" markdown>
<p class="admonition-title">Write-back sequence</p>

epistemic-graph hands Graph OS an authorized `SourceChangeSet`; Graph OS
passes the Connector SDK a generated contract and verified identity. The SDK
reads the vendor source's current version, dry-runs the exact field diff,
then applies with an idempotency key. When the effect is confirmed, the
source returns an applied observation directly; when the outcome is
uncertain, the SDK reconciles using the key and source version, resolving to
applied, no-effect, or still-uncertain. The SDK reports attempt and
reconciliation observations back to epistemic-graph, which returns durable
receipts to Graph OS.

</div>

epistemic-graph creates the change set, binds authorization and policy, and
persists attempt and reconciliation receipts. The SDK validates those generated
models, performs source-side preview and mutation through the connector port,
and blocks a retry while an effect remains uncertain.

## Failure and evidence

- Unknown authentication, unsafe exposure, schema drift, ambiguous mappings,
  stale checkpoints, receipt mismatches, and uncertified extensions fail closed.
- Credential values remain in memory and never enter manifests, source records,
  logs, health responses, or receipts.
- Every accepted source page is attributable to connector identity, stream,
  mapping, provider checkpoint, raw provenance, and an EG graph version.
- Health reflects the scheduler and its injected dependencies; it does not infer
  success from process existence alone.

See [Extension ports](extension-ports.md) for protocol details and
[Connector sync](connector-sync.md) for runtime configuration.

## Connector subsystem architecture

Deep-dive pages for individual connector families and the ingestion machinery
they share, relocated here from agent-utilities per RF-ADR-009 (SDK owns
connectors, transport, repository hydration, and write-back):

- [Connectors & ingestion](architecture/connectors-and-ingestion.md) — the
  unified ingestion architecture: one entrypoint, one provenance contract, one
  delta model, ~40+ connectors.
- [Bidirectional ETL hub](architecture/etl-hub.md) — Stardog SPARQL data
  backend, `graph_etl`, and ETL lineage.
- [Chunked async drain](architecture/chunked-async-drain.md) — capacity-guarded
  background waves for a large single-source full re-ingest.
- [Content-aware ingestion](architecture/content-aware-ingestion.md) —
  ArchiveBox/crawl4ai/scholarx pluggable fetch and research acquisition.
- [Camunda + ARIS integration](architecture/camunda-aris-integration.md)
- [CISO Assistant integration](architecture/ciso-assistant-integration.md)
- [Privacy-safe external ingestion](architecture/privacy-safe-ingestion.md) —
  governed GraphQL/property-graph external-source lifecycle.
- [Universal external graph connectors](architecture/universal-graph-connectors.md)
