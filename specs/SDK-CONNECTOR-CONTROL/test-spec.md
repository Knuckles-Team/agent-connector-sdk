# Test specification: connector control

| ID | Fixture/action | Required assertion |
|---|---|---|
| CC-01 | Register a manifest-backed connector entry point | Check group, name, distribution, and version independently. Direct construction matches served server identity. |
| CC-02 | Change input schema, output schema, entry-point version, or server identity one at a time. | Certification refuses each mismatch before tool execution. |
| CC-03 | Publish same canonical pack twice through a fake generated client | Same idempotency key and result. Changed content yields new digest/key. |
| CC-04 | Feed duplicate entries, bad URI scheme, undeclared kind, literal credential, or oversized body | Deterministic named refusal. No pack call and no secret in output. |
| CC-05 | Request event/tool-choice proposal | Proposal can be logged and rejected; it cannot call write-back or grant an action. |
| CC-06 | Build the wheel. Install it in isolation with the locked published graph wheel. | Generated DTO imports and client/pack calls work without source path overlays. |
| CC-07 | Scan every migrated connector batch | No runtime import or declared dependency on `agent_utilities`; SDK conformance suite and connector's own tests pass. |
| CC-08 | Submit one synthetic pack to a contributor-owned running graph service | Receipt binds tenant, connector, digest, and retry identity. Wrong tenant and stale contract pin refuse. |
| CC-09 | Submit SQL change page with generated SourceIngest client | Typed receipt binds table/key/schema/checkpoint and advances only on accepted result; mismatched tenant or schema refuses. |
| CC-10 | Certify an annotated multi-modal pack | Capability, schema digests, modality, cost/latency units and provenance round-trip. Missing estimate is unknown. Malformed annotation refuses. |

Pull requests run `uv sync`, focused `pytest`, Ruff, mypy, wiring checks, CCCC, jscpd, Dupehound, and KISS through the repository's reproducible hooks. CC-08 is an acceptance probe, not a cloud-PR prerequisite. When the optional live environment is absent, record that the probe did not run. Do not infer a source-gate result.

