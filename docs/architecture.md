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

```mermaid
flowchart LR
    Client[AI or MCP client] -->|MCP| Server[Connector server]
    Server -->|governed HTTP| Vendor[Vendor API]
    GraphOS -->|verified identity and authority| Runner[SDK runtime]
    Runner -->|discover and extract| Server
    Runner -->|generated EG client| EG[epistemic-graph]
    EG -->|authorized change set| Runner
    Runner -->|preview, apply, reconcile| Vendor
```

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

```mermaid
sequenceDiagram
    participant EG as epistemic-graph
    participant OS as GraphOS
    participant SDK as Connector SDK
    participant Source as Vendor source

    EG->>OS: authorized SourceChangeSet
    OS->>SDK: generated contract + verified identity
    SDK->>Source: read current source version
    SDK->>Source: dry-run exact field diff
    SDK->>Source: apply with idempotency key
    alt effect confirmed
        Source-->>SDK: applied source observation
    else outcome uncertain
        SDK->>Source: reconcile key + source version
        Source-->>SDK: applied / no effect / uncertain
    end
    SDK-->>EG: attempt and reconciliation observations
    EG-->>OS: durable receipts
```

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
