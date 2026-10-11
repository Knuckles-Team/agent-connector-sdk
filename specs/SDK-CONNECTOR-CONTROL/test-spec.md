# Test specification: connector control

| ID | Fixture/action | Required assertion |
|---|---|---|
| CC-01 | Construct synthetic connector with valid manifest and registered entry point | Discovery selects exact group/name/distribution/version and server identity; direct and entry-point construction agree. |
| CC-02 | Change input schema, output schema, entry-point version, or server identity one at a time | Certification refuses each mismatch before tool execution. |
| CC-03 | Publish same canonical pack twice through a fake generated client | Same idempotency key and result. Changed content yields new digest/key. |
| CC-04 | Feed duplicate entries, bad URI scheme, undeclared kind, literal credential, or oversized body | Deterministic named refusal. No pack call and no secret in output. |
| CC-05 | Request event/tool-choice proposal | Proposal can be logged and rejected; it cannot call write-back or grant an action. |
| CC-06 | Build wheel and install it in isolated environment with the locked published graph wheel | Generated DTO imports and client/pack calls work without source path overlays. |
| CC-07 | Scan every migrated connector batch | No runtime import or declared dependency on `agent_utilities`; SDK conformance suite and connector's own tests pass. |
| CC-08 | Submit one synthetic pack to a contributor-owned running graph service | Receipt binds tenant, connector, digest, and retry identity. Wrong tenant and stale contract pin refuse. |
| CC-09 | Submit SQL change page with generated SourceIngest client | Typed receipt binds table/key/schema/checkpoint and advances only on accepted result; mismatched tenant or schema refuses. |
| CC-10 | Certify an annotated multi-modal pack | Capability, schema digests, modality, cost/latency units and provenance round-trip. Missing estimate is unknown. Malformed annotation refuses. |

Pull requests run `uv sync`, focused `pytest`, Ruff, mypy, wiring checks, CCCC, jscpd, Dupehound, and KISS through the repository's reproducible hooks. CC-08 is an acceptance probe, not a cloud-PR prerequisite. A missing optional live environment records **NOT RUN** rather than silently passing or failing the source gate.

| ID | Fixture/action | Required assertion |
|---|---|---|
| CC-11 | Parse a fake connector ontology with one `ac:AccessContract` and one `ac:PropertyBinding` (SDK-CONNECTOR-CONTROL-R021) | The parser returns one typed contract and its `VirtualMapping` fields. It refuses a literal secret, an unknown pushdown, pagination or access kind, a missing operation, and a non-integer hint. No error text contains the secret. |
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