| ID | Fixture/action | Required assertion |
|---|---|---|
| CC-11 | Parse a fake connector ontology with one `ac:AccessContract` and one `ac:PropertyBinding` (SDK-CONNECTOR-CONTROL-R021) | The parser returns one typed contract and its `VirtualMapping` fields. It refuses a literal secret, an unknown pushdown, pagination or access kind, a missing operation, and a non-integer hint. No error text contains the secret. |
| CC-11A | Parse each access kind in a source contract (SDK-CONNECTOR-CONTROL-R040 to R044). | Each kind preserves the entity, key, operation, bindings and pushdown declarations. The parser refuses unknown kinds and literal credentials. |
| CC-12 | Scope a fake ontology that imports `http://knuckles.team/kg` and a sibling pack ontology. Prove the hub import leaves the body and appears in `requires_capabilities`. Prove an in-pack body keeps its bytes. (`tests/test_pack_ontology_imports.py`) | SDK-CONNECTOR-CONTROL-R022 |
| CC-13 | Capture a fake prompt with one required and one optional argument through `PromptArtifactKind.list_entries`. (`tests/test_prompt_content.py::test_prompt_capture_binds_required_arguments_as_template`) | `prompts/get` is awaited with `{"<required>": "{{<required>}}"}`. The stored `capture` records `kind: "template"` and the same binding map. `validate` accepts the entry; a prompt with no required argument still captures `kind: "rendered"` with an empty binding map. |
| CC-14 | Simulate a typed required argument: `get_prompt` raises `McpPromptRejectedError` for a prompt with one required and one optional argument. (`tests/test_prompt_content.py::test_prompt_capture_falls_back_to_template_when_server_rejects_bound_argument`) | The capture still succeeds as `kind: "template"` with the same `bound_arguments` map. The stored `result` is a synthesized message naming the prompt's own arguments, not server content. `validate` accepts the entry. |
| CC-14b | Same failure for a prompt with no required argument. (`tests/test_prompt_content.py::test_prompt_capture_still_fails_when_rejected_with_no_required_argument`) | `McpPromptRejectedError` still raises; no fallback, because no placeholder was ever bound. |
| CC-14c | `get_prompt` raises the plain `McpTransportError` (a transport failure, not a protocol rejection) for a prompt with a required argument. (`tests/test_prompt_content.py::test_prompt_capture_propagates_genuine_transport_failures`) | `McpTransportError` still raises; the fallback never masks a server-unreachable failure. |
| CC-15 | Exercise the behaviour of SDK-CONNECTOR-CONTROL-R045.1. (`tests/test_tool_facts.py::test_facts_model_is_frozen_and_typed`) | Type `ToolContractFacts` holds as the row states. |
| CC-16 | Exercise the behaviour of SDK-CONNECTOR-CONTROL-R045.2. (`tests/test_tool_facts.py::test_side_effect_set_is_closed_and_read_only_is_consistent`) | Close the `SideEffect` set holds as the row states. |
| CC-17 | Exercise the behaviour of SDK-CONNECTOR-CONTROL-R045.3. (`tests/test_tool_facts.py::test_schema_tokens_uses_canonical_body_and_named_divisor`) | Compute `schema_tokens` from the existing canonical tool body holds as the row states. |
| CC-18 | Exercise the behaviour of SDK-CONNECTOR-CONTROL-R045.4. (`tests/test_tool_facts.py::test_undeclared_tool_defaults_to_not_read_only`) | Default to the safe value when a connector declares nothing holds as the row states. |
| CC-19 | Exercise the behaviour of SDK-CONNECTOR-CONTROL-R045.5. (`tests/test_tool_facts.py::test_mcp_read_only_hint_is_recorded_as_self_declared`) | Map MCP annotations as self-declared hints holds as the row states. |
| CC-20 | Exercise the behaviour of SDK-CONNECTOR-CONTROL-R045.6. (`tests/test_tool_facts.py::test_side_effects_round_trip_through_generated_pack_annotations`) | Read `side_effects` from `eg.annotations`, and gate on the generated type holds as the row states. |
| CC-21 | Exercise the behaviour of SDK-CONNECTOR-CONTROL-R045.7. (`tests/test_tool_facts.py::test_destructive_action_is_never_read_only`) | Reuse the destructive classification holds as the row states. |
| CC-22 | Exercise the behaviour of SDK-CONNECTOR-CONTROL-R045.8. (`tests/test_pack.py::test_tool_entry_pack_carries_contract_facts`) | Attach the facts to the captured tool entry holds as the row states. |
| CC-23 | Exercise the behaviour of SDK-CONNECTOR-CONTROL-R045.9. (`tests/test_certify_read_only.py::test_read_only_tool_with_recorded_write_fails_certification`) | Certify that a `read_only` tool wrote nothing in its recorded fixture holds as the row states. |
| CC-24 | Exercise the behaviour of SDK-CONNECTOR-CONTROL-R045.10. (`tests/test_certify_read_only.py::test_mcp_hint_without_fixture_is_unproven_and_unpinned`) | Refuse an unproven self-declared `read_only` holds as the row states. |
| CC-25 | Exercise the behaviour of SDK-CONNECTOR-CONTROL-R045.11. (`tests/test_certify_read_only.py::test_manifest_and_pack_carry_equal_facts`) | Generate the manifest facts and prove the path end to end holds as the row states. |
| CC-26 | Exercise the behaviour of SDK-CONNECTOR-CONTROL-R046.1. (`tests/test_auth_pkce.py::test_config_is_frozen_and_holds_reference_only`) | The model row holds as stated. |
| CC-27 | Exercise the behaviour of SDK-CONNECTOR-CONTROL-R046.2. (`tests/test_auth_pkce.py::test_authorize_exchanges_code_with_verifier`) | The behavior row holds as stated. |
| CC-28 | Exercise the behaviour of SDK-CONNECTOR-CONTROL-R046.3. (`tests/test_certify_options.py::test_pkce_option_selects_manager`) | The wiring row holds as stated. |
| CC-29 | Exercise the behaviour of SDK-CONNECTOR-CONTROL-R046.4. (`tests/test_auth_pkce.py::test_refusals_are_typed_and_leak_no_secret`) | The refusal row holds as stated. |
| CC-30 | Exercise the behaviour of SDK-CONNECTOR-CONTROL-R046.5. (`tests/test_auth_pkce.py::test_trace_record_has_no_secret_fields`) | The evidence row holds as stated. |
| CC-31 | Exercise the behaviour of SDK-CONNECTOR-CONTROL-R046.6. (`tests/test_certify_pkce_flow.py::test_certify_run_authenticates_through_pkce`) | The hot-path proof row holds as stated. |
| CC-32 | Exercise the behaviour of SDK-CONNECTOR-CONTROL-R047.1. (`tests/test_a2a_discovery.py::test_discovered_card_is_frozen_and_typed`) | The model row holds as stated. |
| CC-33 | Exercise the behaviour of SDK-CONNECTOR-CONTROL-R047.2. (`tests/test_a2a_discovery.py::test_fetch_uses_well_known_path_and_etag`) | The behavior row holds as stated. |
| CC-34 | Exercise the behaviour of SDK-CONNECTOR-CONTROL-R047.3. (`tests/test_vendor_extractors_archer_infra_a2a.py::test_base_url_entry_is_fetched_into_cards`) | The wiring row holds as stated. |
| CC-35 | Exercise the behaviour of SDK-CONNECTOR-CONTROL-R047.4. (`tests/test_a2a_discovery.py::test_refusals_write_nothing`) | The refusal row holds as stated. |
| CC-36 | Exercise the behaviour of SDK-CONNECTOR-CONTROL-R047.5. (`tests/test_a2a_discovery.py::test_entity_carries_fetch_provenance`) | The evidence row holds as stated. |
| CC-37 | Exercise the behaviour of SDK-CONNECTOR-CONTROL-R047.6. (`tests/test_vendor_extractors_archer_infra_a2a.py::test_extract_discovers_card_from_base_url`) | The hot-path proof row holds as stated. |
| CC-38 | Exercise the behaviour of SDK-CONNECTOR-CONTROL-R048.1. (`tests/test_readable_form.py::test_model_is_frozen_and_optional_on_facts`) | The model row holds as stated. |
| CC-39 | Exercise the behaviour of SDK-CONNECTOR-CONTROL-R048.2. (`tests/test_readable_form.py::test_render_is_bounded_plain_text`) | The behavior row holds as stated. |
| CC-40 | Exercise the behaviour of SDK-CONNECTOR-CONTROL-R048.3. (`tests/test_pack.py::test_tool_entry_carries_readable_form`) | The wiring row holds as stated. |
| CC-41 | Exercise the behaviour of SDK-CONNECTOR-CONTROL-R048.4. (`tests/test_certify_readable_form.py::test_unscored_form_is_refused`) | The refusal row holds as stated. |
| CC-42 | Exercise the behaviour of SDK-CONNECTOR-CONTROL-R048.5. (`tests/test_certify_readable_form.py::test_verdict_records_question_counts`) | The evidence row holds as stated. |
| CC-43 | Exercise the behaviour of SDK-CONNECTOR-CONTROL-R048.6. (`tests/test_certify_readable_form.py::test_certify_run_scores_form_and_pack_carries_it`) | The hot-path proof row holds as stated. |
| CC-44 | Exercise the behaviour of SDK-CONNECTOR-CONTROL-R049.1. (`tests/test_http_payments.py::test_models_are_frozen_and_typed`) | The model row holds as stated. |
| CC-45 | Exercise the behaviour of SDK-CONNECTOR-CONTROL-R049.2. (`tests/test_http_payments.py::test_decide_applies_named_limits`) | The behavior row holds as stated. |
| CC-46 | Exercise the behaviour of SDK-CONNECTOR-CONTROL-R049.3. (`tests/test_http_payments.py::test_client_hook_gates_402_through_approval`) | The wiring row holds as stated. |
| CC-47 | Exercise the behaviour of SDK-CONNECTOR-CONTROL-R049.4. (`tests/test_http_payments.py::test_refusals_send_no_payment_header`) | The refusal row holds as stated. |
| CC-48 | Exercise the behaviour of SDK-CONNECTOR-CONTROL-R049.5. (`tests/test_http_payments.py::test_every_attempt_emits_a_record`) | The evidence row holds as stated. |
| CC-49 | Exercise the behaviour of SDK-CONNECTOR-CONTROL-R049.6. (`tests/test_http_payments_flow.py::test_served_operation_pays_within_budget_and_refuses_over`) | The hot-path proof row holds as stated. |


## Served context acceptance

All cases below bind to SDK-CONNECTOR-CONTROL-R050 and its six children.
The planned test module is `tests/test_tool_context_served.py`.

| ID | Fixture/action | Required assertion |
|---|---|---|
| CC-50 | Construct context and progress models with malformed fields. | Unknown state, missing identity, NaN, negative completion and excessive message length refuse. |
| CC-51 | Two concurrent producers report completion `1`; after both finish, report `2`. Repeat with unknown total. Separately omit the token. | Emitted completion values are exactly `[1, 2]`; sequence strictly increases and completion never exceeds total. Equal-value updates may change the internal terminal summary. No token yields zero notifications and retains the terminal summary. |
| CC-52 | Start the SDK server with condensed and method registrars; call both over MCP | Each handler receives the authenticated context. Its dispatch, logs, progress and result retain one request identity. |
| CC-53 | Deny EG approval, expire deadline, cancel, and break progress delivery after a source effect. Reconnect after losing the terminal response. | Pre-effect refusal calls no backend. An uncertain result identifies the existing receipt. Governed reconciliation and retries produce at most one effect. Missing reconnect mapping returns `recovery_unavailable`, no reconstructed result and no second effect. |
| CC-54 | Run concurrent calls for two tenants and inspect logs, caches and results | No state or token crosses requests. Each event carries provenance; secrets, raw arguments and cached values are absent. |
| CC-55 | Run `test_served_context_progress_and_approval` against a running server and controlled backend | The client receives push notifications before terminal metadata. Backend counters prove allowed effects and zero denied effects. Direct helper invocation is insufficient. |

