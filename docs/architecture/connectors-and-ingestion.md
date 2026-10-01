# KG Connectors, Ingestors & Enrichers — the unified ingestion architecture

> **One entrypoint, one provenance contract, one delta model.** Every external
> system the Knowledge Graph knows about — enterprise apps, code, documents,
> research — flows in through the *same* mechanism and is enriched by the *same*
> OWL/RDF reasoning. This is the map of all of them. (CONCEPT:AU-KG.ingest.enterprise-source-extractor)

This page is the canonical inventory and architecture for how the KG is
**hydrated**. The connector list at the bottom is **auto-generated** from the live
registries (`scripts/generate_connector_map.py`) so it never drifts.

---

## 1. The one mental model

<div class="admonition architecture" markdown>
<p class="admonition-title">One ingestion core, ~40+ connectors</p>

External systems — enterprise apps (LeanIX/ServiceNow/ERPNext/Jira/…),
process (Camunda/ARIS/Egeria/ArchiMate), and documents/web
(ArchiveBox/crawl4ai/scholarx/search) — all feed `source_sync()`/
`sweep_all_sources()`, the one ingestion entrypoint. Code (GitLab/GitHub
repos) instead feeds epistemic-graph's tree-sitter parse + resolve
(`IndexRepository`, `ast_hash` = content hash) first, which then also
feeds `source_sync()`. From there: `stamp_source()` (provenance) →
content-hash delta (skip unchanged) → `write_entities()` (the one writer)
→ the engine's store (LPG + Neo4j/FalkorDB/Stardog/pg-age/fanout). The
store feeds `OWLBridge` reasoning (transitive `:calls`/`:dependsOn`,
crosswalks) back into itself, and the writer also feeds extractors
(code/test, facts, process) into the store. The store's writeback sinks
feed back out to the external systems.

</div>

Three things are deliberately **uniform** across every connector:

1. **One entrypoint** — `sync_source(engine, source, mode)` (and its fleet-wide
   sibling `sweep_all_sources`). No connector hydrates ad hoc.
2. **One provenance contract** — `stamp_source()` stamps `source_system` +
   `domain` on every row, so named-graph routing, federation, and mirroring treat
   all connectors identically.
3. **One delta model** — see §5.
4. **One writer** — `core/materialization.write_entities()` is the single
   materialization implementation. The two historical write paths
   (`ingest_external_batch`, dict entities; and `write_batch`, typed
   `ExtractionBatch` for the materialize/extractor fleet) are now thin **input
   adapters** over it with zero duplicated logic, so provenance, the content-hash
   delta, and typed-label batching are implemented once. Since `execute` /
   `execute_batch` are `@abstractmethod` on `GraphBackend` (every backend provides
   them), the writer has just two branches: **UNWIND MERGE** (all backends) and a
   **per-row MERGE** variant for Ladybug (Kuzu has no UNWIND). Ladybug receives
   those one-row operations through `execute_batch`, whose backend implementation
   translates them into native Ladybug calls; the native engine authority remains
   on its separate `ChangeEnvelope` path. The schema helpers (`normalize_label` /
   `schema_valid_keys` / `set_clause`) also live here once — the engine's
   `_normalize_label` / `_get_set_clause` delegate to them.

---

## 2. The standardized surface (3 MCP tools → clear roles)

The Python core was always unified (`sync_source` is "the single entrypoint").
The MCP surface is now standardized to match:

| MCP tool | Role | Delegates to |
|---|---|---|
| **`source_sync`** | **Canonical** connector→KG ingestion. `source=<name>` or `source="all"` (fleet sweep); `mode=delta\|full\|reconcile`. | `sync_source` / `sweep_all_sources` |
| `graph_hydrate` | Back-compat **alias** (full mode). Kept so existing callers don't break. | `sync_source(mode="full")` |
| `graph_ingest` | Different concern: **content** ingestion — paths, URLs, documents, codebases, corpus/job control. Its `sync`/`materialize_source` actions delegate to the same core. | `sync_source` / `run_materialize_source` |

REST twins live under `/api/dashboard/` (`hydrate/{source}`, `hydrate`,
`hydration-status`, `daemon/start`).

**Rule of thumb:** sync a *system* → `source_sync`; ingest a *file/URL/repo path*
→ `graph_ingest`.

---

