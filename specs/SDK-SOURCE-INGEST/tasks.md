# Tasks: source sync

- [x] Finish the generated-client checkpoint and receipt path. Remove parallel cursor assumptions (SDK-SOURCE-INGEST-R001, SDK-SOURCE-INGEST-R004).
- [x] Implement pure normalized drift classifier, quarantine report, and declared evolution policy (SDK-SOURCE-INGEST-R002, SDK-SOURCE-INGEST-R007).
- [x] Implement proposal-only repair handoff and graph-owned activation proof (SDK-SOURCE-INGEST-R003).
- [x] Port enterprise, document/session/feed, and enrichment adapters through SDK ports (SDK-SOURCE-INGEST-R004–SDK-SOURCE-INGEST-R006).
  - [x] Web-fetch requests-floor backend ported to `agent_connector_sdk.adapters.web_fetch` (HTTP GET via the SDK's own governed client, OG/Twitter Card metadata, tag-strip text normalization) (SDK-SOURCE-INGEST-R005).
  - [x] Web-fetch: ArchiveBox and crawl4ai backends (still call agent-utilities-owned MCP fleet / crawler subprocess infrastructure) (SDK-SOURCE-INGEST-R005).
  - [x] Web-fetch: richer HTML-to-markdown conversion (markitdown or equivalent) in place of the tag-strip floor (SDK-SOURCE-INGEST-R005).
  - [x] Web-fetch: wrapped as `WebFetchSourceAdapter` (`ports.SourceAdapter`), registered via the `agent_connector_sdk.source_adapters` entry-point group; one URL per extracted page, checkpoint-recoverable, reconcile against a fixed URL set (SDK-SOURCE-INGEST-R005).
  - [x] Package-install ingestion and repository-related transport adapters (SDK-SOURCE-INGEST-R005).
- [ ] Record exact merged commit, CI run, fixture results, and graph-backed restart receipt before acceptance.
- [x] Add occurrence/weather adapters (GBIF, iNaturalist, NOAA GHCN/ISD, Open-Meteo, NOAA storm events) and the NCBI/GBIF taxonomy connector validated against `TaxonShape` (SDK-SOURCE-INGEST-R008, SDK-SOURCE-INGEST-R009).
- [ ] Add the ingest worker runner and the `ingest-worker` command; the engine decides admission, lane floors and routing (SDK-SOURCE-INGEST-R010, SDK-SOURCE-INGEST-R011).
- [ ] **R005.1:** Implement and verify paper-source model acceptance (SDK-SOURCE-INGEST-R005.1).
- [ ] **R005.2:** Implement and verify paper-source behavior acceptance (SDK-SOURCE-INGEST-R005.2).
- [ ] **R005.3:** Implement and verify paper-source wiring acceptance (SDK-SOURCE-INGEST-R005.3).
- [ ] **R005.4:** Implement and verify paper-source refusal acceptance (SDK-SOURCE-INGEST-R005.4).
- [ ] **R005.5:** Implement and verify paper-source evidence acceptance (SDK-SOURCE-INGEST-R005.5).
- [ ] **R005.6:** Implement and verify paper-source hot-path proof acceptance (SDK-SOURCE-INGEST-R005.6).

- [ ] **SDK-SOURCE-INGEST-R012:** Platform read/search fallback and observed backend status.
- [ ] **SDK-SOURCE-INGEST-R012.1:** Model.
- [ ] **SDK-SOURCE-INGEST-R012.2:** Behavior.
- [ ] **SDK-SOURCE-INGEST-R012.3:** Wiring.
- [ ] **SDK-SOURCE-INGEST-R012.4:** Refusal.
- [ ] **SDK-SOURCE-INGEST-R012.5:** Evidence.
- [ ] **SDK-SOURCE-INGEST-R012.6:** Hot-path proof.

## Concurrent stage resume

- [ ] `SDK-SOURCE-INGEST-R001.1`: implement and prove model for concurrent stage resume.
- [ ] `SDK-SOURCE-INGEST-R001.2`: implement and prove behavior for concurrent stage resume.
- [ ] `SDK-SOURCE-INGEST-R001.3`: implement and prove wiring for concurrent stage resume.
- [ ] `SDK-SOURCE-INGEST-R001.4`: implement and prove refusal for concurrent stage resume.
- [ ] `SDK-SOURCE-INGEST-R001.5`: implement and prove evidence for concurrent stage resume.
- [ ] `SDK-SOURCE-INGEST-R001.6`: implement and prove hot-path proof for concurrent stage resume.

## Native SQL source execution

- [ ] `SDK-SOURCE-INGEST-R004.1`: implement and prove model for native sql source execution.
- [ ] `SDK-SOURCE-INGEST-R004.2`: implement and prove behavior for native sql source execution.
- [ ] `SDK-SOURCE-INGEST-R004.3`: implement and prove wiring for native sql source execution.
- [ ] `SDK-SOURCE-INGEST-R004.4`: implement and prove refusal for native sql source execution.
- [ ] `SDK-SOURCE-INGEST-R004.5`: implement and prove evidence for native sql source execution.
- [ ] `SDK-SOURCE-INGEST-R004.6`: implement and prove hot-path proof for native sql source execution.

## Offline bookmark import

- [ ] `SDK-SOURCE-INGEST-R005.7`: implement and prove model for offline bookmark import.
- [ ] `SDK-SOURCE-INGEST-R005.8`: implement and prove behavior for offline bookmark import.
- [ ] `SDK-SOURCE-INGEST-R005.9`: implement and prove wiring for offline bookmark import.
- [ ] `SDK-SOURCE-INGEST-R005.10`: implement and prove refusal for offline bookmark import.
- [ ] `SDK-SOURCE-INGEST-R005.11`: implement and prove evidence for offline bookmark import.
- [ ] `SDK-SOURCE-INGEST-R005.12`: implement and prove hot-path proof for offline bookmark import.

## Chain transaction-log decoding

- [ ] `SDK-SOURCE-INGEST-R005.13`: implement and prove model for chain transaction-log decoding.
- [ ] `SDK-SOURCE-INGEST-R005.14`: implement and prove behavior for chain transaction-log decoding.
- [ ] `SDK-SOURCE-INGEST-R005.15`: implement and prove wiring for chain transaction-log decoding.
- [ ] `SDK-SOURCE-INGEST-R005.16`: implement and prove refusal for chain transaction-log decoding.
- [ ] `SDK-SOURCE-INGEST-R005.17`: implement and prove evidence for chain transaction-log decoding.
- [ ] `SDK-SOURCE-INGEST-R005.18`: implement and prove hot-path proof for chain transaction-log decoding.

## Parallel workspace document reads

- [ ] `SDK-SOURCE-INGEST-R005.19`: implement and prove model for parallel workspace document reads.
- [ ] `SDK-SOURCE-INGEST-R005.20`: implement and prove behavior for parallel workspace document reads.
- [ ] `SDK-SOURCE-INGEST-R005.21`: implement and prove wiring for parallel workspace document reads.
- [ ] `SDK-SOURCE-INGEST-R005.22`: implement and prove refusal for parallel workspace document reads.
- [ ] `SDK-SOURCE-INGEST-R005.23`: implement and prove evidence for parallel workspace document reads.
- [ ] `SDK-SOURCE-INGEST-R005.24`: implement and prove hot-path proof for parallel workspace document reads.

## Incremental repository indexing

- [ ] `SDK-SOURCE-INGEST-R004.13`: implement and prove model for incremental repository indexing.
- [ ] `SDK-SOURCE-INGEST-R004.14`: implement and prove behavior for incremental repository indexing.
- [ ] `SDK-SOURCE-INGEST-R004.15`: implement and prove wiring for incremental repository indexing.
- [ ] `SDK-SOURCE-INGEST-R004.16`: implement and prove refusal for incremental repository indexing.
- [ ] `SDK-SOURCE-INGEST-R004.17`: implement and prove evidence for incremental repository indexing.
- [ ] `SDK-SOURCE-INGEST-R004.18`: implement and prove hot-path proof for incremental repository indexing.
- [ ] `SDK-SOURCE-INGEST-R004.19`: implement and prove model for declared connector sources.
- [ ] `SDK-SOURCE-INGEST-R004.20`: implement and prove behavior for declared connector sources.
- [ ] `SDK-SOURCE-INGEST-R004.21`: implement and prove wiring for declared connector sources.
- [ ] `SDK-SOURCE-INGEST-R004.22`: implement and prove refusal for declared connector sources.
- [ ] `SDK-SOURCE-INGEST-R004.23`: implement and prove evidence for declared connector sources.
- [ ] `SDK-SOURCE-INGEST-R004.24`: implement and prove hot-path proof for declared connector sources.
- [ ] `SDK-SOURCE-INGEST-R004.25`: implement and prove pack mapping for declared connector sources.

## Scheduled paper sourcing (R005.25-R005.30)

- [ ] `SDK-SOURCE-INGEST-R005.25`: implement and prove model for scheduled paper sourcing.
- [ ] `SDK-SOURCE-INGEST-R005.26`: implement and prove behavior for scheduled paper sourcing.
- [ ] `SDK-SOURCE-INGEST-R005.27`: implement and prove wiring for scheduled paper sourcing.
- [ ] `SDK-SOURCE-INGEST-R005.28`: implement and prove refusal for scheduled paper sourcing.
- [ ] `SDK-SOURCE-INGEST-R005.29`: implement and prove evidence for scheduled paper sourcing.
- [ ] `SDK-SOURCE-INGEST-R005.30`: implement and prove hot-path proof for scheduled paper sourcing.

## Citation-edge paper extraction (R005.31-R005.36)

- [ ] `SDK-SOURCE-INGEST-R005.31`: implement and prove model for citation-edge paper extraction.
- [ ] `SDK-SOURCE-INGEST-R005.32`: implement and prove behavior for citation-edge paper extraction.
- [ ] `SDK-SOURCE-INGEST-R005.33`: implement and prove wiring for citation-edge paper extraction.
- [ ] `SDK-SOURCE-INGEST-R005.34`: implement and prove refusal for citation-edge paper extraction.
- [ ] `SDK-SOURCE-INGEST-R005.35`: implement and prove evidence for citation-edge paper extraction.
- [ ] `SDK-SOURCE-INGEST-R005.36`: implement and prove hot-path proof for citation-edge paper extraction.

## Document sources moved from agent-utilities (R005.37-R005.39)

- [x] `SDK-SOURCE-INGEST-R005.37`: git-markdown domain packs with lineage and diff-based re-ingest.
- [x] `SDK-SOURCE-INGEST-R005.38`: filesystem document source with a live ingestion path.
- [x] `SDK-SOURCE-INGEST-R005.39`: governed document ingest applies the permission envelope before embedding.

## Interchangeable enterprise operations

- [ ] `SDK-SOURCE-INGEST-R006.32`: implement and prove model for interchangeable enterprise operations.
- [ ] `SDK-SOURCE-INGEST-R006.33`: implement and prove behavior for interchangeable enterprise operations.
- [ ] `SDK-SOURCE-INGEST-R006.34`: implement and prove wiring for interchangeable enterprise operations.
- [ ] `SDK-SOURCE-INGEST-R006.35`: implement and prove refusal for interchangeable enterprise operations.
- [ ] `SDK-SOURCE-INGEST-R006.36`: implement and prove evidence for interchangeable enterprise operations.
- [ ] `SDK-SOURCE-INGEST-R006.37`: implement and prove hot-path proof for interchangeable enterprise operations.

## Paper throughput and purge policy (R015)

- [ ] `SDK-SOURCE-INGEST-R015`: obtain EG decision authority and purge policy definitions.
- [ ] `SDK-SOURCE-INGEST-R015.1`: implement and prove model for paper throughput decision and durable purge obligation.
- [ ] `SDK-SOURCE-INGEST-R015.2`: implement and prove behavior for paper throughput decision and durable purge obligation.
- [ ] `SDK-SOURCE-INGEST-R015.3`: implement and prove wiring for paper throughput decision and durable purge obligation.
- [ ] `SDK-SOURCE-INGEST-R015.4`: implement and prove refusal for paper throughput decision and durable purge obligation.
- [ ] `SDK-SOURCE-INGEST-R015.5`: implement and prove evidence for paper throughput decision and durable purge obligation.
- [ ] `SDK-SOURCE-INGEST-R015.6`: implement and prove hot-path proof for paper throughput decision and durable purge obligation.

## Media vision enrichment (R016)

- [ ] `SDK-SOURCE-INGEST-R016`: identify the vision producer and define the media enrichment contract.
- [ ] `SDK-SOURCE-INGEST-R016.1`: implement and prove model for media vision enrichment.
- [ ] `SDK-SOURCE-INGEST-R016.2`: implement and prove behavior for media vision enrichment.
- [ ] `SDK-SOURCE-INGEST-R016.3`: implement and prove wiring for media vision enrichment.
- [ ] `SDK-SOURCE-INGEST-R016.4`: implement and prove refusal for media vision enrichment.
- [ ] `SDK-SOURCE-INGEST-R016.5`: implement and prove evidence for media vision enrichment.
- [ ] `SDK-SOURCE-INGEST-R016.6`: implement and prove hot-path proof for media vision enrichment.

## Approved query receiving contract

- [ ] `SDK-SOURCE-INGEST-R004.7`: implement and prove model for the generated approval receiver.
- [ ] `SDK-SOURCE-INGEST-R004.8`: implement and prove behavior for the generated approval receiver.
- [ ] `SDK-SOURCE-INGEST-R004.9`: implement and prove wiring for the generated approval receiver.
- [ ] `SDK-SOURCE-INGEST-R004.10`: implement and prove refusal for the generated approval receiver.
- [ ] `SDK-SOURCE-INGEST-R004.11`: implement and prove evidence for the generated approval receiver.
- [ ] `SDK-SOURCE-INGEST-R004.12`: implement and prove hot-path proof for the generated approval receiver.
- [ ] `SDK-SOURCE-INGEST-R004.28`: implement and prove per-parent fan-out (`for_each`) for declared connector sources.

<!-- spec-definition-patch:webui-3-10-source-definition-20261012 -->
## Supported-harness session sync (R013; WEBUI:3)

- [ ] **SDK-SOURCE-INGEST-R013:** Obtain the owner-approved complete harness/source manifest and exact EG/Arbora IDs. Keep work blocked until owners register every source operation.
- [ ] **SDK-SOURCE-INGEST-R013.1:** Define the versioned manifest and refuse unbound operations before source calls.
- [ ] **SDK-SOURCE-INGEST-R013.2:** Prove complete first-run coverage, retry deduplication, restart resume, and visible per-source partial denial.
- [ ] **SDK-SOURCE-INGEST-R013.3:** Wire connector-sync --once/McpToolSourceAdapter to generated SourceIngest and the approved Arbora consumer.
- [ ] **SDK-SOURCE-INGEST-R013.4:** Prove typed denial, zero unauthorized calls, no tenant leakage, and no denied-source cursor advance.
- [ ] **SDK-SOURCE-INGEST-R013.5:** Persist and independently read back manifest-, identity-, revision-, cursor-, outcome-, and graph-receipt-bound evidence.
- [ ] **SDK-SOURCE-INGEST-R013.6:** Exercise every approved entry through served discovery, EG readback, and WEBUI-APPS-R006.4; record full coverage.

## Live meeting and summary transport (R014; WEBUI:10)

- [ ] **SDK-SOURCE-INGEST-R014:** Obtain the real meeting operation/repository and exact EG/Arbora/provider IDs; preserve single-shot dictation and leave unbound operations unresolved.
- [ ] **SDK-SOURCE-INGEST-R014.1:** Define closed event/provider fields and distinguish exact receipt-bound replay from conflicting duplicate payload/revision.
- [ ] **SDK-SOURCE-INGEST-R014.2:** Specify bounded ordered partial ingestion, idempotent replay, newer-revision corrections, and complete-sequence finalization.
- [ ] **SDK-SOURCE-INGEST-R014.3:** Bind the owner-registered meeting operation through real SDK dispatch, EG transcript authority, and Arbora selection.
- [ ] **SDK-SOURCE-INGEST-R014.4:** Prove gaps block finalization. Prove complete sequences finalize and issue bound receipts. Prove summary dispatch without that receipt refuses with zero provider effects.
- [ ] **SDK-SOURCE-INGEST-R014.5:** Persist redacted provenance bound to final transcript, provider revisions, authorization, and invocation receipt.
- [ ] **SDK-SOURCE-INGEST-R014.6:** Test partial -> correction -> complete finalization with zero premature summary calls, plus independent local/hosted selection and refusals.
<!-- /spec-definition-patch -->

## Ingest under an accepted contract (R017)

- [ ] **SDK-SOURCE-INGEST-R017:** Source ingest runs only under an engine-accepted ingest contract. Pass the proving test in test-spec.md.
- [ ] **SDK-SOURCE-INGEST-R017.1:** Model. Pass the proving test in test-spec.md.
- [ ] **SDK-SOURCE-INGEST-R017.2:** Behavior. Pass the proving test in test-spec.md.
- [ ] **SDK-SOURCE-INGEST-R017.3:** Wiring. Pass the proving test in test-spec.md.
- [ ] **SDK-SOURCE-INGEST-R017.4:** Refusal. Pass the proving test in test-spec.md.
- [ ] **SDK-SOURCE-INGEST-R017.5:** Evidence. Pass the proving test in test-spec.md.
- [ ] **SDK-SOURCE-INGEST-R017.6:** Hot-path proof. Pass the proving test in test-spec.md.

## Web-source fetch contract (R005.40)

- [ ] **SDK-SOURCE-INGEST-R005.40:** Web-source fetch contract. `.1` (model and tool registration) and `.2` (obligations and conformance kit) are delivered; `.3` to `.6` (adapter wiring, refusal, evidence, served proof) remain.
- [ ] **SDK-SOURCE-INGEST-R005.40.1:** Model. Add the request, result and refusal types.
- [ ] **SDK-SOURCE-INGEST-R005.40.2:** Behavior. Add the conformance kit for the five obligations.
- [ ] **SDK-SOURCE-INGEST-R005.40.3:** Wiring. Route the adapter through the connector tool.
- [ ] **SDK-SOURCE-INGEST-R005.40.4:** Refusal. Return typed refusals and keep the checkpoint.
- [ ] **SDK-SOURCE-INGEST-R005.40.5:** Evidence. Map the record provenance onto the engine model.
- [ ] **SDK-SOURCE-INGEST-R005.40.6:** Hot-path proof. Add the served two-connector test.
- [ ] **SDK-SOURCE-INGEST-R005.41:** Refuse failed legacy fetches before the runner advances the checkpoint.
- [x] **SDK-SOURCE-INGEST-R005.42:** Pin legacy fetch egress and refuse private targets without an explicit host allowlist.
- [x] `SDK-SOURCE-INGEST-R004.26` — Citable public URL fields kept by the persistence guard.
- [x] `SDK-SOURCE-INGEST-R004.27` — Pass the operator's mass-withdrawal decision through the sink.

- [ ] **SDK-SOURCE-INGEST-R805:** Source access, enumeration and hierarchy contract (rollup).
- [ ] **SDK-SOURCE-INGEST-R805.1:** Permission and group sync.
- [ ] **SDK-SOURCE-INGEST-R805.2:** Identifier enumeration.
- [ ] **SDK-SOURCE-INGEST-R805.3:** Container hierarchy.
- [ ] **SDK-SOURCE-INGEST-R805.4:** Wiring.
- [ ] **SDK-SOURCE-INGEST-R805.5:** Read-time access lookup port.
- [ ] **SDK-SOURCE-INGEST-R805.6:** Hot-path proof.
- [x] `SDK-SOURCE-INGEST-R004.29`: load declarations as typed data with shared field sets.
- [x] `SDK-SOURCE-INGEST-R004.30`: declared record mappers (`RecordMap`, `Mapped`) and shared field validation.
- [x] `SDK-SOURCE-INGEST-R004.31`: `SourceStream` entry with paging and cursor checkpointing.
- [x] `SDK-SOURCE-INGEST-R004.32`: best-effort, split-stream, media and mixed submissions.
- [x] `SDK-SOURCE-INGEST-R004.33`: cursor strategies on `sync` and batched commits.
- [x] `SDK-SOURCE-INGEST-R004.34`: projection, guard and size limit inside `submit`.
- [x] `SDK-SOURCE-INGEST-R004.35`: ingest tools declared as data.
- [x] `SDK-SOURCE-INGEST-R004.36`: declared source edges (owner, steward, assignment references).

## Batch D source-contract verification (2026-10-26)

The grouped Batch D suite and independent storage review verify these leaves.
Each row binds to the cited assertion through `pytest.mark.spec`.

- [x] **SDK-SOURCE-INGEST-R600.2:** Record live write change-set audit and receipt. (`tests/test_writeback_sinks.py::test_live_write_records_change_set_audit_and_receipt`)
- [x] **SDK-SOURCE-INGEST-R800.1:** List built-in sources and reject unknown registry entries. (`tests/source_connectors/test_source_connectors.py::test_registry_lists_builtin_sources_and_rejects_unknown`)
- [x] **SDK-SOURCE-INGEST-R800.3:** Crawl a web connector to bounded depth and poll incrementally. (`tests/source_connectors/test_source_connectors.py::test_web_connector_crawls_to_depth_and_polls_incrementally`)
- [x] **SDK-SOURCE-INGEST-R800.5:** Round-trip checkpoints and reject malformed checkpoint input. (`tests/source_connectors/test_source_connectors.py::test_checkpoint_round_trips_and_bad_input_is_none`)
- [x] **SDK-SOURCE-INGEST-R803.1:** Enforce the strict data-preparation plan gate. (`tests/data_prep/test_kernel.py::test_plan_gate_is_strict_and_allowlisted`)
- [x] **SDK-SOURCE-INGEST-R803.2:** Replay deterministically without mutating the plan. (`tests/data_prep/test_kernel.py::test_replay_is_deterministic_and_plan_is_not_mutated`)
- [x] **SDK-SOURCE-INGEST-R803.3:** Import certification without loading optional provider runtimes. (`tests/data_prep/certification/test_job.py::test_optional_provider_wrappers_are_lazy_and_do_not_run_without_provider`)
- [x] **SDK-SOURCE-INGEST-R803.4:** Deny lossy casts and allow safe lossless widening. (`tests/data_prep/test_kernel.py::test_lossy_casts_are_denied_and_lossless_widening_uses_safe_cast`)
- [x] **SDK-SOURCE-INGEST-R803.5:** Keep below-threshold values out of profiles and serialized output. (`tests/data_prep/test_profiling.py::test_below_threshold_values_never_appear_in_top_k_or_serialized_profile`)
- [x] **SDK-SOURCE-INGEST-R804.1:** Require immutable, digest-pinned voice manifests. (`tests/voice_supply_chain/test_voice_supply_chain.py::test_manifest_normalizes_digest_case_and_defaults_are_fail_closed`)
- [x] **SDK-SOURCE-INGEST-R804.3:** Persist verification and refuse rejected assets. (`tests/voice_supply_chain/test_voice_supply_chain.py::test_mark_verified_persists_and_refuses_rejected`)
- [x] **SDK-SOURCE-INGEST-R804.5:** Require approved license and verified asset for promotion. (`tests/voice_supply_chain/test_voice_supply_chain.py::test_promotion_handoff_requires_approved_license_and_verified_asset`)
- [x] **SDK-SOURCE-INGEST-R804.7:** Bind stored decisions to safe manifest identifiers and refuse traversal before file access.
- [x] **SDK-SOURCE-INGEST-R804.6:** Round-trip one thousand license decisions and count reads for each lookup.
- [x] **SDK-SOURCE-INGEST-R900.1:** Expose an irreversible identity reference for source connections. (`tests/source_connectors/test_universal.py::test_identity_is_an_irreversible_reference`)
- [x] **SDK-SOURCE-INGEST-R900.2:** Advance database polling watermarks idempotently. (`tests/source_connectors/test_database.py::test_poll_advances_the_watermark_and_is_idempotent`)
- [x] **SDK-SOURCE-INGEST-R900.5:** Emit schema entities without leaking the connection location. (`tests/source_connectors/test_universal.py::test_introspect_emits_schema_entities_without_the_location`)
- [x] **SDK-SOURCE-INGEST-R901.1:** Emit governed hierarchy entities idempotently. (`tests/source_connectors/test_graphql_document.py::test_hierarchy_poll_emits_governed_entities_and_is_idempotent`)
- [x] **SDK-SOURCE-INGEST-R901.5:** Report dry-run counts without source details. (`tests/source_connectors/test_graphql_document.py::test_dry_run_plan_reports_counts_only`)
- [x] **SDK-SOURCE-INGEST-R902.1:** Produce neutral-metadata documents from explicit mappings. (`tests/source_connectors/test_mcp_package.py::test_explicit_mapping_yields_documents_with_neutral_metadata`)
- [x] **SDK-SOURCE-INGEST-R902.4:** Refuse prohibited stdio transport. (`tests/source_connectors/test_mcp_package.py::test_stdio_is_refused_when_prohibited`)
- [x] **SDK-SOURCE-INGEST-R902.5:** Resolve servers by declared names only. (`tests/source_connectors/test_mcp_package.py::test_server_resolution_uses_declared_names_only`)

## SDK source-wiring follow-up (2026-10-26)

These focused tests exercise the existing production resolver paths. They do
not change generated status; owner review and the normal status generator are
required before promotion.

- [ ] **SDK-SOURCE-INGEST-R900.3:** Prove database profile resolution reaches the TLS-governed network connection. (`tests/source_connectors/test_database.py::test_database_profile_resolution_reaches_the_tls_governed_connection`)
- [ ] **SDK-SOURCE-INGEST-R902.3:** Prove MCP catalog loading falls back to the platform config path when `MCP_CONFIG` is unset. (`tests/source_connectors/test_mcp_package.py::test_mcp_catalog_falls_back_to_the_platform_config_file`)

## SDK default source wiring follow-up (2026-10-26)

This focused test exercises the existing secret, egress and TLS resolver paths
from a secret-backed GraphQL profile. The row remains open until the test is
reviewed, landed and regenerated into canonical status.

- [ ] **SDK-SOURCE-INGEST-R901.3:** Prove the default GraphQL profile resolver, governed source URL validation and TLS profile are used for a real document load. (`tests/source_connectors/test_graphql_document.py::test_default_graphql_wiring_uses_sdk_resolvers`)

## SDK writeback contract follow-up (2026-10-26)

These focused tests exercise the existing governed writeback boundary and
close the identifier and engine-operand proof gaps. The R600.5 follow-up keeps
uncertain sink failures bound to the durable attempt identity. It exposes the
same `governed_writeback` evidence on timeout and cancellation manifests.

- [ ] **SDK-SOURCE-INGEST-R600.1:** Validate governed writeback identifiers and expose the typed invocation contract. (`tests/test_writeback_sinks.py::test_writeback_contract_validates_ids_and_exposes_typed_invocation`)
- [ ] **SDK-SOURCE-INGEST-R600.3:** Route graph-engine preflight and approval-queue operands through the single SDK entry point without harness imports or duplicate callers. (`tests/test_writeback_sinks.py::test_writeback_wiring_uses_preflight_and_approval_queue`; `tests/test_writeback_sinks.py::test_writeback_package_has_no_harness_import_or_duplicate_entrypoint`)
- [ ] **SDK-SOURCE-INGEST-R600.5:** Carry change-set, authorization and uncertain effect evidence on sink failure manifests while preserving the durable no-replay identity. (`tests/test_writeback_sinks.py::test_sink_failure_manifest_binds_uncertain_evidence_after_preflight`; `tests/test_writeback_sinks.py::test_timeout_and_cancelled_sink_failures_remain_uncertain`)
# Concurrent stage model

- [x] Validate stage identities, limits and dependencies at target construction (SDK-SOURCE-INGEST-R001.1). Refuse stage execution until the concurrent runner is wired.