The served test must include stale and wrong-operation approval, mismatched tenant,
reused effect key with changed arguments. Also exercise duplicate requests and notification loss.
The served reconnect case must preserve the original request and effect identity across the disconnected sessions.
Exercise it with no authenticated producer mapping and assert the typed refusal before any repeated backend call.
Do not accept a helper-only refusal or an effect receipt as proof of terminal result retrieval.
Approval tests assert Arbora returns EG's decision unchanged and the SDK refuses a mismatched binding.
Use bounded barriers to prove notification arrival before the backend completes.
Assert no messages arrive after terminal completion and cache state is cleared.
Record server revision, transport, exact command, result and redacted trace receipt.
These are implementation acceptance requirements; specification checks do not run them.


## Scoped credential and inline authorization acceptance

CC-56 through CC-61 bind SDK-CONNECTOR-CONTROL-R035.1 through R035.6 in tests/test_scoped_credential_transport.py.
Use a real served SDK connector, controlled local OIDC/provider servers and the qualified host challenge/vault fixture.
Enter tools/call with one granted client; assert exactly one credential resolution and authenticated provider request.
Repeat with a co-located unrelated client, wrong tenant, expired grant and revoked authority; assert zero resolver/provider calls.
Test environment and vault references equally; a failed vault grant cannot fall back to process-visible credentials.
For R046, invoke the actual certify command and the served connector's credential-missing path, not only PkceAuthManager directly.
Complete an S256 challenge through a real HTTP callback and read the host persistence receipt before observing the resumed request.
Test browser opening failure, callback failure, absent input, input timeout, cancellation, replay and wrong-client redirect submission.
Each case returns the named bounded outcome and creates no token exchange or resumed effect after invalidation.
Fail vault persistence after exchange; readiness must remain false. Restart and retry through current host authority without duplicating the pending operation.
Inspect transport and logs for codes, verifier, raw tokens, pasted responses and credential values. No public output may contain them.
These integration tests have not run. Helper tests and spec checks do not establish runtime completion.


### Served connector and token-profile acceptance

Extend the existing named served credential/PKCE tests through actual REST/MCP ingress, connector dispatch and controlled provider exchanges.
Grant connector A and prove its authorized call succeeds. Keep tenant, principal/client, provider, audience and scopes unchanged, then target connector B.
The SDK refuses caller-forged connector A metadata on B before secret resolution or exchange. It also refuses a genuine B identity that holds only A's grant.
An explicit B grant permits B without changing A's authority. Assert challenge, vault receipt and transport evidence contain the admitted connector.
Use an OIDC provider returning a signed ID token plus opaque access and refresh tokens; the declared mixed profile must succeed.
Separately prove the JWT access-token profile succeeds with valid signatures, audiences, expiry and resource bindings.
Bad JWT signature, nonce, audience, issuer or expiry refuses; a JWT failure must never retry under an opaque profile.
For exchange-bound opaque tokens, validate authenticated provider/client/PKCE and required resource/account/consent evidence without manufacturing JWT claims.
For introspection-required opaque tokens, active and correctly bound evidence succeeds; inactive, unavailable or missing required fields refuses.
An opaque token without provider expiry may use only the explicit bounded host lease. Assert evidence distinguishes the two validity sources.
Forged profile selection, wrong connector, cross-tenant binding, excess scopes and unapproved resource audience all refuse with zero resumed effects.
The outbound opaque profile must not admit an unsigned Arbora API bearer or remove its required tenant claim.
Inspect responses and logs for token/code leakage. These acceptance cases have not run. They require the runtime wiring.

<!-- spec-definition-patch:sdk5-r007-major-version-tests -->
## Major-version compatibility and pre-pin rollout acceptance (R007.1-R007.6)

These future tests have not run. The producer, gate, and writer attachments are not implemented; no VERIFIED evidence exists.

- **Model and inventory:** Assert stable canonical sorting and digest. Refuse duplicate, unidentifiable, or incomplete package inventories.
- **Receipt production:** Test every inventoried package against the exact artifact in isolation. Assert one complete bound receipt per package and unchanged dependency-file bytes.
- **Positive hot path:** Enter the production rollout command and exercise real pin writers. Assert the all-pass set authorizes only bound packages across R009-R013.
- **Incompatible hot path:** Fail one package check through the same entry point. Assert refusal before the first pin write and unchanged manifests and lockfiles.
- **Missing and stale evidence:** Remove a receipt or change the source, pin preimage, inventory, or artifact. Assert typed refusal and no pin changes.
- **Invalid receipt sets:** Test failed, incomplete, cancelled, duplicate, extra, and cross-package receipts. Assert preflight refusal before any write and byte-identical pins.
- **CC-105 / R007.4:** `tests/test_major_version_compatibility_served.py::test_fleet_preflight_refusal_preserves_all_pins` proves preflight refusal preserves every pin byte-for-byte.
- **CC-106 / R007.6:** `tests/test_major_version_compatibility_served.py::test_writer_b_preimage_race_reports_partial_rollout` races B after A writes. It proves B does not write and requires reconciliation. It identifies A as applied and B as refused.
- **Existing acceptance:** Retain R007 fingerprint and live-contract comparison and R009-R013 package migration and import-scan tests.
<!-- /spec-definition-patch -->

