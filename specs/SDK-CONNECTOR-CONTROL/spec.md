# SDK-CONNECTOR-CONTROL — SDK connector control, certification, and pack publication

**Requirement IDs:** SDK-CONNECTOR-CONTROL-R001 through SDK-CONNECTOR-CONTROL-R024.
**Owner:** agent-connector-sdk.
**Boundary:** This SDK owns source-side connector hosting, discovery, certification, pack construction, and submission. A graph service owns durable pack records and receipts; a control-plane service owns routing and activation policy. Vendor packages own their API calls.

## Outcome and scope

A fresh connector package can use one SDK server factory, one manifest, one credential-reference and HTTP/TLS stack, one certification command, and one generated graph client. Its published pack and tool pins are reproducible from the connector artifact, and the runner refuses uncertified or mismatched packages. Every migrated connector builds without importing `agent_utilities`. This is an SDK contract, not a requirement to copy any private fleet inventory.

The migration is five independently reviewable alphabetical batches: A–E (SDK-CONNECTOR-CONTROL-R009), F–J (SDK-CONNECTOR-CONTROL-R010), K–O (SDK-CONNECTOR-CONTROL-R011), P–S (SDK-CONNECTOR-CONTROL-R012), and T–Z (SDK-CONNECTOR-CONTROL-R013). Packages in a batch are selected from public connector repositories at implementation time, not from a hard-coded count. Those packages own their migration commits. SDK-CONNECTOR-CONTROL-R014 removes an old duplicate toolkit in the control-plane repository after consumers have migrated. SDK-CONNECTOR-CONTROL-R015 establishes the SDK as source lifecycle and certification owner while retiring the duplicate there. Connector base settings move into `agent_connector_sdk/config.py`. Deployment settings and agent/model settings stay with their owners (SDK-CONNECTOR-CONTROL-R016).

## Architecture and contracts

```text
vendor connector package ──manifest and entry point──▶ SDK discovery/certify
        │                                          │ exact package tuple, tool schemas
        └──FastMCP tools/resources/prompts─────────┤
                                                   ▼
                          SDK artifact capture → canonical ConnectorPack
                                                   │ generated client + idempotency
                                                   ▼
                                  durable pack authority and receipt
```

1. A connector manifest names its package identity, server identity, tool pins, capabilities, credential references, source streams, and artifact annotations. Validate closed kinds, sorted unique entries, URI schemes, tenant scope, and no literal secrets before opening a session. Reuse `manifest/model.py`, `loader.py`, `live_contract.py`, `tool_schema.py`, `artifacts/pack.py`, and `certify/`; extend them instead of adding a parallel schema or publisher.
2. Certification binds **entry-point group + name + distribution + version**, runtime MCP server identity, tool name, normalized input schema digest, normalized output schema digest, and declared capability. A missing output schema is still fingerprinted canonically, never treated as an empty wildcard. Normalize schemas through `manifest/tool_schema.py`; SDK conformance tests own the pin calculation. The graph service stores a `contract_pin` as a claim attribute and must not be asked to recompute SDK normalization.
3. Pack publication uses the graph service's generated `ConnectorPack` and `AgentComponent.Content` request/response types. SDK forms a deterministic idempotency key over tenant, connector identity, canonical pack digest, and operation. A retry of an identical request returns the same durable result. Pack entry bodies remain content-addressed and bounded. No hand-written duplicate wire DTO and no placeholder content pack are allowed.
4. SQL-backed source record submission uses the generated `SourceIngest` request, checkpoint and receipt types through the existing SDK sink. The adapter declares table/key identity, change operation, schema digest, source version and provenance. The runner submits bounded pages only after live contract validation. The accepted receipt, not local success, advances the cursor. Reject null or mismatched tenant, schema, primary key and checkpoint fields before the graph call.
5. Pack annotations are a closed, canonical map per entry: capability names, input and output schema digests, modality, bounded cost and latency estimates with units, and provenance. Missing estimates mean `unknown`, never zero. The SDK validates types and units, excludes presentation-only fields from contract fingerprints, and includes semantic annotation changes in the pack digest. Re-certifying the fleet means each package produces current nonempty fingerprints for every declared pin and passes a current live-contract comparison; a package count alone is insufficient.
6. `mcp/server.py`, `mcp/action_dispatch.py`, `auth/`, `http/`, `tls/`, `credentials/`, and `ports/` remain the sole shared connector toolkit. `env://` and `openbao://` references may appear in manifests; resolved values may appear only in request memory, never logs, exceptions, packs, or reports. Unknown auth, public network exposure, or uncertified package tuple fails closed.
7. Connector-internal tool choice or inbound event triage may request a proposal from a decision service. This proposal is observational only. It never directly authorizes a side effect or bypasses deterministic write-back rules.
8. The release contract locks a published compatible graph-client wheel and verifies its generated types, native kernels, and error catalog in an isolated installed consumer. A source overlay, unpinned wheel, or stale lock cannot stand in for the release dependency.
9. Every connector package performs HTTPS calls through the SDK's shared TLS profile in `tls/`; no connector may disable certificate verification with a bare boolean flag or silence the underlying TLS warning library (SDK-CONNECTOR-CONTROL-R017). The SDK's full test suite, strict type checking, and documentation build must pass cleanly against the connector control implementation from a fresh checkout, with no partial or broken module left in the merged source tree (SDK-CONNECTOR-CONTROL-R018).
10. `register_tool_surface` registers one condensed, intent-gated tool per registrar. It reads no `MCP_TOOL_MODE` setting and builds no separate verbose 1:1 tool surface, matching the ecosystem's single condensed intent contract (SDK-CONNECTOR-CONTROL-R020).

