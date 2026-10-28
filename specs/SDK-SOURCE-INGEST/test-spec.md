# Test specification: source sync

| ID | Setup | Required assertion |
|---|---|---|
| SI-01 | Two pages from synthetic adapter, fake generated client | First `None` checkpoint then exact accepted checkpoint. Next page sees updated checkpoint only after receipt. |
| SI-02 | Timeout or ambiguous commit reply | Runner reads durable status and retries with same idempotency identity; no double advance. |
| SI-03 | Tenant/source/stream/manifest mismatch in receipt | Fail closed; no checkpoint advance or cross-tenant reuse. |
| SI-04 | Add optional field under declared compatible policy | Stable normalized digest/classification; accepted page proceeds. |
| SI-05 | Remove required field, change identifier type, add unknown enum, or change nested type | `REQUIRES_REVIEW` or `BREAKING` report. Page quarantined before sink. No checkpoint advance. |
| SI-06 | Approved candidate repair | Graph-owned candidate validation and shadow ingest precede activation; denial or failed shadow keeps old contract active. |
| SI-07 | Representative enterprise, document/feed and enrichment fixtures | Each adapter passes discovery, pagination, duplicate delivery, deletions, rate-limit and secret-redaction cases. |
| SI-08 | Restart after one accepted and one quarantined page against a contributor-owned graph | Accepted cursor resumes exactly once. Quarantined page remains replayable. Redacted receipts bind identities. |

Run offline focused pytest, Ruff, mypy, CCCC, Dupehound, KISS, and wiring checks on every source PR. SI-08 is an opt-in acceptance probe. Without a graph endpoint, cloud PRs must report that the probe did not run.


## Paper-provider acceptance

The planned module is `tests/test_paper_source_served.py`; its cases bind R005.1 through R005.6.

| ID | Setup | Required assertion |
|---|---|---|
| SI-09 | Construct query, provider report, record and receipt models. | Unknown values, missing identities, invalid bounds and mismatched tenant refuse. |
| SI-10 | Two independent providers return the same DOI/revision and conflicting fields; a third fails. | One merged record preserves both sources and conflicts. Declared precedence ignores response order. Failure remains visible and result is partial. |
| SI-11 | Call registered connector search and download operations over MCP, then run the certified sync entry point. | The real caller reaches the shared contract, governed HTTP and generated SourceIngest with the pinned schema. |
| SI-12 | Exercise authentication, malformed input, provider failure, quotas, deadline, unsafe redirects, storage escape, media, size, integrity and parsing failures. | Each typed refusal reaches the caller. All-provider failure is failed. No unauthorized request, complete partial artifact or failed-stream checkpoint advance occurs. |
| SI-13 | Retry the same query and download; then change bytes for the same paper ID. | Identity and provenance remain deterministic. Same bytes reuse the artifact; changed bytes get a new digest. Credentials and private paths never appear. |
| SI-14 | Run `test_served_search_download_and_sync` with real MCP and controlled provider HTTP servers plus a running graph. | Observe original file bytes, merged fields and provider errors. Read back accepted graph records and checkpoints after restart. Failed providers remain retryable without duplicate healthy ingestion. |

Provider fixtures must include HTTP 429 with Retry-After and observed request timestamps.
Concurrent search and download calls must share the declared quota; no request may escape through another operation.
Test missing content metadata with a document containing a located title and author, then a malformed document.
Test truncated content, misleading HTML login responses, unsupported media, cross-host redirects and interrupted downloads.
Assert temporary files are removed and published documents match the recorded digest byte for byte.
Record exact revision, connector registration, commands, provider requests and redacted graph receipts for the served acceptance run.
Specification checks alone do not satisfy these runtime acceptance requirements.


## Platform fallback acceptance

The planned module is `tests/test_platform_fallback_served.py`; cases bind SDK-SOURCE-INGEST-R012.1 through R012.6.