<!-- spec-definition-patch:sdk-consolidated-primary-20261012-tests -->
## Consolidated SDK future acceptance
- **CC-81 / SDK-CONNECTOR-CONTROL-R051.1:** Validate all identity fields and actual instance IDs. Proposed: `tests/test_sandbox_provisioned_served.py::test_request_result_identity_round_trip`.
- **CC-82 / SDK-CONNECTOR-CONTROL-R051.2:** A replay returns the reconciled allocation without duplication. Proposed: `tests/test_sandbox_provisioned_served.py::test_uncertain_allocation_reconciles_before_retry`.
- **CC-83 / SDK-CONNECTOR-CONTROL-R051.3:** Exercise the served route, adapter, and result consumer. Proposed: `tests/test_sandbox_provisioned_served.py::test_agents_run_reaches_sdk_provisioner`.
- **CC-84 / SDK-CONNECTOR-CONTROL-R051.4:** Negative cases observe zero unsupported or unauthorized allocations. Proposed: `tests/test_sandbox_provisioned_served.py::test_denied_profiles_have_zero_provider_calls`.
- **CC-85 / SDK-CONNECTOR-CONTROL-R051.5:** Independent readback matches the bound allocation receipt. Proposed: `tests/test_sandbox_provisioned_served.py::test_receipt_matches_independent_readback`.
- **CC-86 / SDK-CONNECTOR-CONTROL-R051.6:** The served acceptance proves actual allocation and zero duplicate effects. Proposed: `tests/test_sandbox_provisioned_served.py::test_served_replay_has_no_duplicate_effect`.
- **CC-87 / SDK-CONNECTOR-CONTROL-R052.1:** Reject absent or malformed provenance and unbounded payloads. Proposed: `tests/test_visual_observation_served.py::test_rejects_unbound_or_unbounded_envelopes`.
- **CC-88 / SDK-CONNECTOR-CONTROL-R052.2:** The next step reads the committed same-run observation only. Proposed: `tests/test_visual_observation_served.py::test_next_step_reads_committed_same_run_reference`.
- **CC-89 / SDK-CONNECTOR-CONTROL-R052.3:** A served two-step test observes matching IDs at result, state, and consumer. Proposed: `tests/test_visual_observation_served.py::test_tools_call_forwards_observation_to_eg_and_au`.
- **CC-90 / SDK-CONNECTOR-CONTROL-R052.4:** Each refusal produces zero provider effects. Proposed: `tests/test_visual_observation_served.py::test_invalid_scope_refuses_before_provider_effect`.
- **CC-91 / SDK-CONNECTOR-CONTROL-R052.5:** EG readback confirms provenance without returning raw content. Proposed: `tests/test_visual_observation_served.py::test_readback_excludes_visual_payload`.
- **CC-92 / SDK-CONNECTOR-CONTROL-R052.6:** The observed path proves reuse and zero effects on refusal. Proposed: `tests/test_visual_observation_served.py::test_two_step_reuse_isolation_and_stale_refusal`.
- **CC-93 / SDK-CONNECTOR-CONTROL-R053.1:** Reject duplicate declarations, literals, and unknown components. Proposed: `tests/test_environment_manifest_served.py::test_manifest_rejects_duplicate_literal_and_unknown_entries`.
- **CC-94 / SDK-CONNECTOR-CONTROL-R053.2:** Undeclared reads and missing required declarations block startup. Proposed: `tests/test_environment_manifest_served.py::test_missing_and_undeclared_inputs_block_startup`.
- **CC-95 / SDK-CONNECTOR-CONTROL-R053.3:** The served launcher consumes the SDK declaration set. Proposed: `tests/test_environment_manifest_served.py::test_host_startup_consumes_sdk_declaration_set`.
- **CC-96 / SDK-CONNECTOR-CONTROL-R053.4:** A secret canary is absent from every refusal diagnostic. Proposed: `tests/test_environment_manifest_served.py::test_refusal_diagnostics_redact_secret_values`.
- **CC-97 / SDK-CONNECTOR-CONTROL-R053.5:** Independent readback reproduces the declaration set and decision. Proposed: `tests/test_environment_manifest_served.py::test_readback_matches_manifest_and_decision`.
- **CC-98 / SDK-CONNECTOR-CONTROL-R053.6:** The healthy case serves; each negative case refuses before admission. Proposed: `tests/test_environment_manifest_served.py::test_served_startup_accepts_declared_and_refuses_invalid`.
- **CC-99 / SDK-CONNECTOR-CONTROL-R054.1:** Planned `tests/test_json_tag_loader_migration_served.py::test_inventory_finds_every_source_loader` validates complete entries, ordering, duplicate rejection and changed source digests.
- **CC-100 / SDK-CONNECTOR-CONTROL-R054.2:** Planned `tests/test_json_tag_loader_migration_served.py::test_registered_operations_match_source_schemas` detects missing loaders, hidden dynamic paths, unmapped operations and every schema/tag difference.
- **CC-101 / SDK-CONNECTOR-CONTROL-R054.3:** Planned `tests/test_json_tag_loader_migration_served.py::test_tools_list_and_call_reach_backend` enters the served wire methods and observes the controlled backend.
- **CC-102 / SDK-CONNECTOR-CONTROL-R054.4:** Planned `tests/test_json_tag_loader_migration_served.py::test_denied_malformed_and_unknown_calls_have_zero_effects` covers each refusal on both source and replacement servers.
- **CC-103 / SDK-CONNECTOR-CONTROL-R054.5:** Planned `tests/test_json_tag_loader_migration_served.py::test_parity_receipt_reconstructs_from_digests` repeats the fixture and compares canonical receipts after excluding declared observation timestamps.
- **CC-104 / SDK-CONNECTOR-CONTROL-R054.6:** The served transport, registration, authorization, dispatch and controlled backend must all participate. Helper-only or import-scan-only checks cannot satisfy this row.

These are required future tests. None ran during definition authoring.
<!-- /spec-definition-patch -->

<!-- spec-definition-patch:sdk-consolidated-r054-root-test-20261012 -->

- **CC-80 / SDK-CONNECTOR-CONTROL-R054:** Compare every inventory entry with its served Python surface. Cover each parity and refusal child. Require independent readback before completion.
<!-- /spec-definition-patch -->

<!-- spec-definition-patch:sdk-consolidated-r054-binding-marker-20261012 -->

<!-- # spec: SDK-CONNECTOR-CONTROL-R054; planned acceptance link only. -->
<!-- /spec-definition-patch -->

<!-- spec-definition-patch:sdk-consolidated-trailer-bindings-20261012 -->
<!-- # spec: SDK-CONNECTOR-CONTROL-R051; planned acceptance link only; proposed CC-81 through CC-86. -->
<!-- # spec: SDK-CONNECTOR-CONTROL-R052; planned acceptance link only; proposed CC-87 through CC-92. -->
<!-- # spec: SDK-CONNECTOR-CONTROL-R053; planned acceptance link only; proposed CC-93 through CC-98. -->
<!-- /spec-definition-patch -->

<!-- spec-definition-patch:sdk-confirmation-r026-1 -->
## One tool per API operation (SDK-CONNECTOR-CONTROL-R020, R026, R032)

- SDK-CONNECTOR-CONTROL-R020: `tests/test_operation_tools.py::test_default_surface_is_one_typed_annotated_tool_per_operation` serves a sample client with GET, POST, PUT and DELETE operations through `tools/list`. It checks the tool count, names, typed required fields, descriptions and verb annotations. `test_action_dispatch_is_opt_in_compatibility` proves only the opt-in keeps action-dispatch tools. `tests/test_tool_surface.py::test_client_registers_operations_and_retires_action_tools` proves the default drops them. `test_manifest_supplies_schema_name_description_and_verb` covers the OpenAPI manifest path.
- SDK-CONNECTOR-CONTROL-R026: `tests/test_method_tools.py` proves per-method derivation, typed dispatch, base-infrastructure exclusion, destructive confirmation and asynchronous client resolution.
- SDK-CONNECTOR-CONTROL-R032: `tests/test_tool_surface.py::test_verbose_register_runs_alongside_condensed` and `test_verbose_register_name_collision_with_condensed_rejected` prove callback-last ordering and collision refusal.

## Destructive MCP confirmation compatibility (SDK-CONNECTOR-CONTROL-R026.1)

- CC-107 / SDK-CONNECTOR-CONTROL-R026.1: `tests/test_mcp_confirmation_roundtrip.py::test_served_destructive_confirmation_never_bypasses_gate` calls both dispatch paths through served `tools/call`. Run auto 2026-07-28 and legacy 2025-11-25 sessions. Record FastMCP 4.0.11 and MCP 2.3.0. Explicit acceptance yields one HTTPX MockTransport effect. False, truthy-false, nonboolean, decline, cancel, missing content, or elicitation failure yields zero effects.
- CC-108 / SDK-CONNECTOR-CONTROL-R026.1: `tests/test_mcp_confirmation_roundtrip.py::test_legacy_boolean_guard_fails_closed_on_pending_modern_confirmation` runs as a served modern tool. Use the old `if not await` guard. Confirm pending confirmation raises before elicitation or backend effect.
- CC-109 / SDK-CONNECTOR-CONTROL-R026.1: `tests/test_mcp_confirmation_roundtrip.py::test_nondestructive_served_call_does_not_request_confirmation` runs a nondestructive `tools/call` in both client modes and dispatch paths. Confirm it reaches the controlled backend without elicitation.
- CC-110 / SDK-CONNECTOR-CONTROL-R026.1: `tests/test_mcp_confirmation_roundtrip.py::test_missing_or_unversioned_context_denies_before_provider_effect` proves those contexts cancel before the controlled backend. Record package versions from live request context. Helper-only tests cannot satisfy CC-107.