## Portable development and contribution

Clone this public repository, install `uv` and Python matching `pyproject.toml`, run `uv sync`, then run the tests in `test-spec.md`. Unit tests use in-memory fake MCP sessions and fake generated-client ports. No tenant, hosted graph, secret store, or private connector fleet is needed. A contributor can add one synthetic fixture connector in `tests/fixture_package` and prove manifest, pin, pack, and failure behavior. Live publication is a later acceptance gate with a contributor-owned environment.

## Completion rule

Delivery evidence requires an exact merged commit that contains the required implementation and checks. Acceptance requires the gates in `test-spec.md` to pass against that commit. The evidence section below must link a published wheel and a real connector pack receipt. Current implementation exists in `manifest/`, `certify/`, `mcp/`, `artifacts/`, and `runner/`, but fleet cutover and release acceptance are unverified here.

### Evidence

| Gate | Evidence |
| --- | --- |
| Exact merged SDK implementation | Pending exact commit |
| Five batch consumer conformance | Pending batch receipts |
| Published-wheel isolated consumer | Pending artifact digest and CI run |
| Live pack publication and idempotent retry | Pending redacted receipt |

Requirement IDs are defined in [requirements.md](requirements.md); delivery state per ID is in `status.json`.

## Access contracts (SDK-CONNECTOR-CONTROL-R021)

Each connector ontology declares how a consumer reads each class live. The `ac:` vocabulary in `agent_connector_sdk/ontology/access_contract.ttl` defines `ac:AccessContract` and `ac:PropertyBinding`. A contract names the class, the source, the entity and the key field. It names the access kind: `mcp_tool`, `http_endpoint`, `graphql_query` or `a2a_skill`. It names the operation, its parameters, the pagination mode and the pushdown operations. Pushdown operations are `filter`, `sort`, `limit` and `project`. `ac:authRef` holds an `env://` or `openbao://` reference, never a secret. Rate limit, freshness and cost hints let a consumer choose a live read or a copied hot slice. A missing hint means unknown.

`parse_access_contracts` reads the flat Turtle profile and returns typed `AccessContract` values. `virtual_mapping_fields` returns the agent-utilities `VirtualMapping` arguments. graph-os onboarding imports these contracts as unapproved mappings. EG-UNIFIED-DATA-PLANE-R037/R038 and EG-FEDERATED-QUERY-R072/R073 consume the result.

## Pack-scoped ontology imports (SDK-CONNECTOR-CONTROL-R022)

epistemic-graph accepts an `owl:imports` only when it names an ontology entry of the same pack.
Fleet ontologies import shared hub ontologies such as `http://knuckles.team/kg`.
The tenant schema composes every attached pack, so the hub import is redundant at pack scope.
`build_content_pack` removes each import outside the pack from every ontology body.
It records each removed IRI as `ontology-import:<iri>` in the entry's `requires_capabilities` annotation.
The builder handles Turtle and RDF/XML bodies.
A body without external imports stays byte-identical.

