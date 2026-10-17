# Tasks: connector control

- [x] Verify canonical package tuple and input/output pins across direct and entry-point discovery (SDK-CONNECTOR-CONTROL-R002, SDK-CONNECTOR-CONTROL-R003, SDK-CONNECTOR-CONTROL-R004).
- [x] Complete generated-type pack publisher, deterministic idempotency, and published-wheel release lock (SDK-CONNECTOR-CONTROL-R001, SDK-QUALITY-RELEASE-R001, SDK-CONNECTOR-CONTROL-R005, SDK-SOURCE-INGEST-R001).
- [x] Add annotation and proposal-only contracts to synthetic fixture (SDK-CONNECTOR-CONTROL-R006, SDK-CONNECTOR-CONTROL-R007, SDK-CONNECTOR-CONTROL-R008).
- [x] Migrate connector packages in five independent alphabetical batches (SDK-CONNECTOR-CONTROL-R009–SDK-CONNECTOR-CONTROL-R013).
  - [x] Shared per-package import scan (`agent_connector_sdk.testing.fleet_migration.scan_for_agent_utilities_imports`, AST-based) each batch's verification column asks for, owned once by the SDK's own test kit rather than re-derived per batch.
  - [x] Run it against the live fleet: as of this scan, 2 of 74 `agents/*` packages (`market-data-mcp`, `world-reference-mcp`) carry zero `agent_utilities` imports, but both are scaffolded clean from their first commit, not migrated from an agent_utilities base — no batch (A-E, F-J, K-O, P-S, T-Z) has an actual migration commit yet. SDK-CONNECTOR-CONTROL-R009–R013 remain SPECIFIED; those migration commits land in each connector package's own repository.
- [x] Retire duplicate toolkit/certification/config paths only after consumer import scans (SDK-CONNECTOR-CONTROL-R014, SDK-CONNECTOR-CONTROL-R015, SDK-CONNECTOR-CONTROL-R016).
- [ ] **R014.1:** Add `scan_many_packages` to `agent_connector_sdk.testing.fleet_migration` — one call site that scans several package roots and keys each `PackageScanResult` by name, reused by R014's fleet census and every R009-R013 batch scan.
- [x] **R014.2:** Cross-platform advisory file locks. Moved from agent-utilities so connectors depend only on the SDK.
- [x] **R014.3:** Tool version metadata. Moved from agent-utilities so connectors depend only on the SDK.
- [x] **R014.4:** Reference-only CLI secrets. Moved from agent-utilities so connectors depend only on the SDK.
- [x] **R014.5:** Operator base-URL egress guard. Moved from agent-utilities so connectors depend only on the SDK.
- [x] **R014.6:** PII sanitizer. Moved from agent-utilities so connectors depend only on the SDK.
- [x] **R014.7:** Connector state directories. Moved from agent-utilities so connectors depend only on the SDK.
- [x] **R014.8:** Delegated-token helpers. Moved from agent-utilities so connectors depend only on the SDK.
- [x] **R014.9:** Keyless credential sentinel. Moved from agent-utilities so connectors depend only on the SDK.
- [x] **R014.10:** Class-based API client base and auth strategies. Moved from agent-utilities so connectors depend only on the SDK.
- [x] **R014.11:** Browser OAuth (PKCE) login. Moved from agent-utilities so connectors depend only on the SDK.
- [x] **R014.12:** GraphQL schema discovery over a connector executor. Moved from agent-utilities so connectors depend only on the SDK.
- [x] **R014.13:** Per-record external access descriptor. Moved from agent-utilities so connectors depend only on the SDK.
- [x] **R014.14:** Connector env-var drift check. Moved from agent-utilities so connectors depend only on the SDK.
- [x] **R014.15:** External ACL sync into ingested documents. Moved from agent-utilities so connectors depend only on the SDK.
- [x] **R014.16:** DNS-pinned egress (`pin_egress`, `allowed_private_hosts`) on `HttpClientOptions`. Moved from agent-utilities so connectors depend only on the SDK.
- [x] **R014.17:** MCP-free base install; `fastmcp` and `mcp` move to the `mcp` extra.
- [x] **R014.18:** Default fail-closed served security profile (`apply_served_security_profile`) for every connector MCP server.
- [x] **R014.19:** Selected-provider credential profile in `agent_connector_sdk.credentials.provider_profile`.
- [x] **R014.20:** Entry-point groups renamed to `agent_connector_sdk.<x>`.
- [x] **R014.22:** External embedding API client (`agent_connector_sdk.embeddings`). Moved from agent-utilities so connectors depend only on the SDK.
- [x] **R014.23:** Typed epistemic-graph compute adapter with ontology-driven algorithm selection (`agent_connector_sdk.compute`). Replaces connector-local finance computation imported from agent-utilities.
- [ ] **R015.1:** Add `scan_for_duplicate_manifest_or_certify_definitions` to `agent_connector_sdk.testing.duplicate_symbol_scan` — flags a connector package that locally defines `ConnectorManifest`/`CertificationReport`/`certify_connector` instead of importing them from the SDK.
  - [x] Port `agent_utilities.security.entitlements.identity_scoped_resources` to `agent_connector_sdk.entitlements`, over the SDK's own `identity.ActorContext` (SDK-CONNECTOR-CONTROL-R025). A fleet consumer (`vector-mcp`, `documentdb-mcp`, `sql-mcp`, `dockerhub-api`, `keycloak-agent`, `openbao-mcp`, `portainer-agent`, `tunnel-manager`, `systems-manager`, `container-manager-mcp` and others) can now swap its import with no call-site change.