| ID | Input | Required assertion |
|---|---|---|
| SI-15 | Separate read/search inventories; malformed request or policy. | Reject unknown fields, duplicate backends, incompatible authority, unbounded policy and wrong continuation binding. |
| SI-16 | First backend returns 503, next returns valid records; repeat with empty valid search. | Ordered bounded attempts select the second backend. Empty success stops the chain. Status distinguishes degraded and healthy results. |
| SI-17 | A real registered connector serves read/search/status through SDK tools/call. | The production dispatch_async calls the shared composition, governed HTTP and receiving MCP client. Trace their request identities. |
| SI-18 | All backends fail, none configured, unsupported operation, denied scope, 429, TLS failure or cancellation. | Return the exact typed terminal reason. Unsupported and unauthorized requests generate zero backend calls. No failed page advances a checkpoint. |
| SI-19 | Concurrent tenants, expired observations, signed URLs and secret-bearing upstream failures. | Status remains scoped and expires to unknown. Client results and logs retain safe provenance without credentials, raw queries or private URLs. |
| SI-20 | test_served_dispatch_fallback_and_status uses a real SDK server and two controlled local HTTP servers. | First fails and second succeeds; client sees ordered attempts, winning backend and subsequent status. All-failed and denied calls prove refusal through the same dispatcher. |

Start the SDK server with synthetic authenticated scopes, a certified connector registrar and fixed backend order.
Call its read/search tool over the MCP tools/call wire method. Helper calls or mocked dispatch_async cannot prove acceptance.
Local HTTP servers record request counts and monotonic timestamps. Inject two first-backend failures before the second returns valid data.
Assert the client receives two failed attempts followed by one success, the second backend ID and degraded channel status.
Call the registered status action and compare its backend, policy revision, observation time and tenant to the result.
Then make both backends fail. Assert chain_exhausted, null selected backend and no records; refuse an empty successful list.
Test no_backend separately from unsupported_capability, with no HTTP requests in either case.
Remove caller scope and assert unauthorized before dispatch; repeat with another tenant and assert no status or credential leakage.
Exercise HTTP 429, Retry-After, request deadline, cancellation and transport retries together; total observed calls never exceed the configured budget.
Test a valid empty search, malformed successful HTTP body, forbidden redirect, stale status and backend-specific continuation.
For the source path, pass a typed refusal through McpToolSourceAdapter.extract and assert no accepted RecordPage or checkpoint advance.
Record served requests, actual backend traces, schema/policy revisions and redacted client responses for each operation independently.
No live platform account is required. These integration tests have not run. They require implementation and served integration acceptance.

## Concurrent stage resume

The planned module is `tests/test_source_stages_served.py`. Runtime acceptance remains unexecuted.

| Requirement | Case | Required assertion |
|---|---|---|
| `SDK-SOURCE-INGEST-R001.1` | Model | Reject duplicate streams, cycles, missing authority and unbounded concurrency before extraction. |
| `SDK-SOURCE-INGEST-R001.2` | Behavior | Overlap two independent stages; preserve dependency order when one stage fails. |
| `SDK-SOURCE-INGEST-R001.3` | Wiring | Enter connector-sync --once; observe worker execution, generated status reads and accepted commits. |
| `SDK-SOURCE-INGEST-R001.4` | Refusal | Inject scope mismatch, timeout after commit, cancellation and failed dependencies; require no skipped or duplicate accepted records. |
| `SDK-SOURCE-INGEST-R001.5` | Evidence | Compare reports with durable status after restart and check redaction. |
| `SDK-SOURCE-INGEST-R001.6` | Hot-path proof | Prove overlapping requests, exact resume boundaries, no refetch of accepted events and no duplicate durable effects. |

## Native SQL source execution

The planned module is `tests/test_sql_source_served.py`. Runtime acceptance remains unexecuted.

| Requirement | Case | Required assertion |
|---|---|---|
| `SDK-SOURCE-INGEST-R004.1` | Model | Validate parameter types, dialect, limits, snapshot and authority before database calls. |
| `SDK-SOURCE-INGEST-R004.2` | Behavior | Run parameterized native SQL; measure memory across increasing row counts under unchanged limits. |
| `SDK-SOURCE-INGEST-R004.3` | Wiring | Trace tools/call to the real driver and connector-sync to generated receipts without mocking dispatch. |
| `SDK-SOURCE-INGEST-R004.4` | Refusal | Inject failure after three chunks; require visible failure, closed database handle and no silent partial success. |
| `SDK-SOURCE-INGEST-R004.5` | Evidence | Match chunk bounds and receipts to the query; check redaction on success and failure. |
| `SDK-SOURCE-INGEST-R004.6` | Hot-path proof | Require correct rows, native parameter binding, bounded memory, terminal failure and durable checkpoint agreement. |

## Offline bookmark import

The planned module is `tests/test_bookmark_source_served.py`. Runtime acceptance remains unexecuted.