## 3. The three ingestion paths (how a connector gets in)

A connector participates in one or more of these, dispatched by `sync_source`:

<div class="admonition architecture" markdown>
<p class="admonition-title">`sync_source` dispatch ladder</p>

`sync_source(engine, source, mode)` checks, in order: is the source in
`_DELTA_HANDLERS`? If so, run the delta handler (watermark poll +
reconcile — leanix/gitlab/archivebox). Else, is it in
`MATERIALIZE_SOURCES`? If so, `run_materialize_source` (vendor client →
extractor → `write_batch` — camunda/egeria/okta/…). Otherwise,
`HydrationManager.hydrate_source` (generic full hydrate via
`CAPABILITY_REGISTRY`). All three paths converge on `stamp_source` →
content-hash delta → write.

</div>

1. **Delta handlers** (`_DELTA_HANDLERS`) — native incremental sync with a
   per-source watermark (`SourceSyncState` node) + reconcile (tombstone upstream
   deletions). The most efficient path.
2. **Materialize extractors** (`MATERIALIZE_SOURCES`) — an in-process vendor
   client + extractor maps the system to BFO/PROV-O entities, persisted via
   `write_batch`, followed by one OWL reasoning cycle.
3. **Capability hydrate** (`CAPABILITY_REGISTRY`) — the generic full-hydrate
   fallback for any registered source that hasn't grown a delta handler yet.

Plus a fourth, document-oriented path: **`MCP_TOOL_PRESETS`** declarative
connectors that pull records/files/search results as Documents through the
generic `McpToolSourceConnector` (used by `graph_ingest`/`build_skill_graph`).

---

## 4. Activation-bound admission (NE-113)

Connector preparation and connector activation are separate gates. A
successful Arrow clean/validation result can be replayed, but it cannot select
its own graph or governance policy. The activation control plane approves an
exact tuple of connector version, tenant, target graph, mapping reference and
digest, SHACL reference and digest, and ICV reference and digest. The tuple is
fingerprinted as one `ActivationBinding` and is rotated or rolled back through
versioned pure state transitions.

<div class="admonition architecture" markdown>
<p class="admonition-title">Activation-bound admission sequence</p>

A connector sends a `ChangeEnvelope` + `connector_preparation` evidence to
the AU adapter, which asks the activation control plane for the exact
binding + active generation and gets back an approved binding claim. The
adapter verifies tenant, graph, refs, and digests itself, then calls
epistemic-graph's existing `ingest_envelope`, which runs SHACL/ICV +
`ApplyChangeEnvelope` and returns success, skipped, reject, or fail. The
adapter returns a bounded report ref and stable code to the connector.

</div>

`ActivationAdmissionAdapter` fails closed for missing, rotating or stale
activation; connector/version, tenant or graph substitution; missing or
different mapping/SHACL/ICV artifacts; and an unverified write session. A
rejected preflight never calls the native writer. A native rejection is
returned as `engine_rejected` without copying its raw reason. Thus
`ApplyChangeEnvelope` remains the single durable path and the engine remains
the authoritative SHACL/ICV gate. The adapter does not persist activation
state, invent preparation evidence, or create a parallel commit path.

## 5. Delta for *every* connector (the optimization)

"Delta-focused ingestion for all connectors" is two layers — and the second is
what makes it universal:

**(a) Fetch-layer watermark** (per-source, opportunistic). Where the source API
supports "changed since", the delta handler stores the max `updatedAt`/
`last_activity_at`/`created_at` on a `SourceSyncState` node and fetches only the
delta next run. Today: LeanIX, GitLab, ArchiveBox.

**(b) Write-layer content-hash delta** (generic, all connectors). At the single
write fan-in (`ingest_external_batch`), every entity gets a stable `content_hash`
over its semantic properties. Before writing, stored hashes are read in **one
batched round-trip** and unchanged entities are dropped — **no MERGE, no
re-reasoning** — *even when the source was fetched in full*. This is what makes a
full re-mirror cheap and turns every connector incremental regardless of whether
its API supports watermarks. Disable with `KG_WRITE_DELTA=0`.

<div class="admonition architecture" markdown>
<p class="admonition-title">Write-layer content-hash delta</p>