- [ ] **R020.1:** Extend `scan_many_packages` to inventory JSON tag loaders and prove parity across source and replacement registration.
- [ ] **R050.7:** Add visual observation transport between ordered steps within a run, with frame provenance and ordered reference passing.
  - [x] Add `agent_connector_sdk.mcp.method_tools.register_method_tools`, an explicit opt-in primitive deriving one tool per public client-class method (SDK-CONNECTOR-CONTROL-R026). `data-science-mcp`'s `mcp_server.py` stays on `agent_utilities.mcp.verbose_tools.register_tool_surface` for exactly this (its own code comment names the gap as SDK-CONNECTOR-CONTROL-R009). It can now migrate without losing its per-`MLEngine`-method tool surface.
- [ ] Attach exact merged commit, artifact digest, CI result, typed SQL receipt and live redacted pack receipt. Mark accepted only when CC-01–CC-10 pass.
- [x] Verify every connector uses the shared TLS profile with no bare verify-bypass, and that the full test suite, strict type check and docs build pass cleanly from a fresh checkout (SDK-CONNECTOR-CONTROL-R017, SDK-CONNECTOR-CONTROL-R018).
- [x] Expose `ontology_resources` and `register_ontology_resources` for host servers; reuse them in `register_connector_content` (SDK-CONNECTOR-CONTROL-R019).
- [x] Release the SDK so agent-utilities can raise its SDK floor (SDK-CONNECTOR-CONTROL-R019).
- [x] Delete `mcp/tool_mode.py` and the retired verbose 1:1 tool-surface modules; make `register_tool_surface` always register the condensed, gated tool surface with no `MCP_TOOL_MODE` branch (SDK-CONNECTOR-CONTROL-R020).
- [x] Ship the access-contract vocabulary, `parse_access_contracts` and CC-11 tests (SDK-CONNECTOR-CONTROL-R021).
- [x] Serve `access_contract.ttl` beside each connector ontology and add contracts to fleet connector ontologies (SDK-CONNECTOR-CONTROL-R021).
- [x] arbora onboarding imports each contract as an unapproved `VirtualMapping` and a `SourceConnection` (SDK-CONNECTOR-CONTROL-R021; consumer work in agent-utilities and arbora).
- [x] Scope ontology `owl:imports` to the pack and record external IRIs (SDK-CONNECTOR-CONTROL-R022).
- [x] Rebuild and reattach fleet packs that import `http://knuckles.team/kg` (SDK-CONNECTOR-CONTROL-R022).
- [x] Bind required prompt arguments to `{{name}}` placeholders and capture a template instead of refusing (SDK-CONNECTOR-CONTROL-R023).
- [x] Fall back to a synthesized template when the server rejects a bound placeholder for a typed required argument, without masking a genuine transport failure (SDK-CONNECTOR-CONTROL-R024).
- [ ] Type the cross-source connector operation contracts and declare MCP, A2A, API, GraphQL and virtual-graph access kinds (SDK-CONNECTOR-CONTROL-R037 to SDK-CONNECTOR-CONTROL-R044).
- [ ] **R045.1:** Add the frozen `ToolContractFacts` model with its five fields in `agent_connector_sdk/artifacts/tool_facts.py`. (SDK-CONNECTOR-CONTROL-R045.1).
- [ ] **R045.2:** Add the closed `SideEffect` enum and the read-only consistency refusal. (SDK-CONNECTOR-CONTROL-R045.2).
- [ ] **R045.3:** Add `schema_tokens` over the canonical body already built in `_tool_entry`. (SDK-CONNECTOR-CONTROL-R045.3).
- [ ] **R045.4:** Add `facts_from_declaration` with the safe defaults and no name-based inference. (SDK-CONNECTOR-CONTROL-R045.4).
- [ ] **R045.5:** Read `readOnlyHint` into the facts builder and record `declared_by = mcp_hint`. (SDK-CONNECTOR-CONTROL-R045.5).
- [ ] **R045.6:** Bump the graph-client wheel lock after the `EG-TYPED-PACKS` annotation fields land; read `side_effects` from `eg.annotations`. (SDK-CONNECTOR-CONTROL-R045.6).
- [ ] **R045.7:** Call `is_destructive_action` from the facts builder to force `read_only = false`. (SDK-CONNECTOR-CONTROL-R045.7).
- [ ] **R045.8:** Build `ToolContractFacts` inside `_tool_entry` and pass them in the entry annotations. (SDK-CONNECTOR-CONTROL-R045.8).
- [ ] **R045.9:** Add `ToolFixture` and `check_read_only`, then call it from `tool_verdicts` for each `read_only` tool. (SDK-CONNECTOR-CONTROL-R045.9).
- [ ] **R045.10:** Return the `unproven` verdict and exclude the tool from `_certified`. (SDK-CONNECTOR-CONTROL-R045.10).
- [ ] **R045.11:** Extend `write_certified_pins` to render the facts; add the certification-to-pack end-to-end test. (SDK-CONNECTOR-CONTROL-R045.11).
- [ ] **R046:** Browser authorization-code flow with PKCE as a reusable auth manager. (SDK-CONNECTOR-CONTROL-R046).
  - [ ] **R046.1:** Model row. (SDK-CONNECTOR-CONTROL-R046.1).
  - [ ] **R046.2:** Behavior row. (SDK-CONNECTOR-CONTROL-R046.2).
  - [ ] **R046.3:** Wiring row. (SDK-CONNECTOR-CONTROL-R046.3).
  - [ ] **R046.4:** Refusal row. (SDK-CONNECTOR-CONTROL-R046.4).
  - [ ] **R046.5:** Evidence row. (SDK-CONNECTOR-CONTROL-R046.5).
  - [ ] **R046.6:** Hot-path proof row. (SDK-CONNECTOR-CONTROL-R046.6).