| Requirement | Case | Required assertion |
|---|---|---|
| `SDK-SOURCE-INGEST-R005.7` | Model | Validate identities, supported export shapes and local vocabulary revision. |
| `SDK-SOURCE-INGEST-R005.8` | Behavior | Import duplicate and unknown-domain fixtures; require stable IDs, deterministic metadata and zero network or model requests. |
| `SDK-SOURCE-INGEST-R005.9` | Wiring | Enter connector-sync --once with on-disk JSON; observe discovery, extraction and generated ingestion. |
| `SDK-SOURCE-INGEST-R005.10` | Refusal | Prove visible failures, zero outbound calls and unchanged checkpoints for malformed input and path escapes. |
| `SDK-SOURCE-INGEST-R005.11` | Evidence | Read accepted provenance from the graph and reproduce metadata from identical bytes. |
| `SDK-SOURCE-INGEST-R005.12` | Hot-path proof | Assert exact metadata, zero external-service attempts, stable reimport and no advancement for rejected pages. |

## Chain transaction-log decoding

The planned module is `tests/test_chain_source_served.py`. Runtime acceptance remains unexecuted.

| Requirement | Case | Required assertion |
|---|---|---|
| `SDK-SOURCE-INGEST-R005.13` | Model | Validate chain, contract, signature, decoder revision and exact numeric representation without float rounding. |
| `SDK-SOURCE-INGEST-R005.14` | Behavior | Decode known logs into exact typed trades; preserve identity across duplicate delivery. |
| `SDK-SOURCE-INGEST-R005.15` | Wiring | Trace registered tools/call through governed HTTP to a controlled JSON-RPC endpoint and generated ingestion. |
| `SDK-SOURCE-INGEST-R005.16` | Refusal | Inject malformed logs, RPC errors, wrong identity and changed block hashes; require visible rejection and zero invalid durable trades. |
| `SDK-SOURCE-INGEST-R005.17` | Evidence | Compare graph readback with RPC requests and decoder input digests; check redaction. |
| `SDK-SOURCE-INGEST-R005.18` | Hot-path proof | Observe bounded ranges, exact trades, rejection reports and durable checkpoint refusal. |

## Parallel workspace document reads

The planned module is `tests/test_workspace_read_served.py`. Runtime acceptance remains unexecuted.

| Requirement | Case | Required assertion |
|---|---|---|
| `SDK-SOURCE-INGEST-R005.19` | Model | Validate formats and bounds; visibly refuse unsupported legacy or undeclared formats. |
| `SDK-SOURCE-INGEST-R005.20` | Behavior | Read all five format families from one folder; measure overlap and bounds while preserving bytes and locations. |
| `SDK-SOURCE-INGEST-R005.21` | Wiring | Trace real tools/call into on-disk parsers and certified sync into generated ingestion. |
| `SDK-SOURCE-INGEST-R005.22` | Refusal | Test unsupported suffix, mismatched magic, broken documents, parser absence, escape and cancellation beside successful files. |
| `SDK-SOURCE-INGEST-R005.23` | Evidence | Compare before/after hashes; match graph provenance to successful files. |
| `SDK-SOURCE-INGEST-R005.24` | Hot-path proof | Require exact locations, bounded peak tasks, immutable inputs and independent checkpoint behavior for failed files. |

## Interchangeable enterprise operations

The planned module is `tests/test_enterprise_adapters_served.py`. Runtime acceptance remains unexecuted.

| Requirement | Case | Required assertion |
|---|---|---|
| `SDK-SOURCE-INGEST-R006.32` | Model | Validate common schemas and distinguish unsupported operations from empty successful reads. |
| `SDK-SOURCE-INGEST-R006.33` | Behavior | Swap two separately registered connectors without changing workflow requests or result handling; compare normalized outcomes. |
| `SDK-SOURCE-INGEST-R006.34` | Wiring | Enter both connectors through tools/call; trace backend requests and governed effects. |
| `SDK-SOURCE-INGEST-R006.35` | Refusal | Request unsupported operations and denied writes; assert typed reasons and zero effects. |
| `SDK-SOURCE-INGEST-R006.36` | Evidence | Compare connector receipts against identical workflow contracts; check redacted failure evidence. |
| `SDK-SOURCE-INGEST-R006.37` | Hot-path proof | Require wire calls, stable schema, backend identity evidence and zero refused-operation requests. |

## Resource and restart measurements