## Keyword-named manifest fields (SDK-CONNECTOR-CONTROL-R026.2)

- SDK-CONNECTOR-CONTROL-R026.2: `tests/test_operation_tools.py::test_keyword_field_is_exposed_under_its_wire_name` registers a manifest with `from` and `in` fields. The listed schema shows `from` and `in`, `in` stays required, and a served call delivers `from_` and `in_` to the client.
<!-- /spec-definition-patch -->


## API-key cookie isolation acceptance

- **CC-111 / R028.3:** Run the sync case at tests/test_http_client.py::test_api_key_client_isolates_cookies_across_response_statuses. Run the async case at tests/test_http_client.py::test_async_api_key_client_isolates_cookies_across_response_statuses. Seed the HTTPX jar and add explicit Cookie headers. Return Set-Cookie with 302 login, 307 redirect, 500 error, and 200 success responses. Assert requests omit Cookie and responses omit Set-Cookie. Confirm the jar stays empty and the configured x-api-key remains. Confirm status and Location stay unchanged. Confirm the client never follows the redirect.
- **CC-112 / R028.3:** Run tests/test_http_client.py::test_async_api_key_client_isolates_concurrent_callers. Block the responder until both callers send requests through one shared API-key client. Assert explicit and jar-seeded cookies reach neither request. Confirm responses cannot seed the shared cookie jar.
- **CC-113 / R028.3:** Run tests/test_http_client.py::test_non_api_key_client_preserves_existing_cookie_behavior. Confirm the Bearer client retains its existing HTTPX cookie-jar behavior. Keep the existing TLS, origin, redirect, and retry tests.
- **CC-114 / R028.3:** Run downstream acceptance through real modern MCP tools/call. Pin the immutable SDK commit and use a controlled provider transport. Exercise login and finishOAuth before protected calls. Repeat through two distinct MCP clients that share one API-key HTTP client. Assert every provider call carries no Cookie and uses the configured API key. Make no live provider or credential calls.

## Declared auth client factory acceptance

- **CC-115 / R028.4:** Run tests/test_auth_declarations.py against stub servers. Cover Bearer, ApiKey (header and query), Basic and SessionLogin shapes. Assert a 401 after a rotated secret retries once and an unchanged secret does not. Assert ClientCredentials and RefreshToken refresh before expiry, re-mint once on a 401 and keep a rotated refresh token. Assert a CA bundle is trusted only through the declared TLS name. Assert no secret appears in repr, log records or errors, and an incomplete declaration raises AuthConfigurationError.

## JSON loader served acceptance matrix

Seed 5489 must create two isolated servers and controlled backends for each inventory entry.
The fixture must preserve the pinned source JSON, declared Python target and identical operation inputs.
Compare tools/list names, normalized schemas and tags before tools/call.
Run every mapped operation, including each default and explicitly enabled registration kind.
Record results and backend counts independently of the client response.
A permitted call must reach its backend once; each refused call must reach it zero times.
Negative cases include unknown operation, malformed input, denied caller, unsupported mode, name collision and schema mismatch.
Run destructive acceptance and decline on both action and per-method dispatch paths under R026.1.
A dynamically resolved or unreadable loader must remain unresolved and block the gate.
Removing a source operation or changing a schema, tag or refusal must fail the parity comparison.
Repeat the seed and compare canonical receipts after excluding only declared observation timestamps.
Missing source fixtures must fail; import scans and mocked dispatch alone cannot prove served acceptance.

Every comparison must name the exact source_operation_id, target_operation_id and target_registration from the inventory.
Duplicate source or target mappings and unpaired schema/refusal evidence must fail reconstruction.

## SDK environment declaration acceptance

Seed 53 must pin SDK and Arbora package revisions and all source census inputs.
Import environment_declarations through the installed public config module.
List every SDK literal reader and each explicit dynamic binding independently of the exporter.
Test unknown files, aliases, missing bindings, duplicate names, conflicting defaults and unsupported conditions.
Test inherited-environment forwarding with a complete downstream binding and with an unresolved edge.
A missing export must refuse; it must never produce an empty successful manifest fragment.
Assert that EnvironmentDeclarationError carries a refused receipt and no declarations.
Every available export must have outcome available and no unresolved call sites.
Shuffle file and binding order and compare canonical rows, declaration digests and census digests.
Inject distinct secret canaries through process configuration and credential references.
Assert none appears in exported rows, receipts, errors, logs or diagnostic output.
Safe static defaults and null must retain the host schema's exact meaning.

The served fixture must run the real Arbora launcher with the installed SDK export and controlled remaining owner manifests.
Valid enabled components must start and serve a probe.
Missing required settings, malformed values and unresolved declarations must open zero listeners and start zero children.
Enable and disable the same conditional component; only the enabled case must require its credential.
Denied startup must retain component, input name and typed reason without the value.
Record host and SDK revisions, fixture seed, manifest and census digests, process exit and independently observed effect counts.
The host records its own decision; the SDK export receipt supplies no startup authority.
Missing host or AU producer implementation keeps the corresponding served acceptance pending.

## Connector runtime utilities moved from agent-utilities (R014.2-R014.23)