- [ ] **R047:** Agent-card discovery from the standard well-known path. (SDK-CONNECTOR-CONTROL-R047).
  - [ ] **R047.1:** Model row. (SDK-CONNECTOR-CONTROL-R047.1).
  - [ ] **R047.2:** Behavior row. (SDK-CONNECTOR-CONTROL-R047.2).
  - [ ] **R047.3:** Wiring row. (SDK-CONNECTOR-CONTROL-R047.3).
  - [ ] **R047.4:** Refusal row. (SDK-CONNECTOR-CONTROL-R047.4).
  - [ ] **R047.5:** Evidence row. (SDK-CONNECTOR-CONTROL-R047.5).
- [ ] **R055:** Arbora producer-consumer handoff for AU disclosure-set gate. Bind Arbora find, EG ToolRelevance, and AU DisclosureSet gate.
- [ ] **R056:** EG and SDK tool producer compatibility decisions and receipts. Bind at schema-fingerprint/FleetOnboarding.onboard.
- [ ] **R057:** Replaceable search-grounding provider independent of reasoning model. Test provider/model independence.
- [ ] **R058:** Request durability boundary correction. Separate transport selection from durability class.
- [ ] **R059:** EG capability-to-existing-method bindings. Map five capabilities to existing EG methods.
- [ ] **R060:** Native desktop operation port and no-cursor/no-focus invariant. Served tests with grant-bound refusal.
  - [ ] **R047.6:** Hot-path proof row. (SDK-CONNECTOR-CONTROL-R047.6).