The SQL acceptance fixture runs 10,000 and 1,000,000 rows with identical column widths and chunk limits.
Run each size in three separate warmed processes and record baseline RSS, peak RSS and queue high-water marks.
Each run must remain within a declared 32-MiB incremental memory budget after warmup.
The median peak for the larger result must not exceed the smaller result's median by more than eight MiB.
Record platform, driver and fixture versions. A threshold failure remains a failure; no post-hoc bound change establishes flat memory.
Inject a native driver error after the third emitted chunk and inspect the actual receiving client's terminal result.
Require query_failed, incomplete query identity, closed database handle and no fourth chunk or successful completion.
Distinguish previously accepted page receipts from the failed page and read checkpoint state from the graph.

The stage restart test uses two source stages and one receipt-dependent stage.
Pause one source after extraction while another commits, then stop the worker process.
Restart the actual CLI, collect source request boundaries and compare them with generated durable status.
No accepted event may be fetched again; ambiguous unacknowledged pages may replay only with unchanged idempotency identities.
The graph must contain each accepted source identity exactly once. Blocked dependent stages must emit no source requests.

The bookmark test records attempted external source access, not only successful connections.
Permit only the isolated graph transport; reject every external HTTP, DNS and model request.
Check local extraction still returns all declared metadata and records unknown domains explicitly.

Workspace fixtures contain real PDF, DOCX, XLSX, TXT, VTT and SRT bytes, plus unsupported and corrupt files.
Capture start/end timestamps to prove at least two reads overlap while peak active readers never exceeds two.
Hash every input before and after execution. Check sheet/cell, page/paragraph, line and cue locations.
Test compressed expansion limits, symlink escape and changed-file digests through the same served entry point.
An unsupported file remains visible beside successful files and receives no accepted progress token.

Enterprise acceptance registers two separately packaged connectors against distinct local backend services.
Send identical list_accounts and read_invoice contracts before and after changing only the approved connector selection.
Inspect normalized records and backend request logs. Exercise create_invoice through governed approval and idempotency.
Repeat an effect with the same identity and assert one effect; denied and unsupported effects produce zero backend requests.

## Approved query receiving acceptance

All tests in this section are planned and unexecuted.

| Requirement | Case | Required assertion |
|---|---|---|
| `SDK-SOURCE-INGEST-R004.7` | Model | `tests/test_approved_sql_source.py::test_generated_descriptor_and_page_contract` checks exact producer fields, page invariants and continuation bindings. |
| `SDK-SOURCE-INGEST-R004.8` | Behavior | `tests/test_approved_sql_source.py::test_verification_boundaries_and_bounds` checks start/chunk/complete order, immutable parameters, read-only execution and bounded buffers. |
| `SDK-SOURCE-INGEST-R004.9` | Wiring | `tests/test_approved_sql_source_served.py::test_registered_approval_receiver` traces the tools/call wire method through actual registration, verification and driver access. |
| `SDK-SOURCE-INGEST-R004.10` | Refusal | `tests/test_approved_sql_source_served.py::test_revocation_and_failure_after_chunks` proves explicit terminal failure after three chunks and zero unauthorized effects. |
| `SDK-SOURCE-INGEST-R004.11` | Evidence | `tests/test_approved_sql_source.py::test_page_provenance_and_redaction` compares immutable bindings, verification receipts, terminal totals and redacted failures. |
| `SDK-SOURCE-INGEST-R004.12` | Hot-path proof | Use real authenticated dispatch on both sides. Mocks of approval, driver, dispatcher or durable ingestion cannot close acceptance. |
| `SDK-SOURCE-INGEST-R004.37` | Generic model | `tests/test_foreign_read.py::test_foreign_read_lifecycle_uses_exact_methods_and_binds_digest` checks the exact EG phase tags, wrapped DTOs and opaque approval boundary. |
| `SDK-SOURCE-INGEST-R004.38` | Generic behavior | `tests/test_foreign_read.py::test_foreign_read_refuses_sequence_digest_and_terminal_replay` checks monotone sequence, digest binding, terminal replay and explicit cancellation. |
| `SDK-SOURCE-INGEST-R004.39` | Generic refusal | `tests/test_foreign_read.py::test_foreign_read_timeout_and_malformed_response_fail_closed` checks deadline and malformed response refusal; the DTO test checks row and cell limits. |

## Declared connector sources

The modules are `tests/test_source_sync.py` and `tests/test_source_sync_served.py`.