- `SDK-CONNECTOR-CONTROL-R014.2`: `tests/test_connector_runtime_from_au.py::test_r014_2_file_lock_exclusive_and_nonblocking` holds a lock, proves a second descriptor is refused, then acquires it after release.
- `SDK-CONNECTOR-CONTROL-R014.3`: `test_r014_3_tool_version_stamps_async_tool`.
- `SDK-CONNECTOR-CONTROL-R014.4`: `test_r014_4_runtime_secret_references` covers resolution, refusal, non-disclosure and the argparse action.
- `SDK-CONNECTOR-CONTROL-R014.5`: `test_r014_5_validate_base_url` covers literal and resolved refusal and loopback control.
- `SDK-CONNECTOR-CONTROL-R014.6`: `test_r014_6_pii_sanitizer_redacts`.
- `SDK-CONNECTOR-CONTROL-R014.7`: `test_r014_7_paths_honour_overrides`.
- `SDK-CONNECTOR-CONTROL-R014.8`: `test_r014_8_delegation_helpers`.
- `SDK-CONNECTOR-CONTROL-R014.9`: `test_r014_9_no_credential`.
- `SDK-CONNECTOR-CONTROL-R014.10`: `tests/test_connector_runtime_adds.py::test_r014_10_token_auth_envelope_and_error_mapping` and `test_r014_10_auth_strategies_and_retries` cover the header token, envelope, error mapping, redaction, destructive gate, 429 backoff, 401 refresh and TLS-override refusal.
- `SDK-CONNECTOR-CONTROL-R014.11`: `tests/test_connector_runtime_adds.py::test_r014_11_browser_auth_pkce_store_and_refresh` covers the S256 challenge, the 0600 store, the proactive refresh and the API-key override.
- `SDK-CONNECTOR-CONTROL-R014.12`: `tests/test_connector_runtime_adds.py::test_r014_12_graphql_helpers_sync_async_and_failure`.
- `SDK-CONNECTOR-CONTROL-R014.13`: `tests/test_connector_runtime_adds.py::test_r014_13_external_access_descriptor`.
- `SDK-CONNECTOR-CONTROL-R014.14`: `tests/test_connector_runtime_adds.py::test_r014_14_env_drift_against_declarations` builds a connector with each read and declaration kind and checks the exact findings and the `--check` exit.
- `SDK-CONNECTOR-CONTROL-R014.15`: `tests/test_document_sources.py::test_connector_ingestion_syncs_external_acl` ingests a restricted file and a quarantined one. It asserts the committed access properties and that no local path is persisted.
- `SDK-CONNECTOR-CONTROL-R014.16`: `tests/test_http_dns_pinned_egress.py` covers pinned Host/SNI, private-resolution refusal, the private allow-list, loopback, plaintext, peer mismatch, URL limits and allow-list validation.
- `SDK-CONNECTOR-CONTROL-R014.17`: `tests/test_base_install_mcp_free.py` imports the base modules with `fastmcp` and `mcp` blocked and checks the MCP surface names the extra.
- `SDK-CONNECTOR-CONTROL-R014.18`: `tests/test_served_security_and_provider_profile.py::test_r014_18_*` cover refusal without auth or audience and the middleware's identity/tenant/ACL/session cases. They also cover default application by `create_mcp_server`, the logged override and the static tenant claim.
- `SDK-CONNECTOR-CONTROL-R014.19`: `tests/test_served_security_and_provider_profile.py::test_r014_19_*` cover resolution, close, every failure code and every invalid document.
- `SDK-CONNECTOR-CONTROL-R014.20`: `tests/test_served_security_and_provider_profile.py::test_r014_20_entry_point_groups_use_the_sdk_namespace`.
- `SDK-CONNECTOR-CONTROL-R014.22`: `tests/test_embeddings.py` covers `openai` and `ollama` provider requests, sub-batching and bearer auth from a reference. It also covers body non-disclosure, invalid settings, caching per endpoint and the DNS-pinned no-redirect client.
- `SDK-CONNECTOR-CONTROL-R014.23`: `tests/test_compute_adapter.py` covers SPARQL algorithm selection and the served run. It also covers refusal of unbound analyses and unserved methods and IRI and client-path validation. It covers the unavailable endpoint and the compute-only scopes.
- `SDK-CONNECTOR-CONTROL-R014.25`: `tests/test_connector_runtime_adds.py::test_r014_25_sdk_consumed_env_not_dead` declares the TLS profile variables for a connector that reads none. It expects no finding. A non-SDK variable stays `DEAD`.
- `SDK-CONNECTOR-CONTROL-R014.26`: `tests/test_connector_runtime_adds.py::test_r014_26_parser_settings_not_dead` declares parser settings for a connector that reads none. It expects no finding.

## Connector packs authored as Turtle (R067)

- `SDK-CONNECTOR-CONTROL-R067`: Rollup closes when every child `.1` to `.8` passes its proving test.
- `SDK-CONNECTOR-CONTROL-R067.1`: `tests/test_pack_declaration.py::test_declaration_round_trip_and_nested_property_refusal`.
- `SDK-CONNECTOR-CONTROL-R067.2`: `tests/test_pack_turtle.py::test_emit_is_deterministic_and_uses_engine_terms`.
- `SDK-CONNECTOR-CONTROL-R067.3`: `tests/test_pack_declaration.py::test_views_render_and_fingerprint_id_is_sdk_owned`.
- `SDK-CONNECTOR-CONTROL-R067.4`: `tests/test_pack_turtle.py::test_preflight_uses_engine_validation`.
- `SDK-CONNECTOR-CONTROL-R067.5`: `tests/test_pack_turtle.py::test_content_pack_carries_contract_entry`.
- `SDK-CONNECTOR-CONTROL-R067.6`: `tests/test_pack_declaration.py::test_declaration_refusals_name_the_field`.
- `SDK-CONNECTOR-CONTROL-R067.7`: `tests/test_pack_declaration.py::test_certification_records_accepted_contract_digest`.
- `SDK-CONNECTOR-CONTROL-R067.8`: `tests/test_pack_rdf_served.py::test_declaration_to_engine_pack_end_to_end`.

## SDK-CONNECTOR-CONTROL-R068 acceptance

| Case | Row | Proving test and observation |
|---|---|---|

| Model | `SDK-CONNECTOR-CONTROL-R068.1` | `tests/test_seed_graph.py::test_seed_declaration_round_trips`: A round trip keeps every field and refuses a blank instance IRI. |

| Behavior | `SDK-CONNECTOR-CONTROL-R068.2` | `tests/test_seed_graph.py::test_seed_turtle_is_deterministic`: Two emissions of one declaration are byte-identical, with one digest per part. |

| Wiring | `SDK-CONNECTOR-CONTROL-R068.3` | `tests/test_seed_graph.py::test_server_registers_seed_and_notifies`: A served connector lists the seed resource, and a digest change sends one notification. |

| Refusal | `SDK-CONNECTOR-CONTROL-R068.4` | `tests/test_seed_graph.py::test_seed_refusals`: Each case raises its code, and no seed resource is served. |

| Evidence | `SDK-CONNECTOR-CONTROL-R068.5` | `tests/test_seed_graph.py::test_resource_metadata_carries_digest`: The resource metadata digest equals the digest of the body. |

| Hot-path proof | `SDK-CONNECTOR-CONTROL-R068.6` | `tests/test_seed_graph_served.py::test_connector_serves_contract_resources_and_notifies`: The client reads all three resource kinds, and the change sends one notification with a new seed digest. |


Hot-path proof for `SDK-CONNECTOR-CONTROL-R068`: `tests/test_seed_graph_served.py::test_connector_serves_contract_resources_and_notifies`.

## SDK-CONNECTOR-CONTROL-R069 acceptance

| Case | Row | Proving test and observation |
|---|---|---|

| Model | `SDK-CONNECTOR-CONTROL-R069.1` | `tests/test_transport_contract.py::test_transport_contract_round_trips`: A round trip keeps every field and refuses an unknown protocol or pushdown value. |

| Behavior | `SDK-CONNECTOR-CONTROL-R069.2` | `tests/test_transport_contract.py::test_registry_one_transport_per_protocol`: The registry holds one transport per protocol, and a stream contract with a filter refuses. |

| Wiring | `SDK-CONNECTOR-CONTROL-R069.3` | `tests/test_transport_contract.py::test_certification_checks_registry`: Certification of a pack reaches the registry check. |

| Refusal | `SDK-CONNECTOR-CONTROL-R069.4` | `tests/test_transport_contract.py::test_transport_refusals`: Each case refuses with its code. |

| Evidence | `SDK-CONNECTOR-CONTROL-R069.5` | `tests/test_transport_contract.py::test_certification_records_matrix`: The certification file lists every declared protocol with its transport module. |