- [ ] **R048:** Agent-readable text form in tool contracts. (SDK-CONNECTOR-CONTROL-R048).
  - [ ] **R048.1:** Model row. (SDK-CONNECTOR-CONTROL-R048.1).
  - [ ] **R048.2:** Behavior row. (SDK-CONNECTOR-CONTROL-R048.2).
  - [ ] **R048.3:** Wiring row. (SDK-CONNECTOR-CONTROL-R048.3).
  - [ ] **R048.4:** Refusal row. (SDK-CONNECTOR-CONTROL-R048.4).
  - [ ] **R048.5:** Evidence row. (SDK-CONNECTOR-CONTROL-R048.5).
  - [ ] **R048.6:** Hot-path proof row. (SDK-CONNECTOR-CONTROL-R048.6).
- [ ] **R049:** Budget-limited, approval-gated payment challenge handling. (SDK-CONNECTOR-CONTROL-R049).
  - [ ] **R049.1:** Model row. (SDK-CONNECTOR-CONTROL-R049.1).
  - [ ] **R049.2:** Behavior row. (SDK-CONNECTOR-CONTROL-R049.2).
  - [ ] **R049.3:** Wiring row. (SDK-CONNECTOR-CONTROL-R049.3).
  - [ ] **R049.4:** Refusal row. (SDK-CONNECTOR-CONTROL-R049.4).
  - [ ] **R049.5:** Evidence row. (SDK-CONNECTOR-CONTROL-R049.5).
  - [ ] **R049.6:** Hot-path proof row. (SDK-CONNECTOR-CONTROL-R049.6).
- [ ] **R050.1:** Implement and verify model acceptance (SDK-CONNECTOR-CONTROL-R050.1).
- [ ] **R050.2:** Implement strict emitted progress and concurrent equal-value suppression (SDK-CONNECTOR-CONTROL-R050.2).
- [ ] **R050.3:** Implement and verify wiring acceptance (SDK-CONNECTOR-CONTROL-R050.3).
- [ ] **R050.4:** Verify EG approval binding and unavailable reconnect producer refusal (SDK-CONNECTOR-CONTROL-R050.4).
- [ ] **R050.5:** Implement and verify evidence acceptance (SDK-CONNECTOR-CONTROL-R050.5).
- [ ] **R050.6:** Verify served progress, approval and reconnect refusal acceptance (SDK-CONNECTOR-CONTROL-R050.6).

- [ ] **SDK-CONNECTOR-CONTROL-R035.1:** Model: host-bound credential use.
- [ ] **SDK-CONNECTOR-CONTROL-R035.2:** Behavior: host-bound credential use.
- [ ] **SDK-CONNECTOR-CONTROL-R035.3:** Wiring: host-bound credential use.
- [ ] **SDK-CONNECTOR-CONTROL-R035.4:** Refusal: host-bound credential use.
- [ ] **SDK-CONNECTOR-CONTROL-R035.5:** Evidence: host-bound credential use.
- [ ] **SDK-CONNECTOR-CONTROL-R035.6:** Hot-path proof: host-bound credential use.