| Requirement | Case | Required assertion |
|---|---|---|
| `SDK-SOURCE-INGEST-R004.19` | Model | `tests/test_source_sync.py::test_declaration_validates_sources` refuses a duplicate ID, an empty tool list and an incremental source without a cursor field. |
| `SDK-SOURCE-INGEST-R004.20` | Behavior | `tests/test_source_sync.py::test_runner_submits_typed_batches_once` runs twice over one fixture page set and submits each record once. |
| `SDK-SOURCE-INGEST-R004.21` | Wiring | `tests/test_source_sync.py::test_tool_surface_serves_declarations` lists the tool with a read-only annotation and returns the declarations. |
| `SDK-SOURCE-INGEST-R004.22` | Refusal | `tests/test_source_sync.py::test_runner_refusals_and_budgets` covers each refusal, the retry limit and a partial run. `tests/test_source_sync.py::test_malformed_pages_do_not_advance` checks malformed list paths, entries and IDs before any sink or cursor update. |
| `SDK-SOURCE-INGEST-R004.23` | Evidence | `tests/test_source_sync.py::test_report_binds_receipts` compares report batch digests with the engine receipts. |
| `SDK-SOURCE-INGEST-R004.24` | Hot-path proof | The test observes the engine refusal, the failed KV checkpoint and zero written nodes. |
| `SDK-SOURCE-INGEST-R004.25` | Pack mapping | A connector test resolves each declared record type in its manifest `schema_mappings`. |
| `SDK-SOURCE-INGEST-R004.29` | Declarations as typed data | `tests/test_load_declaration.py::test_shared_field_sets_expand_once_per_mapping`, `::test_previous_schema_version_still_reads`, `::test_inline_fields_win_over_a_shared_set`, `::test_unknown_field_set_and_unsupported_version_are_refused` and `::test_a_package_without_sources_is_refused`. |
| `SDK-SOURCE-INGEST-R004.30` | Declared record mappers | `tests/test_ingest_mapping.py`. |
| `SDK-SOURCE-INGEST-R004.31` | One ingest stream entry | `tests/test_ingest_stream.py`. |
| `SDK-SOURCE-INGEST-R004.32` | Best-effort, split-stream, media and mixed submissions | `tests/test_ingest_stream.py`. |
| `SDK-SOURCE-INGEST-R004.33` | Cursor strategies and batching | `tests/test_ingest_strategies.py`. |
| `SDK-SOURCE-INGEST-R004.34` | Projection, guard and limits in submit | `tests/test_ingest_strategies.py`. |
| `SDK-SOURCE-INGEST-R004.35` | Declared ingest tools | `tests/test_ingest_strategies.py`. |
| `SDK-SOURCE-INGEST-R004.36` | Declared source edges | `tests/test_source_sync_edges.py`. |
| `SDK-SOURCE-INGEST-R004.28` | Per-parent fan-out | `tests/test_for_each.py::test_child_runs_once_per_parent_record`, `::test_missing_parent_and_cycle_are_typed_refusals`, `::test_fan_out_is_capped`, `::test_for_each_is_in_the_served_schema`, `::test_preset_adapter_fans_out_and_pages_each_parent` and `::test_preset_adapter_refuses_unknown_parent`. |

<!-- spec-definition-patch:webui-3-10-source-definition-20261012 -->
## Supported-harness session synchronization (WEBUI:3)

<!-- # spec: SDK-SOURCE-INGEST-R013; future acceptance links only; no evidence recorded. -->

These tests are planned. They require the complete owner-approved manifest and published EG/Arbora contracts.

| Test ID | Requirement | Level | Setup and input | Expected observation | Evidence |
|---|---|---|---|---|---|
| HS-13.1 | R013.1 | Contract | unbound entries | refusal before calls | `tests/test_supported_harness_session_sync.py::test_manifest_rejects_unbound_entries_before_source_calls` |
| HS-13.2 | R013.2 | Integration | sync/restart | full coverage and idempotent resume | `tests/test_supported_harness_session_sync.py::test_first_run_coverage_retry_and_restart` |
| HS-13.3 | R013.3 | Served | connector-sync --once | generated SourceIngest calls | `tests/test_supported_harness_session_sync_served.py::test_connector_sync_uses_generated_source_ingest` |
| HS-13.4 | R013.4 | Negative | denied/cross-tenant source | typed refusal; zero calls; cursor unchanged | `tests/test_supported_harness_session_sync_served.py::test_denial_is_partial_without_cursor_advance` |
| HS-13.5 | R013.5 | Persistence | restart/readback | bound receipts agree | `tests/test_supported_harness_session_sync.py::test_receipts_read_back_after_restart` |
| HS-13.6 | R013.6 | End-to-end | every entry and WEBUI-APPS-R006.4 | full browse/coverage; EG and Arbora IDs unassigned | `tests/test_supported_harness_session_sync_served.py::test_every_manifest_source_is_browsable` |

