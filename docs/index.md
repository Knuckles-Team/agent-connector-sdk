<section class="site-hero" aria-labelledby="connector-sdk-title">
  <div class="site-hero__eyebrow">Connector runtime</div>
  <h1 class="site-hero__title" id="connector-sdk-title">Build one connector. Run it everywhere.</h1>
  <p class="site-hero__summary">
    A secure MCP runtime, source synchronization contract, and governed
    write-back boundary for the agent ecosystem.
  </p>
  <div class="site-hero__actions">
    <a class="md-button md-button--primary" href="tutorial/">Build your first connector</a>
    <a class="md-button" href="architecture/">Explore the architecture</a>
  </div>
</section>

<div class="site-card-grid" role="list" aria-label="SDK capabilities">
  <article class="site-card" role="listitem">
    <h2 class="site-card__title">Serve</h2>
    <p class="site-card__body">Create FastMCP servers with authentication, safe exposure, visibility, health, rate limits, and a consistent tool surface.</p>
  </article>
  <article class="site-card" role="listitem">
    <h2 class="site-card__title">Synchronize</h2>
    <p class="site-card__body">Discover certified source contracts, extract bounded pages, and advance EG-authoritative checkpoints from durable receipts.</p>
  </article>
  <article class="site-card" role="listitem">
    <h2 class="site-card__title">Publish</h2>
    <p class="site-card__body">Expose skills, prompts, ontologies, SHACL shapes, and manifests as deterministic ConnectorPack content.</p>
  </article>
  <article class="site-card" role="listitem">
    <h2 class="site-card__title">Write back</h2>
    <p class="site-card__body">Preview exact diffs, verify policy and source versions, apply idempotently, and reconcile uncertain effects.</p>
  </article>
  <article class="site-card" role="listitem">
    <h2 class="site-card__title">Ingest repositories</h2>
    <p class="site-card__body">Page authenticated immutable snapshots into deterministic manifests and bounded IndexRepository requests with typed per-file outcomes and tombstones.</p>
  </article>
</div>

## One graph contract

The SDK depends directly on `epistemic-graph>=2.27`. Generated SourceIngest,
ConnectorPack, and WriteBack models and clients are the sole graph boundary.
Connector packages keep vendor logic local; durable identity, mapping,
checkpoints, provenance, and receipts stay authoritative in epistemic-graph.

![Agent ecosystem runtime architecture](assets/runtime-architecture.svg)

<div class="site-ownership">
  <div class="site-ownership__grid">
    <div class="site-ownership__item">
      <div class="site-ownership__label">Connectors own</div>
      <div class="site-ownership__value">Vendor requests, source revisions, paging tokens, and external effects.</div>
    </div>
    <div class="site-ownership__item">
      <div class="site-ownership__label">The SDK owns</div>
      <div class="site-ownership__value">MCP lifecycle, capture, transport, certification, scheduling, and governed source execution.</div>
    </div>
    <div class="site-ownership__item">
      <div class="site-ownership__label">epistemic-graph owns</div>
      <div class="site-ownership__value">Graph schemas, source state, content identity, reasoning, provenance, and durable receipts.</div>
    </div>
    <div class="site-ownership__item">
      <div class="site-ownership__label">GraphOS owns</div>
      <div class="site-ownership__value">Verified runtime identity, authority injection, composition, and protocol exposure.</div>
    </div>
  </div>
</div>

## From API to durable evidence

<ol class="site-flow">
  <li class="site-flow__step">
    <div class="site-flow__title">Describe</div>
    <div class="site-flow__body">A connector publishes its tools, content, source presets, and safety declarations over MCP.</div>
  </li>
  <li class="site-flow__step">
    <div class="site-flow__title">Certify</div>
    <div class="site-flow__body">The SDK verifies package identity, live schemas, pagination, and extension behavior.</div>
  </li>
  <li class="site-flow__step">
    <div class="site-flow__title">Transport</div>
    <div class="site-flow__body">Bounded pages and exact content archives cross generated epistemic-graph contracts.</div>
  </li>
  <li class="site-flow__step">
    <div class="site-flow__title">Acknowledge</div>
    <div class="site-flow__body">epistemic-graph commits state and returns the receipt that authorizes the next step.</div>
  </li>
</ol>

## Choose a path

- **New connector:** follow [Build your first connector](tutorial.md).
- **Runtime owner:** read [Architecture](architecture.md) and
  [Connector sync](connector-sync.md).
- **Repository operator:** use [Repository ingestion](repository-ingestion.md)
  for immutable snapshot paging and durable indexing receipts.
- **Extension author:** implement [Extension ports](extension-ports.md) and run
  the [Conformance kit](conformance-kit.md).
- **Security reviewer:** start with [Connector servers](connector-servers.md),
  [HTTP clients](http-clients.md), and [Credentials](credentials.md).