<!-- spec-definition-patch:sdk5-r007-major-version-tasks -->
## SDK:5 - major-version compatibility gate

- [ ] **SDK-CONNECTOR-CONTROL-R007.1:** Define transition, canonical inventory, receipt, and gate models bound to package and artifact identities.
- [ ] **SDK-CONNECTOR-CONTROL-R007.2:** Evaluate every package against the target artifact in isolation; emit one complete receipt per package without changing tracked pins.
- [ ] **SDK-CONNECTOR-CONTROL-R007.3:** Implement fleet authorization and a package-specific pre-write check; attach both to rollout and R009-R013 writers.
- [ ] **SDK-CONNECTOR-CONTROL-R007.4:** Preserve pins on preflight refusal. Report later package races as partial outcomes needing reconciliation.
- [ ] **SDK-CONNECTOR-CONTROL-R007.5:** Persist reproducible, credential-free transition, inventory, receipt, suite, and authorization evidence.
- [ ] **SDK-CONNECTOR-CONTROL-R007.6:** Prove preflight safety; prove writer-race refusal and reconciliation.
- [ ] Preserve existing R007 fingerprint and live-contract acceptance and R009-R013 migration acceptance; do not claim implementation evidence.
<!-- /spec-definition-patch -->

<!-- spec-definition-patch:sdk-consolidated-primary-20261012-tasks -->
## Consolidated SDK definitions
- [ ] **SDK-CONNECTOR-CONTROL-R051:** Define and prove the sandbox allocation producer; runtime and served evidence remain absent.
- [ ] **SDK-CONNECTOR-CONTROL-R052:** Define and prove visual observation transport; runtime and served evidence remain absent.
- [ ] **SDK-CONNECTOR-CONTROL-R053:** Implement the public environment declaration export and prove its host startup binding; served acceptance remains pending.
- [ ] **SDK-CONNECTOR-CONTROL-R054:** Inventory pinned JSON tag loaders and prove served registration parity with explicit opt-ins preserved.
- [ ] **SDK-CONNECTOR-CONTROL-R051.1:** Model and acceptance remain unimplemented.
- [ ] **SDK-CONNECTOR-CONTROL-R051.2:** Behavior and acceptance remain unimplemented.
- [ ] **SDK-CONNECTOR-CONTROL-R051.3:** Wiring and acceptance remain unimplemented.
- [ ] **SDK-CONNECTOR-CONTROL-R051.4:** Refusal and acceptance remain unimplemented.
- [ ] **SDK-CONNECTOR-CONTROL-R051.5:** Evidence and acceptance remain unimplemented.
- [ ] **SDK-CONNECTOR-CONTROL-R051.6:** Hot-path proof and acceptance remain unimplemented.
- [ ] **SDK-CONNECTOR-CONTROL-R052.1:** Model and acceptance remain unimplemented.
- [ ] **SDK-CONNECTOR-CONTROL-R052.2:** Behavior and acceptance remain unimplemented.
- [ ] **SDK-CONNECTOR-CONTROL-R052.3:** Wiring and acceptance remain unimplemented.
- [ ] **SDK-CONNECTOR-CONTROL-R052.4:** Refusal and acceptance remain unimplemented.
- [ ] **SDK-CONNECTOR-CONTROL-R052.5:** Evidence and acceptance remain unimplemented.
- [ ] **SDK-CONNECTOR-CONTROL-R052.6:** Hot-path proof and acceptance remain unimplemented.
- [ ] **SDK-CONNECTOR-CONTROL-R053.1:** Model; implement the planned test_manifest_rejects_duplicate_literal_and_unknown_entries acceptance.
- [ ] **SDK-CONNECTOR-CONTROL-R053.2:** Behavior; implement the planned test_missing_and_undeclared_inputs_block_startup acceptance.
- [ ] **SDK-CONNECTOR-CONTROL-R053.3:** Wiring; implement the planned test_host_startup_consumes_sdk_declaration_set acceptance.
- [ ] **SDK-CONNECTOR-CONTROL-R053.4:** Refusal; implement the planned test_refusal_diagnostics_redact_secret_values acceptance.
- [ ] **SDK-CONNECTOR-CONTROL-R053.5:** Evidence; implement the planned test_readback_matches_manifest_and_decision acceptance.
- [ ] **SDK-CONNECTOR-CONTROL-R053.6:** Hot-path proof; implement the planned test_served_startup_accepts_declared_and_refuses_invalid acceptance.
- [ ] **SDK-CONNECTOR-CONTROL-R054.1:** Define and validate JsonTagLoaderEntry and deterministic inventory ordering.
- [ ] **SDK-CONNECTOR-CONTROL-R054.2:** Scan pinned package inputs and block every unresolved loader or unmapped operation.
- [ ] **SDK-CONNECTOR-CONTROL-R054.3:** Connect the inventory gate to both served server fixtures and existing dispatch paths.
- [ ] **SDK-CONNECTOR-CONTROL-R054.4:** Preserve typed refusals and zero backend calls, including destructive confirmation refusal.
- [ ] **SDK-CONNECTOR-CONTROL-R054.5:** Emit canonical receipts and independently reconstruct their parity decisions.
- [ ] **SDK-CONNECTOR-CONTROL-R054.6:** Run the complete served default and explicit-opt-in matrix for every inventory operation.