| Hot-path proof | `SDK-CONNECTOR-CONTROL-R069.6` | `tests/test_transport_contract_served.py::test_declared_transports_serve_virtual_reads`: Each read returns rows through its declared transport, and the engine records the protocol. |


Hot-path proof for `SDK-CONNECTOR-CONTROL-R069`: `tests/test_transport_contract_served.py::test_declared_transports_serve_virtual_reads`.
- `SDK-CONNECTOR-CONTROL-R780.1` to `SDK-CONNECTOR-CONTROL-R780.5`: `tests/test_au_helper_parity.py` (5 tests).
- `SDK-CONNECTOR-CONTROL-R780.7`: `tests/test_http_airgap.py` covers both governed HTTP clients and refusal before transport.
- `SDK-CONNECTOR-CONTROL-R780.8`: `tests/test_http_standard_headers.py` checks standard headers and caller overrides on the transport path.
- `SDK-CONNECTOR-CONTROL-R780.10`: `tests/test_async_resilience.py` checks the callable retry and refusal paths.
- `SDK-CONNECTOR-CONTROL-R780.9`: `tests/test_http_requests.py` covers Requests TLS, timeout, headers and air-gap redirects.
- `SDK-CONNECTOR-CONTROL-R780.11`: `tests/test_sync_resilience.py` checks blocking callable retries and refusal paths.
- `SDK-CONNECTOR-CONTROL-R780.12`: `tests/test_explicit_env_expansion.py` checks explicit values and defaults.
- `SDK-CONNECTOR-CONTROL-R781`: `tests/test_trajectory_recorder.py`.
- `SDK-CONNECTOR-CONTROL-R014.21.1`: `tests/test_a2a_protocol.py` streams oversized card, send and poll replies, and refuses compressed replies before reading.
- `SDK-CONNECTOR-CONTROL-R014.21.2`: A future served test exercises the optional A2A app with the caller's broker and storage.
- `SDK-CONNECTOR-CONTROL-R782`: `tests/test_stream_adapter.py`.

## SDK-CONNECTOR-CONTROL-R070

`tests/test_current_plan.py` uses synthetic JSON and Python values. Positive cases cover available empty/populated snapshots, all statuses, unavailable/null and ordered JSON round trips. Negative cases cover unknown authority fields, scalar coercion, negative/bool revisions, invalid statuses, empty/oversized IDs, naive/non-UTC/reversed timestamps, availability mismatch and malformed nested instances. Frozen tuples and model fields refuse mutation. These tests require no server, engine or model call.

## SDK-CONNECTOR-CONTROL-R071

`tests/test_connector_identity.py` resolves the name from a fake entry-point table and from a `pyproject.toml`. It checks the refusal of zero, duplicate and invalid names. It builds both `for_package` constructors under one name. It checks the refusal of content that disagrees with its manifest.

## SDK-CONNECTOR-CONTROL-R019.1

`tests/test_connector_run.py` builds a fixture connector distribution (installed metadata, package, content) and starts it through `build_server` and `run`. It checks the served tools, skills, prompts, ontology and `connector://resources`, the metadata version, each transport and the unknown-transport refusal.

## SDK-CONNECTOR-CONTROL-R019.2

`tests/test_connector_hooks.py` declares each bootstrap hook on the fixture connector and builds it with `build_server`. It lists the tools for `tool_registry` with its declared tag and toggle. It lists the per-action tools of `action_tools` with a declared prefix, a default prefix and the toggle off. It lists a decorated and a plain inline tool. It requests the declared route and `/ready` for a ready, a down and a raising probe. The raising probe's message never appears in the response. It reads every `RegistrationContext` field and serves content from `content_root`. The SDK refuses reserved, relative and repeated routes and escaping content roots. It also refuses `tools` with `tool_registry` and `action_prefixes` without `action_tools`. `tests/test_ingest_strategies.py` runs `ingest_registration` with a `RegistrationContext`.

## SDK-CONNECTOR-CONTROL-R019.3

`tests/test_connector_hooks.py` parses interpolated and absolute config mount sources from a `pyproject.toml` table. It refuses a non-list field, relative or escaping paths, a target outside `/etc`, an extra key, a non-string value and a repeated target. It reads the schema's required keys. The `config_mounts` conformance check passes for the fixture and fails for a mount on `/`.

## SDK-CONNECTOR-CONTROL-R071.1

`tests/test_connector_run.py` resolves content directories and the installed declaration for a fixture with one entry point. `tests/test_conformance_plugin.py` rejects a removed provider group.

## SDK-CONNECTOR-CONTROL-R071.2

`tests/test_connector_run.py` reads the distribution, connector and server versions from metadata and refuses an uninstalled distribution. `tests/test_conformance_plugin.py` rejects a module that spells `__version__`.

## SDK-CONNECTOR-CONTROL-R072

`tests/test_certify_connector_rename.py` gives the fixture fingerprints an older connector name. `--check` refuses the checkout. `--write` rewrites the name from the manifest, and `--check` then passes.

## Never-drop splitter, successor parity and actor forwarding (R020.3, R020.4, R902)

- `SDK-CONNECTOR-CONTROL-R020.3`: `tests/test_action_split.py::test_router_actions_remain_served` registers a router with three actions and a router with unlistable actions. It calls all four tools over MCP and asserts the split report records the retained router and its reason.
- `SDK-CONNECTOR-CONTROL-R020.5`: `tests/test_action_split.py` splits a router and asserts parent and per-action inheritance. A purge action never inherits a read class and still raises. A stray tool is unclassified.
- `SDK-CONNECTOR-CONTROL-R020.4`: `tests/test_successor_tool_parity.py` compares a predecessor and a successor tool list. It asserts kept, split and covered outcomes, and a refusal for one lost tool.
- `SDK-CONNECTOR-CONTROL-R902`: The rollup holds when its six children hold.
- `SDK-CONNECTOR-CONTROL-R902.1`: A unit test reads the flag from a fixture manifest.
- `SDK-CONNECTOR-CONTROL-R902.2`: Tests cover one actor-required call and one ordinary call.
- `SDK-CONNECTOR-CONTROL-R902.3`: A served test calls an actor-required tool with a forwarded token and reads the subject.
- `SDK-CONNECTOR-CONTROL-R902.4`: A served test asserts each refusal and no upstream call.
- `SDK-CONNECTOR-CONTROL-R902.5`: A test reads the trace event and asserts no token.
- `SDK-CONNECTOR-CONTROL-R902.6`: `tests/test_actor_forwarding_served.py::test_actor_required_tool_binds_forwarded_user` passes.

Hot-path proof for `SDK-CONNECTOR-CONTROL-R902`: `tests/test_actor_forwarding_served.py::test_actor_required_tool_binds_forwarded_user`.
- `SDK-CONNECTOR-CONTROL-R030.1`: `tests/test_graphql_client.py` passes. It covers auth headers, bounded retry, redaction, pagination and the async call.

