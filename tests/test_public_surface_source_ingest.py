"""Public surface of the source-ingest modules: every exported name resolves from its module."""

from __future__ import annotations

import importlib


def test__extras_exports() -> None:
    module = importlib.import_module("agent_connector_sdk._extras")
    exported = (module.require_mcp_extra,)
    assert len(exported) == 1
    assert all(item is not None for item in exported)


def test_adapters_document_sources_exports() -> None:
    module = importlib.import_module("agent_connector_sdk.adapters.document_sources")
    exported = (
        module.DEFAULT_TEXT_EXTENSIONS,
        module.DocumentGovernance,
        module.DocumentIngestReport,
        module.DocumentSource,
    )
    assert len(exported) == 4
    assert all(item is not None for item in exported)


def test_auth_browser_exports() -> None:
    module = importlib.import_module("agent_connector_sdk.auth.browser")
    exported = (
        module.BaseLoopbackCallbackHandler,
        module.BaseLoopbackCallbackServer,
        module.TokenStore,
    )
    assert len(exported) == 3
    assert all(item is not None for item in exported)


def test_credentials_provider_profile_exports() -> None:
    module = importlib.import_module("agent_connector_sdk.credentials.provider_profile")
    exported = (module.ResolvedProviderProfile,)
    assert len(exported) == 1
    assert all(item is not None for item in exported)


def test_data_prep_exports() -> None:
    module = importlib.import_module("agent_connector_sdk.data_prep")
    exported = (
        module.STEP_VERBS,
        module.ArrowAdapter,
        module.ArrowTypeName,
        module.CanonicalNames,
        module.CleanStep,
        module.ColumnName,
        module.ColumnProfile,
        module.DataPrepDependencyError,
        module.DataPrepError,
        module.Dedupe,
        module.Digest,
        module.FillNulls,
        module.InvalidRowDisposition,
        module.LocalProfile,
        module.NullPolicy,
        module.OpaqueReference,
        module.PrepResult,
        module.ProfileClient,
        module.ProfileDeadlineError,
        module.ProfileEvidenceAuthority,
        module.ProfileProtocolError,
        module.ProfileScalar,
        module.ProfileTarget,
        module.ProfileTargetKind,
        module.ProfileWarningCode,
        module.QuantilePoint,
        module.QuarantineOutcome,
        module.RegisteredRowModel,
        module.RowOutcome,
        module.SafeCast,
        module.ScalarValue,
        module.SchemaVersion,
        module.StepEvidence,
        module.TopKEntry,
        module.validate_engine_profile,
    )
    assert len(exported) == 35
    assert all(item is not None for item in exported)


def test_data_prep__base_exports() -> None:
    module = importlib.import_module("agent_connector_sdk.data_prep._base")
    exported = (module.ProtocolModel,)
    assert len(exported) == 1
    assert all(item is not None for item in exported)


def test_data_prep_certification_exports() -> None:
    module = importlib.import_module("agent_connector_sdk.data_prep.certification")
    exported = (
        module.CertificationAdapter,
        module.CertificationBackend,
        module.CertificationResult,
        module.CertificationSigner,
        module.CertificationState,
        module.FailureCode,
        module.PanderaAdapter,
        module.SignedResultSummary,
        module.mark_not_requested,
    )
    assert len(exported) == 9
    assert all(item is not None for item in exported)


def test_data_prep_certification_models_exports() -> None:
    module = importlib.import_module(
        "agent_connector_sdk.data_prep.certification.models"
    )
    exported = (
        module.OpaqueRef,
        module.Signature,
    )
    assert len(exported) == 2
    assert all(item is not None for item in exported)


def test_http_egress_exports() -> None:
    module = importlib.import_module("agent_connector_sdk.http.egress")
    exported = (
        module.AsyncDnsPinnedEgressTransport,
        module.DnsPinnedEgressTransport,
        module.EgressDecision,
    )
    assert len(exported) == 3
    assert all(item is not None for item in exported)


def test_http_support_exports() -> None:
    module = importlib.import_module("agent_connector_sdk.http.support")
    exported = (
        module.DEFAULT_ERROR_MAP,
        module.DEFAULT_MAX_RETRIES_429,
    )
    assert len(exported) == 2
    assert all(item is not None for item in exported)


def test_httpsupport_client_protocol_exports() -> None:
    module = importlib.import_module("agent_connector_sdk.httpsupport.client_protocol")
    exported = (
        module.AsyncHttpClient,
        module.HttpClient,
        module.HttpConnectError,
        module.HttpProtocolError,
        module.HttpResponse,
        module.HttpTimeoutError,
        module.HttpTooManyRedirectsError,
        module.HttpTransportError,
        module.map_transport_error,
        module.normalize_response,
    )
    assert len(exported) == 10
    assert all(item is not None for item in exported)


def test_httpsupport_rate_limit_exports() -> None:
    module = importlib.import_module("agent_connector_sdk.httpsupport.rate_limit")
    exported = (module.DEFAULT_RETRY_AFTER_CAP_S,)
    assert len(exported) == 1
    assert all(item is not None for item in exported)