## Prompt capture with required arguments (SDK-CONNECTOR-CONTROL-R023)

A prompt with no required argument is captured by rendering it, unchanged from prior behavior.
A prompt with a required argument is captured as a template instead of refused.
`PromptArtifactKind` binds each required argument to a deterministic `{{name}}` placeholder.
It calls `prompts/get` with those bound placeholders and leaves optional arguments unbound.
The captured body records `capture.kind` as `template` and `capture.bound_arguments` as the placeholder map.
`build_content_pack` treats a template capture the same as a rendered capture; the pack entry body is opaque bytes to the archive.
A prompt onboarding path that previously raised `MalformedArtifactError` for a required argument now succeeds.

## Prompt capture when the server rejects the bound placeholder (SDK-CONNECTOR-CONTROL-R024)

A typed required prompt argument (`int`, `float`, `bool`, `list`, or an enum) can refuse the string `{{name}}` placeholder SDK-CONNECTOR-CONTROL-R023 binds for it.
Capture must never depend on the server accepting a placeholder value for a typed argument.
`McpClientSession.get_prompt` distinguishes a well-formed MCP protocol error from every other failure.
A protocol error (`mcp.shared.exceptions.MCPError`) raises `McpPromptRejectedError`, a subclass of `McpTransportError`.
Every other failure, including a transport failure such as a timeout or dropped connection, still raises the plain `McpTransportError` it always has.
`PromptArtifactKind.list_entries` catches `McpPromptRejectedError` only for a prompt that bound at least one required argument.
On that catch it builds the captured `result` from the prompt's own listed name and arguments alone, with no server-rendered content, and keeps `capture.kind` as `template`.
A prompt with no required argument never bound a placeholder, so the same error there is a genuine rejection and still raises.
Any failure that is not `McpPromptRejectedError` always raises, so a server that is truly unreachable still fails the capture.

## Caller-scoped context and progress

SDK-CONNECTOR-CONTROL-R050 defines the shared context for every registered tool.
Callers receive ordered progress without polling and a correlated terminal result.
A call without a progress token emits no progress notification.
Context state is a disposable request cache; durable knowledge remains owned by EG.
EG owns approval decisions. GraphOS serves the authenticated approval exchange and returns EG's decision unchanged.
The SDK checks the decision's binding before a source effect.
Reconnect recovery refuses when its authenticated durable result producer is unavailable.
Acceptance requires the served integration cases CC-50 through CC-55.


## Hosted credential binding

R035.1 through R035.6 require exact host-authorized tenant/client/resource bindings for every secret reference, including process-visible environment values.
R046 uses the same host-owned challenge and vault authority for bounded inline PKCE, without blocking stdin or pasted-code files.
GRAPHOS-IDENTITY-R023 defines the matching consumer; qualified grant, challenge and persistence ports remain missing integration.
All added or refined work requires served integration acceptance.

<!-- spec-definition-patch:sdk5-r007-major-version-gate -->
## Major-version compatibility receipt and pre-pin gate (R007.1-R007.6)

A major-version rollout is one transition over the complete authoritative connector-package inventory. Bind the transition to the distribution, old and target major pins, immutable target artifact digest, and canonical inventory snapshot. Bind each sorted package entry to its repository, source commit, current pin, and dependency-file preimage digest. Hash canonical entries with SHA-256. The producer stops if it cannot list every package.

Evaluate the target artifact in an isolated candidate environment for every package. Do not change tracked manifests or lockfiles. Emit one completed `PackageCompatibilityReceipt` per package. Bind each receipt to the transition, inventory, package, source commit, and old and target pins. Also bind its preimage, artifact, complete check suite, run, and outcome. Import scans alone do not prove compatibility.

Use this producer-to-consumer order:

1. `agent_connector_sdk.testing.fleet_migration.evaluate_major_version_compatibility(inventory, transition)` produces receipts for the complete inventory.
2. `authorize_major_version_pin_changes(transition, inventory, receipts)` validates exact membership and freshness. It authorizes only a complete, passing set.
3. Each package writer calls `require_package_pin_change(gate, package_id, pin_preimage)` before its first pin write. R009-R013 use this same gate.