## Live meeting and summary providers (WEBUI:10)

<!-- # spec: SDK-SOURCE-INGEST-R014; future acceptance links only; no evidence recorded. -->

Current dictation routes are single-shot. These tests require a registered meeting operation and EG/Arbora provider bindings.

| Test ID | Requirement | Level | Setup and input | Expected observation | Evidence |
|---|---|---|---|---|---|
| MT-14.1 | R014.1 | Contract | exact replay/conflicting duplicate | same receipt/no effect; conflict refuses | `tests/test_meeting_transcript_contract.py::test_exact_replay_and_conflicting_duplicate` |
| MT-14.2 | R014.2 | Integration | partial/replay/correction/gap/completion | exact replay has one effect; complete sequence finalizes with bound receipt | Proposed: `tests/test_meeting_transcript.py::test_ordered_partial_replay_correction_and_finalization_receipt` |
| MT-14.3 | R014.3 | Served | owner-registered meeting operation | real SDK/Arbora calls; IDs unresolved | `tests/test_meeting_transcript_served.py::test_registered_operation_dispatch_and_readback` |
| MT-14.4 | R014.4 | Negative | denied capture; complete finalize; gap; summary pre-receipt | Complete finalization succeeds. Denial, gaps, and missing receipt refuse before provider effects. | Proposed: `tests/test_meeting_transcript_served.py::test_gap_blocks_finalize_and_missing_receipt_blocks_summary` |
| MT-14.5 | R014.5 | Persistence | corrected transcript/summary | final revision/provider provenance | `tests/test_meeting_transcript.py::test_receipt_binds_final_revision_and_provider` |
| MT-14.6 | R014.6 | End-to-end | partial/correction/complete finalization/summary | The bound receipt precedes local/hosted summary dispatch. No summary call occurs early. | Proposed: `tests/test_meeting_transcript_served.py::test_partial_correction_complete_finalize_receipt_then_summary` |
<!-- /spec-definition-patch -->

<!-- spec-definition-patch:sdk-consolidated-r006-rollup-binding-20261012 -->
<!-- # spec: SDK-SOURCE-INGEST-R006; rollup link to existing child test bindings R006.1 through R006.31; no new runtime evidence. -->
<!-- /spec-definition-patch -->

## Document sources moved from agent-utilities (R005.37-R005.39)

- `SDK-SOURCE-INGEST-R005.37`: `tests/test_document_sources.py::test_two_domain_packs_ingested_with_lineage` and `::test_incremental_change_updates_only_the_touched_file` ingest two packs from a scratch git repository. They read lineage back from the committed records. They then modify and remove files and observe one upsert and one withdrawal.
- `SDK-SOURCE-INGEST-R005.38`: `tests/test_document_sources.py::test_filesystem_connector_ingestion_live_path` ingests a tree with refused entries, re-runs without change, then advances one file.
- `SDK-SOURCE-INGEST-R005.39`: `tests/test_document_sources.py::test_governed_connector_applies_envelope_before_embedding`, `::test_governed_connector_failure_blocks_document_and_checkpoint` and `::test_governance_failure_leaves_real_engine_checkpoint` (a real `epistemic-graph-server`) prove the envelope is stamped before submission and a refusal leaves the durable checkpoint unchanged.

## Ingest under an accepted contract (R017)

- `SDK-SOURCE-INGEST-R017`: Rollup closes when every child `.1` to `.6` passes its proving test.
- `SDK-SOURCE-INGEST-R017.1`: `tests/test_ingest_contract_binding.py::test_binding_carries_contract_iri`.
- `SDK-SOURCE-INGEST-R017.2`: `tests/test_ingest_contract_binding.py::test_nested_values_become_relationships`.
- `SDK-SOURCE-INGEST-R017.3`: `tests/test_ingest_contract_binding.py::test_submit_checks_accepted_contract`.
- `SDK-SOURCE-INGEST-R017.4`: `tests/test_ingest_contract_binding.py::test_refusals_keep_checkpoint`.
- `SDK-SOURCE-INGEST-R017.5`: `tests/test_ingest_contract_binding.py::test_report_matches_engine_receipt`.
- `SDK-SOURCE-INGEST-R017.6`: `tests/test_ingest_contract_served.py::test_ingest_requires_accepted_contract`.

## Web-source fetch contract (R005.40)

