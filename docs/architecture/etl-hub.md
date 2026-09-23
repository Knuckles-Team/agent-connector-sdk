# Knowledge Graph as a Bidirectional ETL Hub (Stardog data backend, connectors, write-back, lineage)

> **CONCEPT:AU-KG.query.vendor-agnostic-traversal** (SPARQL data backend) · **KG-2.9** (unified ingestion contract) ·
> **AU-KG.ontology.one-source** (`graph_etl` unified pipeline) · **AU-KG.ontology.kg-3** (ETL lineage)
> **Modules:** `knowledge_graph/etl/{pipeline,lineage}.py` ·
> `knowledge_graph/backends/sparql/stardog_backend.py` ·
> `knowledge_graph/enrichment/{provenance,registry,materialize,writeback}` ·
> `knowledge_graph/integrations/stardog_sync.py`
> **Related:** [OWL/RDF Layer](https://knuckles-team.github.io/agent-utilities/architecture/owl_rdf_layer/) · [Graph Backend Architecture](https://knuckles-team.github.io/epistemic-graph/architecture/graph-backends/) ·
> [Camunda + ARIS ↔ KG](camunda-aris-integration.md) · Recipe: [Stardog + pg-age](https://knuckles-team.github.io/agent-utilities/recipes/databases/)

The agent-utilities Knowledge Graph is the **canonical hub** of a bidirectional ETL
spine: external systems are **extracted** into the KG, normalized through the OWL/ontology
layer (the *transform*), and **loaded** out to other systems — a triplestore like Stardog
(full data), a peer graph store (mirror), or a system-of-record (write-back intelligence).
"System A → ontological normalization → System B" is the architecture, exposed as one
`graph_etl` interface. It is built almost entirely on machinery that already existed (the
self-registering extractors, the OWL bridge, the write-back sink registry, the multi-backend
connection registry, the fan-out mirror) — so this is mostly *wiring*, not new transport.

## The spine

<div class="admonition architecture" markdown>
<p class="admonition-title">Bidirectional ETL hub</p>

External systems (LeanIX, ServiceNow, Egeria, Camunda/ARIS, GitLab/Jira/…)
feed extractors/hydration, which `stamp_source()` (source_system + domain)
and run through an ontology transform (interfaces, links, OWL bridge,
metamodel compile) into the canonical Knowledge Graph (the epistemic-graph
engine, the authority, keyed by externalToolId + domain federation keys).

Outbound, the hub feeds two paths: write-back sinks (18, `run_writeback`,
dry-run + `ProposalQueue`) back to the systems of record (LeanIX/
ServiceNow/Egeria), and graph-store load (`push_to_stardog`/`copy_graph`/
fan-out mirror) to Stardog and to Neo4j/FalkorDB/AGE. Every hub write also
records into ETL lineage (`PROVENANCE_AGENT` runs + `WAS_DERIVED_FROM`).

</div>

Both halves are **uniform across every connector**: a single provenance contract
(`source_system` + `domain`) and a single graph representation (real type/rel labels) mean a
new source is declarative config, never bespoke push/pull code.

## One ingestion contract (KG-2.9)

External connector ingestion has one durable path: connector-specific dicts or
typed `ExtractionBatch` values are normalized into a graph slice and committed
through native `ApplyChangeEnvelope`. Hydration implementations may still call
the compact `ingest_external_batch` protocol, but `HydrationManager` gives them
a native proxy; materialize extractors convert `ExtractionBatch` directly into
the same envelope. `registry.write_batch` remains an internal/offline writer for
legitimate non-source finance/synthesis construction and the explicit test-only
adapter; it is not a production connector authority.

- **Metadata** — envelope rendering stamps *both*
  `source_system` (provenance / named-graph routing) and `domain` (the federation key the
  write-back resolver queries). Internal-fact writes pass no source and stay untagged.
- **Representation** — native graph-slice envelopes preserve the **real** node type / edge rel.
  `:DomainEntity` / `:EXTERNAL_LINK` remain
  only as the no-type fallback. (Safe: nothing queries `:DomainEntity`; real types are
  `rdfs:subClassOf :DomainEntity`, so OWL reasoning is unaffected — and a SPARQL mirror now
  types every node by its real `rdf:type`.)

## Stardog as a SPARQL data backend (KG-2.7)

Stardog is a first-class data backend, distinct from the OWL *reasoning* backend
(`backends/owl/stardog_backend.py`) — the two compose: reason over the schema, store/serve the
data here.

<div class="admonition architecture" markdown>
<p class="admonition-title">Stardog SPARQL backend</p>

KG engine writes (`_upsert_node`/`_upsert_edge`, via
`ingest_external_batch`/`copy_graph`/fan-out replay) call
`StardogSparqlBackend.execute()`, which translates Cypher to SPARQL
(finite, owned MERGE shapes), routes to a named graph
(`graph_uri_for(props) → urn:source:<sys>`), and issues `INSERT DATA` into
Stardog. Separately, `execute_sparql`/`upload_graph`/`download_graph` query
and pull from Stardog directly.

</div>

The engine has **no SPARQL routing** — every write reaches a backend as Cypher. So the data
backend translates the engine's finite, owned MERGE shapes into SPARQL INSERT/DELETE (the same
shape-coupling the fan-out backend already uses), routing each node/edge into its
`urn:source:<system>` named graph by the `source_system` provenance. Registered as a
`role="mirror"` connection, every KG write replicates live; `push_to_stardog` /
`pull_from_stardog` give on-demand control.

## `graph_etl` — one pipeline run (AU-KG.ontology.one-source)

<div class="admonition architecture" markdown>
<p class="admonition-title">One `graph_etl` pipeline run</p>

The caller (MCP `graph_etl` or REST `/graph/etl`) calls
`run_etl.run(source, sink, mode, sources, dry_run, ops)`. If a source is
given, it calls `sync_source(engine, source, mode)` (extract+transform+load
into the KG), returning hydration counts. If a sink is given, either
`run_writeback` (dry-run + `ProposalQueue`, for a write-back domain) or
`push_to_stardog`/`copy_graph` (for a graph-store sink) runs, returning
created/node/edge counts. Either way, `run_etl` then calls
`record_etl_run(source, sink, direction, counts)` for lineage, which
returns a `run_id`, and finally returns `{status, inbound, outbound,
lineage}` to the caller.

</div>

`run_etl` is a thin orchestrator (no transport of its own) over `sync_source`,
`run_writeback`, `push_to_stardog`/`copy_graph`, and the connection registry. `source` or
`sink` may be omitted for a one-directional run. Surfaced as the `graph_etl` MCP tool
(`action=run|list|lineage`) and the `/graph/etl` REST twin (auto-served from
`ACTION_TOOL_ROUTES`).

The `{status, inbound, outbound, lineage}` manifest is built from `etl.result.EtlResult`
(AU-KG.etl.result-contract) — a validated pydantic contract (adds a typed `counts` dict,
replacing the old ad hoc `_count()` shape-guessing) — then serialized back to a plain
`dict` (`.model_dump()`) so existing callers keep indexing it unchanged. `sync_source` and
`ingest_connector_to_table` return the same coerced shape.

## ETL lineage (AU-KG.ontology.kg-3)

Every run records a trail in the KG itself, reusing the existing provenance ontology (no new
node/edge types): a `PROVENANCE_AGENT` run node (`kind="etl_run"`, source/sink/direction/counts)
plus `WAS_DERIVED_FROM` edges chaining `sink → run → source` through `urn:source:<s>` /
`urn:sink:<s>` system markers. `graph_etl action=lineage` (or `etl.query_lineage`) answers
impact-analysis questions — "what flows from ServiceNow to LeanIX?", "where did this Stardog
graph originate?".

## Surfaces

| Capability | MCP | REST |
|---|---|---|
| Run / inspect a pipeline | `graph_etl(action=run\|list\|lineage)` | `POST /graph/etl` |
| Push/pull/query Stardog directly | `graph_configure(action=push_to_stardog\|pull_from_stardog\|stardog_sparql)` | `POST /graph/configure` |
| Sync one source inbound | `source_sync` | `POST /source/sync` |
| Write-back to a system-of-record | `graph_writeback` | `POST /graph/writeback` |
| Register a mirror / connection | `graph_configure(action=add_connection)` | `POST /graph/configure` |

## Related

- [OWL/RDF Layer](https://knuckles-team.github.io/agent-utilities/architecture/owl_rdf_layer/) — local SPARQL + promotion/reasoning over any backend.
- [Graph Backend Architecture](https://knuckles-team.github.io/epistemic-graph/architecture/graph-backends/) — connection registry roles + fan-out mirroring.
- [Camunda + ARIS ↔ KG](camunda-aris-integration.md) — a worked bidirectional connector.
- Recipe: [Stardog + pg-age databases](https://knuckles-team.github.io/agent-utilities/recipes/databases/) — operational setup (Step 2b/7).