- `SDK-CONNECTOR-CONTROL-R074`: See each child.
- `SDK-CONNECTOR-CONTROL-R074.1`: `tests/test_resource_descriptor.py::test_descriptor_round_trips_and_names_only_a_credential_reference` builds a descriptor, serialises it and reads it back.
- `SDK-CONNECTOR-CONTROL-R074.2`: `tests/test_prompt_role.py::test_prompt_role_and_concepts_reach_the_pack_entry` packs a `system` prompt and reads `role` and the class IRIs from the entry.
- `SDK-CONNECTOR-CONTROL-R074.3`: `tests/test_pack_surfaces.py::test_pack_lists_all_surfaces_and_contract` builds a fixture pack and reads six counts and one contract from the manifest.
- `SDK-CONNECTOR-CONTROL-R074.4`: `tests/test_pack_surfaces.py::test_live_resource_listing_equals_pack_descriptors` compares `resources/list` with the pack entries.
- `SDK-CONNECTOR-CONTROL-R074.5`: `tests/test_resource_descriptor.py::test_build_refuses_unmapped_unknown_unpaged_and_secret_descriptors` asserts each of the four codes.
- `SDK-CONNECTOR-CONTROL-R074.6`: `tests/test_pack_surfaces_served.py::test_factory_serves_and_packs_every_surface_with_a_parseable_contract`.
- `SDK-CONNECTOR-CONTROL-R074.7`: `tests/test_resource_declarations.py::test_real_connector_repos_list_yields_a_proposed_resource` derives the github-agent repository list. `tests/test_resource_declarations.py::test_scaffolded_connector_serves_derived_resources` reads the served `manifest://connector/resources`.
- `SDK-CONNECTOR-CONTROL-R075`: See each child.
- `SDK-CONNECTOR-CONTROL-R075.1`: `tests/test_single_declaration.py::test_server_serves_declaration_live_and_runner_reads_only_that` lists `connector://resources` as the only resource of a declared server.
- `SDK-CONNECTOR-CONTROL-R075.2`: `tests/test_single_declaration.py::test_build_declaration_maps_meta_without_any_file`, `::test_connector_sources_module_declares_by_tool_name`, `tests/test_source_sync.py::test_tool_surface_serves_declarations` and `tests/test_for_each.py::test_for_each_is_in_the_served_schema`.
- `SDK-CONNECTOR-CONTROL-R075.3`: `tests/test_single_declaration.py::test_declared_connector_must_match_descriptor`, `::test_server_without_a_sync_preset_is_refused` and `::test_certify_reads_the_declaration_and_checks_tools_live`.
- `SDK-CONNECTOR-CONTROL-R075.4`: `tests/test_single_declaration.py::test_prompt_serves_its_directive_and_carries_metadata_over_mcp`.
- `SDK-CONNECTOR-CONTROL-R075.5`: `tests/test_single_declaration.py::test_skill_directory_name_matches_frontmatter_name`.
- `SDK-CONNECTOR-CONTROL-R075.6`: `tests/test_ingest.py::test_change_set_maps_to_exact_declared_references`.
- `SDK-CONNECTOR-CONTROL-R075.7`: `tests/test_pack_resource_schema.py::test_pack_satisfies_engine_resource_schema_rule`. `tests/test_eg_pack_entry_kinds.py` proves the SDK against the engine floor. Its tests are `test_every_sdk_module_imports_against_the_engine`, `test_every_mapped_entry_kind_exists_in_the_engine`, `test_a_manifest_resource_has_no_pack_entry_kind` and `test_a_pack_builds_against_the_engine`.

- **R028.1 pinned TLS identity:** Run `tests/test_http_egress.py::test_pinned_transport_verifies_original_tls_hostname`. A local TLS server presents a certificate for localhost. A request to a different logical hostname fails even when the caller supplies localhost as SNI. A request to localhost succeeds through the pinned address and retains its Host header.
- **R028.2 construction and pinning:** Run `tests/test_http_egress_construction.py`. Both factories refuse unsafe literal hosts before creating a transport. An allowed private host completes a real pinned request. DNS lookup occurs at request time.

- **R028.1 canonical loopback:** `tests/test_http_egress.py::test_loopback_hostname_canonicalization` refuses mixed-case and dotted localhost names unless the policy admits loopback or names that host. A different host is not covered by the exception.

- `SDK-CONNECTOR-CONTROL-R035.7`: `tests/test_credentials.py::test_openbao_ignores_ambient_proxy` and `tests/test_credentials.py::test_openbao_never_follows_redirects`.
# Tool schema estimate

R045.3 uses a captured tool's canonical body and checks byte boundaries and
non-ASCII text against the named divisor.

- **R039 external evidence:** The container-manager test
  `tests/test_access_contracts.py::test_served_deployment_access_contract_matches_fixture`
  uses a synthetic Kubernetes provider and a real MCP tool call. Its owner
  repository merged commit `db08ad5123a1b12ef715d237d2d3aa6e49aac330` after
  green checks. This is not a local test binding or engine mapping proof.

- **R038 external evidence:** The uptime-kuma-agent test
  `tests/test_service_health.py::test_served_health_contract` calls the served
  MCP tool with a synthetic provider and checks its response and access
  contract. Owner merge `1915fce3ef886c82ce17edbf9cb0d92bdfe50dfb` passed
  its PR checks. This is not SDK-local evidence or engine mapping proof.

- **SDK-CONNECTOR-CONTROL-R650.1:** Future acceptance must bind the current
  live declaration and ontology to the signed release. Confirm signer-lock
  agreement, declared rotation, canonical signature encoding and rejection of
  environment-backed publication keys. The removed manifest tests do not
  establish this proof.

## Malformed Retry-After (SDK-CONNECTOR-CONTROL-R780.3)

`tests/test_http_units.py::test_retry_policy_decisions` checks malformed
non-ASCII digits and oversized ASCII values.
`tests/test_http_client.py::test_sync_transport_falls_back_for_non_ascii_retry_after`
checks bounded fallback through the governed transport.

## Tool pin coverage (SDK-CONNECTOR-CONTROL-R004.1)

`tests/test_artifacts_discovery.py::test_contract_pin_normalization_rejects_incomplete_tool_sets`
checks empty, missing, extra and duplicate captures against served MCP tools.
`tests/test_artifacts_discovery.py::test_contract_pin_normalization_rejects_duplicate_live_names`
checks duplicate names in the live response.

## Fleet scan completeness (R014.28)

The fleet scan test uses empty and missing roots, invalid bytes, symbolic
links and duplicate package names. It asserts that none can produce a clean
migration result. A separate test exercises invalid Python syntax.

R014.29 tests literal legacy names in common dynamic import forms, a nonliteral
name and a safe literal import. It does not claim coverage of all runtime calls.

R015.1 also checks incomplete duplicate scans. Invalid Python, unreadable
bytes, empty or missing roots and symbolic links do not report clean.

## Session cookie scope (R028.5)

An HTTPX client logs in once, then calls a matching and nonmatching path. The
test checks cookie path scope and refuses a second origin without dispatch.
Sync and async tests also refuse cross-origin redirects. Direct unguarded
HTTPX use refuses before login.

## Explicit TLS settings (R780.13)

Resolve a service-specific profile from an injected mapping. Conflicting
process settings do not alter the result, and an unknown profile refuses.

- `SDK-CONNECTOR-CONTROL-R035.8`: `tests/test_reference_invariants.py` refuses forged references before resolution.
- `SDK-CONNECTOR-CONTROL-R049.7`: `tests/test_payments.py::test_default_payment_budgets_deny_positive_challenges`.