Runtime work and test execution remain outstanding.
<!-- /spec-definition-patch -->

<!-- spec-definition-patch:sdk-confirmation-r026-1 -->
- [ ] SDK-CONNECTOR-CONTROL-R026.1: Implement protocol-selected confirmation in `ctx_confirm_destructive`. Propagate pending results through generated-method and action dispatch. Keep legacy boolean consumers fail-closed. Run the served acceptance matrix under both protocol eras with a controlled transport. Record exact source, package, and protocol versions. Keep receipts empty until independent review of merged-main evidence.
<!-- /spec-definition-patch -->


## API-key cookie isolation

- [ ] SDK-CONNECTOR-CONTROL-R028.3: Keep API-key identity header-based; do not add cookie-session auth or storage.
- [ ] SDK-CONNECTOR-CONTROL-R028.3: Strip request and response cookies for every API-key status in sync and async clients.
- [ ] SDK-CONNECTOR-CONTROL-R028.3: Prove other auth strategies, transport controls, and downstream cross-caller behavior remain correct.

## Host provider interface and cross-spec producer bindings

- [ ] **SDK-CONNECTOR-CONTROL-R061.1:** Define ProviderPlatformInterface model with service operations and supported platforms.
- [ ] **SDK-CONNECTOR-CONTROL-R061.2:** Provide read-only registry keyed by service, operation and platform.
- [ ] **SDK-CONNECTOR-CONTROL-R061.3:** Wire platform interface into existing host service lifecycle calls.
- [ ] **SDK-CONNECTOR-CONTROL-R061.4:** Refuse unsupported platform, unknown operation and undeclared refusal types.
- [ ] **SDK-CONNECTOR-CONTROL-R061.5:** Record queried service, operation, platform and matched interface digest.
- [ ] **SDK-CONNECTOR-CONTROL-R061.6:** Verify host-management consumer queries platform-native commands correctly for each OS.
- [ ] **SDK-CONNECTOR-CONTROL-R062.1:** Define CertificationAttestation model with decision and AU consumer binding.
- [ ] **SDK-CONNECTOR-CONTROL-R062.2:** EG produces attestation; AU consumes and acts on accepted decisions.
- [ ] **SDK-CONNECTOR-CONTROL-R062.3:** Wire EG producer and AU consumer through existing identity bindings.
- [ ] **SDK-CONNECTOR-CONTROL-R062.4:** Refuse unknown outcome values and missing identity bindings.
- [ ] **SDK-CONNECTOR-CONTROL-R062.5:** Record decision digest, attestation outcome and AU actor/tenant binding.
- [ ] **SDK-CONNECTOR-CONTROL-R062.6:** Verify AU accepts/rejects attestations and seals EG decision trace.
- [ ] **SDK-CONNECTOR-CONTROL-R063.1:** Define EnvironmentDeclaration model with all required field categories.
- [ ] **SDK-CONNECTOR-CONTROL-R063.2:** SDK and AU export immutable declaration sets from component usage census.
- [ ] **SDK-CONNECTOR-CONTROL-R063.3:** Wire public environment_declarations operation into Arbora launcher.
- [ ] **SDK-CONNECTOR-CONTROL-R063.4:** Refuse missing revision, conflicting declarations and unresolved dynamic reads.
- [ ] **SDK-CONNECTOR-CONTROL-R063.5:** Emit EnvironmentDeclarationExport with reproducible declaration digest.
- [ ] **SDK-CONNECTOR-CONTROL-R063.6:** Verify Arbora launcher accepts SDK and AU declaration exports and validates startup.
- [ ] **SDK-CONNECTOR-CONTROL-R064.1:** Define VaultStorageConfig and RootBundleManifest models with propagation matrix.
- [ ] **SDK-CONNECTOR-CONTROL-R064.2:** Guided deployment offers default vault and bundle; components verify every upstream peer.
- [ ] **SDK-CONNECTOR-CONTROL-R064.3:** Wire bundle loading into HTTP client and launcher startup initialization.
- [ ] **SDK-CONNECTOR-CONTROL-R064.4:** Refuse missing vault endpoint, root bundle or failed certificate chain verification.
- [ ] **SDK-CONNECTOR-CONTROL-R064.5:** Record vault endpoint, bundle digest and propagation matrix revision.
- [ ] **SDK-CONNECTOR-CONTROL-R064.6:** Verify guided deployment propagates bundle and startup fails on unverified certificate.
- [ ] **SDK-CONNECTOR-CONTROL-R065.1:** Define ComponentHealthState distinguishing not-configured from configured-but-unavailable.
- [ ] **SDK-CONNECTOR-CONTROL-R065.2:** Unconfigured and disabled components suppress alerts automatically.
- [ ] **SDK-CONNECTOR-CONTROL-R065.3:** Wire health state classification into Arbora /health endpoint and alert evaluation.
- [ ] **SDK-CONNECTOR-CONTROL-R065.4:** Refuse unknown state values and contradictory configuration pairs.
- [ ] **SDK-CONNECTOR-CONTROL-R065.5:** Record component state, configuration status and alert suppression reason.
- [ ] **SDK-CONNECTOR-CONTROL-R065.6:** Verify /health endpoint reports all states and alerts suppress for non-enabled components.
- [ ] **SDK-CONNECTOR-CONTROL-R066.1:** Define ScalingProposal and AppliedScalingState models with strategy choices.
- [ ] **SDK-CONNECTOR-CONTROL-R066.2:** EG generates proposal; Arbora accepts/rejects and records applied state.
- [ ] **SDK-CONNECTOR-CONTROL-R066.3:** Wire EG proposal producer and Arbora capacity consumer with applied-state receipt.
- [ ] **SDK-CONNECTOR-CONTROL-R066.4:** Refuse invalid premises and incompatible strategies without partial application.
- [ ] **SDK-CONNECTOR-CONTROL-R066.5:** Record proposal load/headroom premises, applied instance count and loop closure.
- [ ] **SDK-CONNECTOR-CONTROL-R066.6:** Verify EG generates proposal, Arbora applies it and loop closes on receipt.