def test_httpsupport_redaction_exports() -> None:
    module = importlib.import_module("agent_connector_sdk.httpsupport.redaction")
    exported = (module.contains_secret,)
    assert len(exported) == 1
    assert all(item is not None for item in exported)


def test_mcp_env_drift_exports() -> None:
    module = importlib.import_module("agent_connector_sdk.mcp.env_drift")
    exported = (
        module.FRAMEWORK_ENV,
        module.RUNTIME_ALLOWLIST,
        module.framework_dynamic_families,
    )
    assert len(exported) == 3
    assert all(item is not None for item in exported)


def test_mcp_graphql_exports() -> None:
    module = importlib.import_module("agent_connector_sdk.mcp.graphql")
    exported = (
        module.GET_TYPE_DETAILS_QUERY,
        module.LIST_TYPES_QUERY,
        module.graphql_failure_payload,
    )
    assert len(exported) == 3
    assert all(item is not None for item in exported)


def test_mcp_served_security_exports() -> None:
    module = importlib.import_module("agent_connector_sdk.mcp.served_security")
    exported = (module.SERVED_TRANSPORTS,)
    assert len(exported) == 1
    assert all(item is not None for item in exported)


def test_paths_exports() -> None:
    module = importlib.import_module("agent_connector_sdk.paths")
    exported = (
        module.cache_dir,
        module.config_dir,
    )
    assert len(exported) == 2
    assert all(item is not None for item in exported)


def test_source_connectors_exports() -> None:
    module = importlib.import_module("agent_connector_sdk.source_connectors")
    exported = (
        module.BaseSourceConnector,
        module.CheckpointedBatch,
        module.PermSyncConnector,
        module.SlimConnector,
        module.SlimDocument,
        module.SourceDocument,
        module.get_connector_class,
        module.register_source,
    )
    assert len(exported) == 8
    assert all(item is not None for item in exported)


def test_source_connectors_connectors_arxiv_exports() -> None:
    module = importlib.import_module(
        "agent_connector_sdk.source_connectors.connectors.arxiv"
    )
    exported = (module.ArxivConnector,)
    assert len(exported) == 1
    assert all(item is not None for item in exported)


def test_source_connectors_connectors_package_manifest_exports() -> None:
    module = importlib.import_module(
        "agent_connector_sdk.source_connectors.connectors.package_manifest"
    )
    exported = (
        module.ONYX_CONNECTOR_PARITY,
        module.PACKAGE_PRESETS,
        module.get_preset,
        module.list_presets,
        module.onyx_parity,
        module.onyx_parity_summary,
    )
    assert len(exported) == 6
    assert all(item is not None for item in exported)


def test_source_connectors_connectors_rest_exports() -> None:
    module = importlib.import_module(
        "agent_connector_sdk.source_connectors.connectors.rest"
    )
    exported = (module.RestJsonConnector,)
    assert len(exported) == 1
    assert all(item is not None for item in exported)


def test_source_connectors_connectors_rss_exports() -> None:
    module = importlib.import_module(
        "agent_connector_sdk.source_connectors.connectors.rss"
    )
    exported = (module.RssConnector,)
    assert len(exported) == 1
    assert all(item is not None for item in exported)


def test_source_connectors_connectors_web_exports() -> None:
    module = importlib.import_module(
        "agent_connector_sdk.source_connectors.connectors.web"
    )
    exported = (module.WebCrawlerConnector,)
    assert len(exported) == 1
    assert all(item is not None for item in exported)


def test_source_connectors_http_safety_exports() -> None:
    module = importlib.import_module(
        "agent_connector_sdk.source_connectors.http_safety"
    )
    exported = (
        module.DEFAULT_MAX_REDIRECTS,
        module.DEFAULT_MAX_REQUEST_BYTES,
        module.HARD_MAX_REDIRECTS,
        module.HARD_MAX_RESPONSE_BYTES,
        module.ResolvedSourceURL,
        module.configured_source_http_policy,
        module.normalize_allowed_hosts,
        module.require_safe_source_url,
        module.resolve_safe_source_url,
        module.safe_delete_json,
        module.safe_get_bytes,
        module.safe_get_bytes_async,
        module.safe_get_json,
        module.safe_get_json_async,
        module.safe_get_text_async,
        module.safe_post_json_async,
        module.source_url_host,
    )
    assert len(exported) == 17
    assert all(item is not None for item in exported)


def test_voice_supply_chain_license_registry_exports() -> None:
    module = importlib.import_module(
        "agent_connector_sdk.voice_supply_chain.license_registry"
    )
    exported = (module.get_license_decision,)
    assert len(exported) == 1
    assert all(item is not None for item in exported)


def test_voice_supply_chain_manifest_exports() -> None:
    module = importlib.import_module("agent_connector_sdk.voice_supply_chain.manifest")
    exported = (
        module.HF_COMMIT_SHA_LEN,
        module.VoiceConfigManifest,
        module.VoiceModelProvider,
    )
    assert len(exported) == 3
    assert all(item is not None for item in exported)