Each incoming entity gets a `content_hash` (id + volatile timestamps
excluded), and stored hashes for all of them are read in one batch
(`MATCH … WHERE n.id IN $ids`). A changed or new hash triggers `MERGE` +
re-reason; an unchanged hash is skipped (`skipped_unchanged++`).

</div>

**Leveraging Rust epistemic-graph.** For code, the content hash is *free*: the
tree-sitter parser emits a content-stable `ast_hash` on every symbol, so "which
symbols changed" is answered by comparing `ast_hash`, not by node existence.

> **Corrected 2026-09-04.** This paragraph previously said the parser *uses*
> `ast_hash` as the `symbol:<hash>` node id, and that node existence
> (`HasNodesBatch`) therefore answers the delta question. Both halves are now
> false and the technique would be wrong if applied: since `3831475a` the node id
> is OCCURRENCE identity -- `sha256(file_path, symbol_type, qualified_symbol,
> per-file ordinal)` -- so it is stable across content edits, and a node
> continues to exist unchanged when a symbol's body changes. Delta detection must
> read the `ast_hash` PROPERTY. The id was changed because content-addressing made
> byte-identical declarations share one id (max multiplicity 46), which made
> 954,652 EG edge rows ambiguous. `IndexRepository` resolves an entire
repo's `:calls`/`:dependsOn` in one parallel (`rayon`) pass off-reactor. The
generic write-layer delta extends that same content-hash idea to every non-code
connector.

### Legacy embedding reconciliation

New connector envelopes persist an embedding property and register the same
vector in the engine ANN index. Legacy nodes are reconciled in bounded pages by
`GraphMaintainer.backfill_entity_embeddings` and the operator-facing
`scripts/backfill_embeddings.py`:

<div class="admonition architecture" markdown>
<p class="admonition-title">Legacy embedding backfill</p>

IDs where embedding is null and not text-deferred (bounded and ordered) get
one batched property hydration, then a check for extractable text: no text
sets a separate no-text CAS state (never a placeholder vector); text
triggers one batched embedding request (validating all vectors first),
then one cross-modal transaction (exact-text CAS + ANN add) that commits
the durable property and ANN vector together — a staging or commit failure
instead rolls back to a later bounded backfill retry. A successful commit
sets CAS served-read readiness true (a post-commit crash before readiness
instead falls to periodic/operator hydration repair) and fans out the
winning full node to configured mirrors.

</div>

The vector transaction changes only the embedding and its maintenance/readiness
fields, so existing connector properties, ownership, classification, and ACL
state remain intact.
It also fences the exact name/summary/fallback values used to construct the
embedding input: a concurrent content update loses the CAS and is retried from a
fresh property snapshot instead of receiving a stale vector. Every response
vector is non-empty, finite, and dimension-consistent before any vector property
is written.

Durable success is the progress ledger: the next page cannot select a completed
node. A node with no usable text receives a separate maintenance-only `no_text`
state, never a fake embedding, so it does not pin every later page; a normal full
entity upsert replaces that state when source data changes. In fan-out mode, a
winning authority CAS reuses the structured full-node outbox path so mirrors
receive the exact updated node without resetting ACL properties; a losing CAS
emits no mirror entry. The conditional property update and ANN registration
stage and commit in one engine transaction. An ANN staging or commit failure
rolls back before the embedding property is durable, leaving the node eligible
for a later bounded backfill. The periodic/operator hydrator repairs only the
post-commit gap where the property and ANN vector exist but the served-read
readiness CAS did not complete; it does not repair a rolled-back transaction.

---

## 5b. Ambient epistemics (valid-time + provenance, W3.4)

Connector-ingested rows carry epistemic value **by default**, with no
per-connector code change — `KG_AMBIENT_EPISTEMIC` (default ON; per-source
opt-out via `KG_AMBIENT_EPISTEMIC_DISABLED_SOURCES`):

- **Valid-time from the source's own timestamp.** Every envelope already
  carries `event_time`/`valid_time` (populated from the connector's own
  `updated_field`/version-field). `envelope_ingest._stamp_ambient_valid_time`
  maps that onto the written row's bitemporal `valid_from`; a delete/reconcile
  tombstone closes `valid_to` at the supersession instant
  (`_stamp_ambient_valid_until`). **Never fabricated** — a source with no
  usable timestamp writes neither property, so `is_valid_as_of` still treats
  it as "always valid" rather than inventing a start date.