## Connector packs authored as Turtle (R067)

- [ ] **SDK-CONNECTOR-CONTROL-R067:** The SDK authors each connector pack as Turtle from typed declarations. Pass the proving test in test-spec.md.
- [ ] **SDK-CONNECTOR-CONTROL-R067.1:** Model. Pass the proving test in test-spec.md.
- [ ] **SDK-CONNECTOR-CONTROL-R067.2:** Behavior. Pass the proving test in test-spec.md.
- [ ] **SDK-CONNECTOR-CONTROL-R067.3:** Behavior. Pass the proving test in test-spec.md.
- [ ] **SDK-CONNECTOR-CONTROL-R067.4:** Behavior. Pass the proving test in test-spec.md.
- [ ] **SDK-CONNECTOR-CONTROL-R067.5:** Wiring. Pass the proving test in test-spec.md.
- [ ] **SDK-CONNECTOR-CONTROL-R067.6:** Refusal. Pass the proving test in test-spec.md.
- [ ] **SDK-CONNECTOR-CONTROL-R067.7:** Evidence. Pass the proving test in test-spec.md.
- [ ] **SDK-CONNECTOR-CONTROL-R067.8:** Hot-path proof. Pass the proving test in test-spec.md.
- [ ] **SDK-CONNECTOR-CONTROL-R068 (rollup):** Each connector serves its seed graph and contract resources for first connect (rollup).
- [ ] **SDK-CONNECTOR-CONTROL-R068.1 (Model):** Add the typed model.
- [ ] **SDK-CONNECTOR-CONTROL-R068.2 (Behavior):** Implement the behavior.
- [ ] **SDK-CONNECTOR-CONTROL-R068.3 (Wiring):** Wire the production call site.
- [ ] **SDK-CONNECTOR-CONTROL-R068.4 (Refusal):** Add the typed refusals.
- [ ] **SDK-CONNECTOR-CONTROL-R068.5 (Evidence):** Emit the evidence.
- [ ] **SDK-CONNECTOR-CONTROL-R068.6 (Hot-path proof):** Add the served hot-path test.
- [ ] **SDK-CONNECTOR-CONTROL-R069 (rollup):** Connector transports are declared contracts per connection protocol (rollup).
- [ ] **SDK-CONNECTOR-CONTROL-R069.1 (Model):** Add the typed model.
- [ ] **SDK-CONNECTOR-CONTROL-R069.2 (Behavior):** Implement the behavior.
- [ ] **SDK-CONNECTOR-CONTROL-R069.3 (Wiring):** Wire the production call site.
- [ ] **SDK-CONNECTOR-CONTROL-R069.4 (Refusal):** Add the typed refusals.
- [ ] **SDK-CONNECTOR-CONTROL-R069.5 (Evidence):** Emit the evidence.
- [ ] **SDK-CONNECTOR-CONTROL-R069.6 (Hot-path proof):** Add the served hot-path test.
- [x] **SDK-CONNECTOR-CONTROL-R780.1:** Actor type, bound to `tests/test_au_helper_parity.py`.
- [x] **SDK-CONNECTOR-CONTROL-R780.2:** Exceptions, bound to `tests/test_au_helper_parity.py`.
- [x] **SDK-CONNECTOR-CONTROL-R780.3:** Governed HTTP client and retry, bound.
- [x] **SDK-CONNECTOR-CONTROL-R780.4:** TLS profile resolution, bound.
- [x] **SDK-CONNECTOR-CONTROL-R780.5:** Value helpers and configuration projection, bound.
- [ ] **SDK-CONNECTOR-CONTROL-R780.6:** Add the remainder helpers.
- [ ] **SDK-CONNECTOR-CONTROL-R780:** Rollup of the helper replacements.
- [ ] **SDK-CONNECTOR-CONTROL-R781:** Training-trajectory recorder helper.
- [ ] **SDK-CONNECTOR-CONTROL-R782:** Message-stream adapters normalize into change envelopes.