The gate checks the transition, artifact, inventory, package source, current pin, and preimage. It refuses missing, duplicate, extra, failed, incomplete, cancelled, stale, or mismatched receipts before any pin changes. Each refusal preserves every pin. One package's receipt cannot authorize another package.

**Implementation boundary:** `agent_connector_sdk.testing.fleet_migration.scan_many_packages` and `PackageScanResult` currently report import-scan findings only. They do not produce compatibility receipts, evaluate a target artifact, authorize rollout, or gate pin writes. The producer, gate, rollout command, and R009-R013 writer attachments remain unimplemented. R007.6 describes future proof; this definition claims no runtime behavior or test result. Existing R007 fingerprint and live-contract checks, plus R009-R013 migration obligations, remain in force.
<!-- /spec-definition-patch -->

<!-- spec-definition-patch:sdk-consolidated-primary-20261012-spec -->

## Sandbox allocation producer for AU:29 (R051.1-R051.6)

The SDK provisions and reconciles admitted sandbox requests through one typed port. GraphOS owns host admission and the certified support matrix. Source trace: `AU:29 49df21c60c947240d4f02b1424b1de29183f10a69c76bd885f19d13e7237061c`.

**SDK-CONNECTOR-CONTROL-R051.1 — Model.** Define SandboxProvisioner. It consumes GraphOS ProvisionRequest. It returns ProvisionResult with allocation ID, actual instances, observed image/platform, state, timestamps, and provider receipt.

**SDK-CONNECTOR-CONTROL-R051.2 — Behavior.** Allocate once per stable operation ID. Reconcile uncertain results before retry. Transport loss never proves no allocation.

**SDK-CONNECTOR-CONTROL-R051.3 — Wiring.** Plan agent_connector_sdk.ports.sandbox.SandboxProvisioner. Route AU sandbox access through GraphOS agents.run and NativeWorkItemAdmissionProtocol/CapacityLedger. Call the SDK adapter, then return its receipt to GraphOS. This producer and binding are absent.

**SDK-CONNECTOR-CONTROL-R051.4 — Refusal.** Refuse unsupported profiles, missing grants, expired requests, and conflicting replay IDs before provider calls. Reconcile unresolved outcomes before retry. Unsupported combinations allocate nothing.

**SDK-CONNECTOR-CONTROL-R051.5 — Evidence.** Bind request/result digests, adapter version, matrix revision, operation/allocation IDs, instances, state, timestamps, and reconciliation. Exclude credentials and secret values.

**SDK-CONNECTOR-CONTROL-R051.6 — Hot-path proof.** Future served tests enter GraphOS agents.run. Use a disposable certified adapter. Observe instances and independent readback. Test unsupported profiles and response loss without duplicates.

## Visual observation transport for AU:35 (R052.1-R052.6)

The SDK transports visual observations and provenance between steps. EG owns durable perception state; AU owns next-step conditioning. SDK request_cache remains request-scoped. Source trace: `AU:35 9da1fe3853d82945989df4194b626b793a37937ff892b483c1583a8d1aae644e`.

**SDK-CONNECTOR-CONTROL-R052.1 — Model.** Define VisualObservationEnvelope. Include observation ID, modality, source operation, and frame or sequence. Bind capture time, content digest/reference, tenant/run/request scope, and schema revision. Keep payload behind governed references.

**SDK-CONNECTOR-CONTROL-R052.2 — Behavior.** Pass ordered observation references to the next authorized step in the same run. EG owns durable storage and retention. SDK request_cache is not cross-request memory.

**SDK-CONNECTOR-CONTROL-R052.3 — Wiring.** Bind create_mcp_server tools/call through tool_surface or method_tools and dispatch_async. Forward the observation to EG state, then AU. The current SDK path lacks this producer and binding.

**SDK-CONNECTOR-CONTROL-R052.4 — Refusal.** Refuse expired, invalidated, uncommitted, unauthorized, cross-tenant/run, and wrong-schema references before provider calls. Never substitute another request's cache.

**SDK-CONNECTOR-CONTROL-R052.5 — Evidence.** Bind the digest, source/frame, producer operation, tenant/run, schema revision, retention decision, and consumer step. Exclude raw visual content and secrets.