- **One PROV-O Activity + one summary Claim per sync run, never per row.**
  `source_sync._ingest_entities_via_envelope` (the shared tail ~20 connector
  handlers route through) mints one `:Activity` node
  (`etl.lineage.record_connector_sync_activity`,
  `RegistryNodeType.PROVENANCE_ACTIVITY`) per call, links every synced row to
  it via a `derived_from` edge riding the SAME `ApplyChangeEnvelope`
  transaction as that row's own write (no extra round trip), and persists one
  `:Claim` after the batch ("source X reported N records as of T",
  `etl.lineage.record_connector_sync_claim`) through the lightweight direct
  `ClaimNode` + `add_node` path (`orchestration.agent_dispatch_worker`'s
  convention) — not the governed mining-flywheel lifecycle, which is reserved
  for inferred findings needing review.

<div class="admonition architecture" markdown>
<p class="admonition-title">Per-sync provenance and claims</p>

One `source_sync` handler run mints one `:Activity` (`kind=connector_sync`)
and, per record, a `ChangeEnvelope` (`valid_from` ← event_time/valid_time)
carrying a `derived_from` edge to that activity in the same transaction as
the row's own write. After the whole batch, it persists one `:Claim`
("source X reported N records as of T") linked from the activity.

</div>

The write-path X5 closure applies the same idea to **outbound** writes: see
§7's writeback bullet below.

---

## 6. Background ingestion across the board

A single host-role daemon runs `skill_scheduler` every 60s, reading
`deploy/schedules.yml`. The fleet sweep is one declarative entry:

```yaml
- name: all-sources-delta-sweep
  cron: "*/20 * * * *"
  kind: skill
  ref: all          # → sync_source(engine, "all", mode="delta") → sweep_all_sources
  action: delta
  enabled: true
```

`sweep_all_sources(mode="delta")` enumerates the union of delta handlers +
**configured** capability sources + materialize extractors and syncs each,
isolating per-connector failures (unconfigured → *skipped*, not *errored*). With
the write-layer delta, each 20-minute pass is proportional to what changed.
Per-source entries (e.g. a nightly LeanIX `reconcile`, or a tighter cadence for a
hot source) still live alongside it when a source needs its own schedule.

---

## 7. Enrichers (what happens after the write)

Ingestion is only half the story — the KG's differentiator is that everything
lands in **one ontology** and is reasoned over together:

- **OWLBridge reasoning** — transitive `:calls`/`:dependsOn`/`:covers`,
  cross-vendor process crosswalks, `:Feature` clustering; runs as a cycle after
  materialize and on the Loop. (`core/owl_bridge.py`, `ontology_*.ttl`)
- **Extractors** — `code_test` (symbols/tests → `:Code`/`:Test`), the document
  fact extractor (text → atomic fact edges), process lift (Camunda/ARIS → ArchiMate).
- **Writeback sinks** — the outbound half: KG intelligence is pushed *back* into
  the source systems (issues, CMDB CIs, fact-sheet attributes). High-stakes sinks
  are propose-only via the ProposalQueue. (`enrichment/writeback/sinks/`) The
  write path's `as_of` (X5, W3.4) closes the read path's long-standing
  bitemporal `as_of` support: `run_writeback` stamps `as_of` onto every
  returned proposal (audit-trail coverage for every sink with no per-sink
  change), and the ServiceNow/Egeria sinks additionally embed it into the
  LIVE outbound payload (ServiceNow `work_notes` text; Egeria
  `additional_properties`) — so a backfeed records which KG state it derived
  from, not just that a write happened.