- `SDK-SOURCE-INGEST-R005.40`: Rollup closes when every child `.1` to `.6` passes its proving test.
- `SDK-SOURCE-INGEST-R005.40.1`: `tests/test_web_source_contract.py::test_models_round_trip`.
- `SDK-SOURCE-INGEST-R005.40.2`: `tests/test_web_source_contract.py::test_conformance_kit_flags_each_obligation`.
- `SDK-SOURCE-INGEST-R005.40.3`: `tests/test_adapters_web_fetch_source_adapter.py::test_extract_calls_connector_tool`.
- `SDK-SOURCE-INGEST-R005.40.4`: `tests/test_adapters_web_fetch_source_adapter.py::test_refusal_keeps_checkpoint`.
- `SDK-SOURCE-INGEST-R005.40.5`: `tests/test_adapters_web_fetch_source_adapter.py::test_record_provenance_matches_engine_model`.
- `SDK-SOURCE-INGEST-R005.40.6`: `tests/test_web_source_served.py::test_two_backends_produce_equal_records`.
- `SDK-SOURCE-INGEST-R005.41`: `tests/test_adapters_web_fetch_source_adapter.py::test_failed_fetch_preserves_accepted_checkpoint`.
- `SDK-SOURCE-INGEST-R005.42`: `tests/test_adapters_web_fetch.py` checks pinned egress and explicit private-host admission.
- `SDK-SOURCE-INGEST-R004.26`: `tests/test_ingest_citable_fields.py::test_citable_fields_keep_public_urls_and_nothing_else`.
- `SDK-SOURCE-INGEST-R004.27`: `tests/test_contracts_and_sink.py::test_sink_passes_the_mass_withdrawal_decision_to_the_engine`.

## Permission sync, identifier enumeration, containers and the read-time access check

| Row | Proving test |
|---|---|
| `SDK-SOURCE-INGEST-R805` | See each child. |
| `SDK-SOURCE-INGEST-R805.1` | `tests/source_connectors/test_permission_sync.py::test_access_batch_carries_no_content` |
| `SDK-SOURCE-INGEST-R805.2` | `tests/source_connectors/test_permission_sync.py::test_interrupted_enumeration_is_incomplete` |
| `SDK-SOURCE-INGEST-R805.3` | `tests/source_connectors/test_permission_sync.py::test_container_batch_preserves_parents` |
| `SDK-SOURCE-INGEST-R805.4` | `tests/test_source_sync.py::test_runner_schedules_access_enumeration_and_containers` |
| `SDK-SOURCE-INGEST-R805.5` | `tests/test_access_check_port.py::test_timeout_denies_every_record` |
| `SDK-SOURCE-INGEST-R805.6` | `tests/test_permission_sync_served.py::test_revocation_and_prune_against_real_engine` |
| `SDK-SOURCE-INGEST-R805.7` | `tests/test_access_check_port.py` covers bounded SDK-local access checks. |

## Voice registry identity binding

`SDK-SOURCE-INGEST-R804.7` uses the real manifest and license registry APIs.
Invalid identifiers must not access a file outside the registry. A decision
for another manifest must not approve the requested handoff.
# Voice decision registry scale proof

R804.6 records one thousand distinct license decisions through the production
registry, then reads each decision back. Each lookup must read one decision file.

# Concurrent stage model proof

R001.1 validates stage identity, limits and the dependency graph at SyncTarget
construction. The sequential sync path refuses stage-bearing targets before it
discovers or extracts from a source.
# Web certification and runner admission dependency

R005.40.3 and R005.40.4 require a host-admitted receipt tied to the tested
connector revision and live tool schemas. A schema-only match is not web
conformance. Tests must refuse missing, stale and mismatched evidence before
the tool call and leave the checkpoint unchanged.

## REST source malformed pages (R800.9)

Poll through the registered REST source with a prior cursor and next cursor.
Refuse missing or non-list records, non-object records, blank IDs and empty text.
The caller checkpoint stays unchanged, and no next cursor is returned.

## Partial RSS sweep (R800.8)

Inject network failure and malformed input in concurrent feeds. A healthy feed
returns newer records while the prior watermark remains fixed. Recover the
failed feed and assert its older records arrive once and the watermark moves.

## Partial arXiv sweep (R800.7)

Inject both a network failure and malformed category feed. A healthy category
returns a newer record while the prior watermark remains fixed. Recover the
failed category and assert its older record arrives once and the watermark moves.

## Timestamp watermark ordering

R900.7 checks a SQLite source compares offset-bearing timestamps by instant
and replays idempotently. Invalid timestamps and mixing
timezone-aware and naive timestamps fail closed.