**SDK-CONNECTOR-CONTROL-R052.6 — Hot-path proof.** Future served tests cross MCP tools/call, EG state write/readback, and AU next-step use. Prove same-run reuse, cross-run isolation, and stale-reference refusal.

## SDK environment declarations for GRAPHOS:9 (R053.1-R053.6)

The SDK declares environment inputs used by enabled SDK components, including indirect reads. GraphOS owns startup validation; AU owns AU declarations. Source trace: `GRAPHOS:9 cfd8f1270b5ec1f19d8c78f50e5a833695573763a691584e8c74d8fa5f1cb225`.

**SDK-CONNECTOR-CONTROL-R053.1 — Model.** Define versioned EnvironmentDeclaration records. Include component/distribution, schema revision, input name, required state, type constraints, and direct/indirect read source. Store no values.

**SDK-CONNECTOR-CONTROL-R053.2 — Behavior.** Plan SDK environment_manifest to list declarations for every enabled SDK component and transitive setting. This producer is absent from the public SDK surface.

**SDK-CONNECTOR-CONTROL-R053.3 — Wiring.** Bind the SDK export to GraphOS HostEnvironmentManifest and its R010 startup consumer. Do not duplicate its schema or validator. AU declarations stay AU-owned.

**SDK-CONNECTOR-CONTROL-R053.4 — Refusal.** Refuse startup before serving on missing, malformed, or undeclared inputs. Name the input where required. Never reveal its value.

**SDK-CONNECTOR-CONTROL-R053.5 — Evidence.** Bind declaration digest, component versions, enabled set, schema revision, validation outcome, and host decision. Persist names and constraints, never values.

**SDK-CONNECTOR-CONTROL-R053.6 — Hot-path proof.** Future served tests cover enabled components and indirect reads. Test missing, malformed, and undeclared inputs. Confirm no route admission and redact secret values.

## JSON tag-loader migration for AU:89 (R054.1-R054.6)

Inventory each JSON tag loader and migrate it to Python registration with served parity. Preserve the condensed default and R026/R032 opt-ins. Source trace: `AU:89 3916d50003442e91ad490706e9c9cd0d77211af4998baa3ad98220457e4c7d1a`.

**SDK-CONNECTOR-CONTROL-R054.1 — Model.** Bind each entry to package, repository, JSON digest, target, and operation IDs. Also record schemas, tags, mode, authorization reference, and refusal cases.

**SDK-CONNECTOR-CONTROL-R054.2 — Behavior.** Migrate entries through register_tool_surface or register_method_tools. Keep condensed action routing as default. Preserve explicit R026/R032 opt-ins; clarify R020 wording.

**SDK-CONNECTOR-CONTROL-R054.3 — Wiring.** Bind inventory and parity checks to tools/list and tools/call through Python registration and action_dispatch. Current definitions lack a complete census and gate.

**SDK-CONNECTOR-CONTROL-R054.4 — Refusal.** Preserve denied, malformed, unknown, unsupported, and schema-mismatch refusals. Any unclassified loader or unexplained difference blocks completion.

**SDK-CONNECTOR-CONTROL-R054.5 — Evidence.** Record revisions, inventory digest, operation/schema/tag parity, mode, authorization/refusal comparison, and served receipt. Do not claim completion before readback.

**SDK-CONNECTOR-CONTROL-R054.6 — Hot-path proof.** Future served tests list every package with tools/list. Then call each operation. Include denied and malformed calls. Test condensed default and supported opt-ins.

## Consolidated packet trace

SDK:5 remains defined by R007.1-R007.6. No duplicate SDK:5 rows were added. `AU:29 49df21c60c947240d4f02b1424b1de29183f10a69c76bd885f19d13e7237061c`; `AU:35 9da1fe3853d82945989df4194b626b793a37937ff892b483c1583a8d1aae644e`; `GRAPHOS:9 cfd8f1270b5ec1f19d8c78f50e5a833695573763a691584e8c74d8fa5f1cb225`; `AU:89 3916d50003442e91ad490706e9c9cd0d77211af4998baa3ad98220457e4c7d1a`.

The current SDK tree lacks these four producers and bindings. This packet adds definitions only. It adds no runtime implementation or acceptance receipt.
<!-- /spec-definition-patch -->