See also: [KG as Bidirectional ETL Hub](etl-hub.md),
[Content-Aware Ingestion](content-aware-ingestion.md),
[Code Intelligence](https://knuckles-team.github.io/epistemic-graph/architecture/code-intelligence/),
[Vendor-Neutral Enterprise Ontology](https://knuckles-team.github.io/agent-utilities/architecture/vendor_neutral_enterprise_ontology/),
[Camunda + ARIS ↔ KG](camunda-aris-integration.md).

---

## 8. Fail-closed connector permissions (AU-P0-4)

Three failure modes closed — none change the ~40 connectors that already report
a real ACL (LeanIX, GitLab, ServiceNow, …); this is about what happens when a
connector reports **nothing**:

1. **Unknown/unconfigured ACL must never mean public.** The generic
   `mcp_package`/`mcp_tool` connectors used to default an ingested document's
   `ExternalAccess` to `.public()` when a preset/instance declared no `acl_*`
   fields. `default_external_access()` (`protocols/source_connectors/base.py`)
   now returns `ExternalAccess.quarantined()` instead — `is_public=False` plus
   the `connector-unconfigured-acl` marking, so `permission_sync.sync_access`
   actually restricts the document rather than registering no ACL at all and
   falling through to default-allow. There is no environment opt-in back to
   the old public-by-default behavior anymore — the quarantined default is
   unconditional.
2. **Every external source is compile-before-sync governed.**
   `connector_manifest_gate.precheck_source` rejects a missing, unsigned,
   providerless, schema-drifted, or code-fingerprint-drifted
   `connector_manifest.yml` before any source record is read. Provider-owned
   presets and exact live MCP schema fingerprints are part of the signed
   contract. An installed connector distribution is checked directly; when the
   connector runs as a remote Kubernetes MCP service, GraphOS resolves the same
   data from the complete-manifest signature and `ontology.lock`-pinned bundled
   snapshot. The resolved preset always enables live MCP schema verification
   before pulling records. A broken installed provider never falls back to its
   bundled snapshot, while a genuinely absent remote-only distribution can use
   that signed snapshot without being installed into GraphOS. Boot sweeps likewise
   enqueue an in-process materializer only when its provider module is installed;
   known-but-absent instances are not reported as contract failures. The
   in-package native connector bundle signs the local-module closure for `rss`,
   `web`, `filesystem`, and the other zero-infrastructure sources. Only the
   explicit internal-introspection sources documented by the gate bypass this
   external supply-chain boundary.
3. **A reconcile pass can't mistake a failed fetch for "everything was
   deleted."** `source_sync._reconcile` distinguishes a live-id fetch that
   errored or was skipped (`fetch_ok=False` — always skips, regardless of
   policy) from a genuinely empty authoritative snapshot, which only
   tombstones every previously-known node for that source when it is named in
   `SOURCE_SYNC_ALLOW_EMPTY_TOMBSTONE` (comma-separated, empty by default).
   Wired today for the LeanIX reconcile path; the `jira`/`ard` reconcile call
   sites still call `_reconcile` without `fetch_ok`, so they keep the
   conservative default (`True`) rather than distinguishing the two cases yet.

See [Configuration Reference](https://knuckles-team.github.io/agent-utilities/architecture/configuration/) for the three flags, and
[External Permission Sync](https://knuckles-team.github.io/agent-utilities/pillars/4_ecosystem_peripherals/ECO-4.28-External_Permission_Sync/)
for how the ACL descriptor maps onto the KG-2.46 permissioning model.

### 8a. Typed actions in the manifest (CA-32, DEC-CA-07, CONCEPT:AU-KG.ontology.connector-typed-actions)

`connector_manifest.yml`'s `actions:` block (`ActionSpec`,
`knowledge_graph/ontology/connector_manifest.py`) started as the generic
a2a-capability pair every connector's `AgentCard` advertises
(`epistemic-answer`/`run_graph_flow`) — informational, not gated. DEC-CA-07
extends the SAME field, additively, into a typed declaration for a connector
action that performs a governed mutating write:

```yaml
actions:
  - id: delete_widget          # unchanged: the original identifier field
    name: Delete Widget
    description: Remove a widget.
    label: Delete Widget                  # new, optional
    parameters:                            # new, optional
      - name: widget_id
        type: string
        required: true
    target_resource: Widget                # new, optional; must name a resources[].name
    conflict_policy: manual_review         # new, optional: source_wins | graph_derived | manual_review | reject
    requires_approval: true                # new; defaults true — DEC-CA-07 fail-closed
    approval_class: sensitive              # new, optional; default "unclassified"
    effects: ["mutate:Widget"]             # new, optional
```

Every new field is optional with a default that reproduces the old
three-field shape exactly, so all 72 manifests on disk load byte-compatibly
without regeneration. `ConnectorManifest` cross-validates `target_resource`
against the manifest's own `resources[]` and refuses `requires_approval:
false` on an action whose `id`/`name` looks destructive by name (the same
term vocabulary `mcp.tools.intent_tools._DESTRUCTIVE_TERMS` uses) — an
explicit opt-out still isn't enough for something that looks destructive.

`connector_manifest_gate.undeclared_mutating_tools(pkg)` statically (AST, no
import — connector packages are separate repos/venvs this one doesn't
install) scans `agents/<pkg>`'s own `@mcp.tool(...)` registrations for an
EXPLICIT mutating signal — a `tags={"mutating"}` or a standard MCP
`annotations={"destructiveHint": True}` / `{"readOnlyHint": False}` — that has
no matching `actions[].id`. Because the scan is decorator-only, a package
that registers tools via `mcp.tool(...)(func)` call syntax instead of
`@mcp.tool(...)` is a known false-negative (e.g. `genius-agent`). It is
fail-**open** on absence of either signal (nothing breaks for a package that
hasn't opted in) and fail-**closed** the moment a tool carries one
(`check_manifest_bytes(..., require_declared_actions=True)`, or the CLI's
`--check-actions` flag). It is OFF by default everywhere — `source_sync`'s
runtime gate, the CLI sweep, and `precheck_source` — because 8 of the 72
shipped packages (`audio-transcriber`, `container-manager-mcp`,
`lakekeeper-mcp`, `microsoft-agent`, `opensearch-mcp`, `spark-mcp`,
`systems-manager`, `tunnel-manager`) already tag a tool mutating via
`annotations={"readOnlyHint": False, ...}`/`{"destructiveHint": True}`
without declaring it in `actions:`; closing that real, pre-existing gap
fleet-wide is out of CA-32's scope. CA-40..46 (new/extended MCP packages)
declare `actions:` and pass `--check-actions` from day one instead.

---

## 8b. Governed candidate-claim promotion, supersession & dead-letter drain

The universal-ingestion program's governed validation/promotion and incremental
reconciliation tracks (CONCEPT:AU-KG.ingest.governed-claim-promotion,
CONCEPT:AU-KG.ingest.fact-supersession, CONCEPT:AU-KG.ingest.dead-letter-drain)
— assembled from the pieces above, not a second ingestion stack:

<div class="admonition architecture" markdown>
<p class="admonition-title">Governed candidate-claim lifecycle</p>

A candidate claim (domain + statement + confidence + proposed
`ChangeEnvelope`) is proposed via `propose_candidate_claim()`, persisting a
`:Claim` node (`is_verified=False`). `GovernedPromotionValidator.validate()`
then branches: a classification/policy or SHACL failure rejects to
**RETRACTED** (terminal, sticky, never materialized); PII detected also
rejects to RETRACTED (quarantined); dedup/contradiction/below-threshold
records a hold, staying **PROPOSED** (audit-visible); every gate clearing
validates to **VALIDATED** (still not a fact). A steward reviews validated
claims (`graph_claims list/get`); `graph_claims action=accept` (behind the
fail-closed `ActionPolicy` approval queue) accepts to **ACCEPTED**, which
triggers `materialize_on_claim_accepted()` → `ingest_envelope()` writing
the real, now-queryable typed fact. If later found wrong,
`graph_claims action=retract` calls `supersede_materialized_claim()` →
`retire_fact()`, tombstoning via `ingest_envelope(operation=delete)` plus a
`SUPERSEDES` edge — archived, not deleted, inspectable with its evidence
edge.

</div>

* **Steward review is structural, not a flag.** A candidate claim is always a
  generic `:Claim` node — never the real domain-typed entity/edge it proposes
  — so a "fact" query surface (one that answers domain questions over typed
  nodes) cannot see it until `materialize_on_claim_accepted` writes the real
  fact, which only runs after `graph_claims(action="accept")` clears the
  fail-closed `ActionPolicy` approval-queue gate (`kind="claim.accept"`,
  default tier `approval_required`). Unqueryable-as-fact is a property of what
  got written, not a filter a query path could forget to apply.
* **Every gate fails closed.** An unreadable classification policy, an
  unvalidatable SHACL shape (missing validator, missing shapes, malformed
  report), or an unscannable PII pass is recorded as a FAILED check — never
  skipped as a pass. This is the opposite of the advisory `SHACLValidator`/
  `shacl_gate` phase (fails open on a missing shapes file) and deliberately
  does not reuse that path for candidate-claim promotion.
* **Per-pack confidence thresholds** resolve from one bounded
  `INGESTION_CONFIDENCE_THRESHOLDS` mapping (domain → threshold; see
  [Configuration Reference](https://knuckles-team.github.io/agent-utilities/architecture/configuration/)), not a global constant.
* **Retraction/supersession preserves history.** `supersession.retire_fact`
  tombstones through the SAME fail-closed `ingest_envelope` path connectors
  use (`operation="delete"` — archives, closes the bitemporal interval, never
  deletes the node) and links a `SUPERSEDES` evidence edge, so a retired fact
  stays inspectable with the claim that retired it.
* **Dead-letter is loud and drainable.** `knowledge_graph/ingestion/
  dead_letter.py` adds `list`/`drain` over the existing `WorkItem` dead-letter
  terminal status — visible (never a silent aggregate-only count) and
  explicitly, manually requeued (never an automatic retry of an
  already-exhausted item; the original stays untouched for audit).
* **Both surfaces, one core.** `graph_claims`/`graph_jobs` (MCP) dispatch into
  this same module; REST parity is automatic via the existing
  `ACTION_TOOL_ROUTES` generic action-routed POST.

Module: `knowledge_graph/ingestion/{promotion,supersession,dead_letter}.py`.
Naming note (D-ST3-1): this type was originally named `CandidateClaim` as a
placeholder guess; the extraction-side `feat/candidate-claims-entity-resolution`
branch has since published the real, disjoint `CandidateClaim` (a
write-authority-free extraction proposal), so this one was renamed to
`promotion.PromotionRequest` — it carries an already-assembled `ChangeEnvelope`
(a concrete pending write) through governance gates, which the extraction-side
type never does. `PromotionRequest` is this lane's own minimal shape (one
proposed `ChangeEnvelope` + domain + confidence + optional `EvidenceBundle`);
adapt it once the sibling domain-pack contract publishes (see
`reports/deferred/promotion.md`, D-GP2-2).

---

## 8. Typed connector prepare → validate → map boundary

Connectors that ingest bounded Arrow pages can opt into the shared
`agent_utilities.data_prep.connector_contract` boundary without adding a
provider-specific commit path:

<div class="admonition architecture" markdown>
<p class="admonition-title">Typed connector prepare → validate → map</p>

A raw Arrow page goes through `CleanPipeline` (strict model + `PrepEvidence`),
then `ConnectorMapper` (pluggable domain mapping), producing a native
`ChangeEnvelope` (artifact refs + replay digest), which `ingest_envelope(s)`
commits (SHACL/ICV + durable cursor). A quarantine or failure at the
`CleanPipeline` step instead produces no checkpoint and no snapshot marker.

</div>

`ConnectorPrepContract` is versioned and binds immutable refs/digests for the
raw model, prep plan, expected Arrow schema, mapping, SHACL shapes, and ICV
policy.  `ConnectorPageLimits` bounds page rows, output cardinality, columns,
and redacted diagnostics.  A mapper receives the prepared Arrow table and
returns a bounded sequence of native `ChangeEnvelope` values; the contract
checks connector/tenant/schema authority, deterministic idempotency keys,
duplicate keys, and forbids a mapper from returning a page-level snapshot
marker or checkpoint.

Strict validation raises a stable redacted diagnostic.  Explicit quarantine
returns a `PreparedConnectorPage` whose certification is `quarantined` or
`partial`; accepted envelopes may be inspected by the caller, but the page
cannot advance its checkpoint.  Only a complete, diagnostic-free,
fetch-complete page can expose a checkpoint candidate.  Its
`snapshot_complete()` helper additionally refuses an empty live-id set unless
the caller supplies `authoritative_empty=True`, so failed or partial fetches
cannot become deletion or verified-empty snapshots.  The returned envelopes
still use the existing `ingest_envelope`/`ingest_envelopes` path; the engine,
not this boundary, remains the SHACL/ICV and durability authority.

## 9. Connector inventory

<!-- BEGIN:CONNECTOR-INVENTORY (generated by scripts/generate_connector_map.py) -->

_Auto-generated — do not edit by hand. Run `python scripts/generate_connector_map.py`._

**56 distinct connectors** across the ingestion/enrichment paths: 8 delta handlers · 32 capability-hydrate · 24 materialize extractors · 31 writeback sinks · 31 document-ingest presets.

### Connector × path matrix

`in` = ingests into the KG · `out` = writes KG intelligence back to the system.

| Connector | Delta (in) | Hydrate (in) | Materialize (in) | Writeback (out) |
|---|:--:|:--:|:--:|:--:|
| `ansible` | — | — | ✅ | ✅ |
| `archimate` | — | — | ✅ | ✅ |
| `archivebox` | ✅ | — | — | — |
| `aris` | — | ✅ | ✅ | — |
| `caddy` | — | ✅ | ✅ | ✅ |
| `camunda` | — | — | ✅ | — |
| `capability` | — | — | — | ✅ |
| `ciso_assistant` | — | — | ✅ | ✅ |
| `confluence` | ✅ | — | — | — |
| `databases` | — | ✅ | — | — |
| `egeria` | — | — | ✅ | ✅ |
| `emerald` | — | — | ✅ | ✅ |
| `emerald_exchange` | — | ✅ | — | — |
| `enterprise_architecture` | — | ✅ | — | — |
| `erpnext` | — | ✅ | ✅ | ✅ |
| `essential_ea` | — | ✅ | — | — |
| `freshrss` | ✅ | — | — | — |
| `github` | — | ✅ | — | ✅ |
| `gitlab` | ✅ | ✅ | — | ✅ |
| `glpi` | — | ✅ | — | — |
| `homeassistant` | — | — | ✅ | ✅ |
| `issue_tracking` | — | ✅ | — | — |
| `jira` | ✅ | — | — | ✅ |
| `jira_transition` | — | — | — | ✅ |
| `kafka` | — | — | ✅ | ✅ |
| `keycloak` | — | ✅ | ✅ | ✅ |
| `langfuse` | — | ✅ | — | — |
| `leanix` | ✅ | ✅ | — | ✅ |
| `legal` | — | — | — | ✅ |
| `lgtm` | — | ✅ | ✅ | ✅ |
| `listmonk` | — | ✅ | — | — |
| `mattermost` | — | ✅ | — | — |
| `mealie` | — | — | ✅ | ✅ |
| `message_protocol` | — | ✅ | — | — |
| `microsoft` | — | — | ✅ | — |
| `nextcloud` | — | ✅ | ✅ | ✅ |
| `okta` | — | — | ✅ | ✅ |
| `openbao` | — | ✅ | — | — |
| `openmaint` | — | ✅ | — | — |
| `plane` | ✅ | — | — | ✅ |
| `plane_state` | — | — | — | ✅ |
| `portainer` | — | ✅ | ✅ | ✅ |
| `postiz` | — | ✅ | — | — |
| `process` | — | — | — | ✅ |
| `process_modeling` | — | ✅ | — | — |
| `relational_database` | — | ✅ | — | — |
| `rss` | ✅ | — | — | — |
| `salesforce` | — | — | ✅ | ✅ |
| `scholarx` | — | ✅ | — | — |
| `servicenow` | — | ✅ | ✅ | ✅ |
| `source_control` | — | ✅ | — | — |
| `technitium_dns` | — | ✅ | ✅ | ✅ |
| `tunnel_manager` | — | ✅ | — | — |
| `twenty` | — | ✅ | ✅ | ✅ |
| `uptime_kuma` | — | ✅ | ✅ | ✅ |
| `wger` | — | — | ✅ | ✅ |

### Document-ingest presets (`MCP_TOOL_PRESETS`)

Declarative connectors that pull records/files/search-results as Documents through the generic `McpToolSourceConnector`:

- `archivebox`
- `confluence`
- `freshrss`
- `github-repos`
- `gitlab-issues`
- `gitlab-merge-requests`
- `harness-runs`
- `jira`
- `keycloak-users`
- `mealie-recipes`
- `nextcloud-files`
- `objectstore-prefix`
- `okta-users`
- `plane`
- `pulselink-bilibili`
- `pulselink-exa`
- `pulselink-github`
- `pulselink-hackernews`
- `pulselink-news`
- `pulselink-reddit`
- `pulselink-rss`
- `pulselink-v2ex`
- `pulselink-web`
- `pulselink-x`
- `pulselink-xiaohongshu`
- `pulselink-xueqiu`
- `pulselink-youtube`
- `searxng-search`
- `servicenow-table`
- `sql-query`
- `sql-table`

<!-- END:CONNECTOR-INVENTORY -->