## Numeric zero REST cursor (R800.11)

Return numeric zero as a continuation from the first page. Confirm that the
next poll sends the string cursor and returns the second page.

## Database page completeness

R900.8 exercises missing text and missing watermarks against SQLite. The read
refuses before a partial load or checkpoint, then succeeds after row repair.

## Bounded web crawl and resumption (R800.10)

Poll a linked site with a one-page limit and an already-seen seed. Every call
fetches at most one page. Serialized checkpoints resume to the deeper pages.
A checkpoint bound to a different source refuses before a fetch.

## Web host rate limiting (R005.43)

A controlled clock checks shared pacing across schemes, ports, host case,
trailing dots, IDNA and equivalent IPv6 forms. Another host has its own budget.

R005.44 checks a valid IPv6 robots URL, denial of a private path and cache
reuse for equivalent IPv6 and IDNA spellings.

R005.55 checks the total web-fetch deadline against trickling data and stalled DNS.

R005.54 sends malformed tag, metadata and title starts through the legacy
adapter. It uses a pinned local HTTP fetch and observes a returned page.

R005.53 compares title selection with the previous expression and exercises
large unclosed starts and missing closing tags.

R005.52 compares quoted metadata precedence and entities with the previous
parser, then exercises large unclosed and nested metadata spans.

R005.51 compares tag stripping against the previous behavior and exercises a
large unclosed span within a bounded test timeout.

R005.50 resumes a bound checkpoint against the same and changed URL lists.
A mismatch refuses before fetching. Legacy unbound checkpoints stay usable.

R005.49 submits invalid stream and index values to the legacy adapter. It
refuses each before a fetch, and a terminal checkpoint remains unchanged.

R005.48 streams an oversized body and a compressed body. It refuses both,
closes each response and leaves the adapter without a page.

R005.45 calls the served web-fetch tool with a denied URL carrying a query
secret. The refusal contains its reason but no requested path or query value.

R005.46 blocks one fake robots load while concurrent checks enter. They share
one load for that origin; a different origin completes independently.
- `SDK-SOURCE-INGEST-R005.47`: `tests/test_evm_chain_models.py` checks model bounds and refusal before discovery or extraction.

R803.7 mutates the exposed plan view and asserts that both execution paths retain their original plan and evidence.

R803.8 refuses duplicate Arrow names before a row conversion can overwrite a field.

R803.9 suppresses numeric statistics when any value is below the disclosure threshold. Eligible-only data still produces statistics.

R803.10 refuses a passed result with zero checks at both models and at the job boundary.

R803.11 refuses any mismatch between certification state and signed summary status.

R803.12 rejects non-string signer identity, algorithm and signature without reporting a pass.
R803.13 checks the missing Arrow dependency through the public adapter and names the declared extra.
R803.14 submits a mutated engine profile with a below-threshold value and requires refusal before it reaches the caller.

### Stalled MCP cursor (SDK-SOURCE-INGEST-R004.50)

`tests/test_mcp_cursor_refusal.py` enters both shared adapter paths through the sync worker. It checks the accepted checkpoint and retry after a repeated cursor, error redaction, and an explicit provider end.
R004.40 exercises cyclic and malformed continuation tokens and a bounded history, preserving accepted pages while refusing the offending page.

R004.41 validates durable status and cursor identity and refuses malformed checkpoints before source fetch.

R004.42 refuses malformed durable sequence values before SourceIngest submission, while retaining legacy absence and valid sequence advancement.

R004.43 mutates the caller checkpoint during dispatch. The receipt still binds the sent snapshot.

R004.51 refuses a custom transport status for another connector or stream before SourceIngest submission.
R004.44 conflicts on a cursor-bearing submission and checks that the page is not retried against a changed checkpoint.
R004.45 interrupts a chunked single-stream page. Earlier chunks keep the old cursor; a completed page advances it.
R004.46 refuses split document pages before either stream commits. Entity-only sync still runs with the same binding setup.

R004.47 refuses an accepted checkpoint that names another stream through the generated status channel.

R004.48 checks conflict refusal on terminal pages and intermediate chunks while a competing writer advances the cursor.

R004.49 denies a best-effort page and confirms that sync does not fetch its continuation.
R012.7 tests bounded platform contract primitives and structural continuation binding. Authentication, continuation integrity, equivalence certification, and served behavior remain open.

R004.52 submits a non-page write after a paged checkpoint and confirms the prior cursor survives.
