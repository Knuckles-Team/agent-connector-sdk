"""Public surface of the source-ingest modules: every exported name resolves from its module."""

from __future__ import annotations

import importlib


def test__extras_exports() -> None:
    module = importlib.import_module("scion_sdk._extras")
    exported = (module.require_mcp_extra,)
    assert len(exported) == 1
    assert all(item is not None for item in exported)


def test_adapters_document_sources_exports() -> None:
    module = importlib.import_module("scion_sdk.adapters.document_sources")
    exported = (
        module.DEFAULT_TEXT_EXTENSIONS,
        module.DocumentGovernance,
        module.DocumentIngestReport,
        module.DocumentSource,
    )
    assert len(exported) == 4
    assert all(item is not None for item in exported)


def test_auth_browser_exports() -> None:
    module = importlib.import_module("scion_sdk.auth.browser")
    exported = (
        module.BaseLoopbackCallbackHandler,
        module.BaseLoopbackCallbackServer,
        module.TokenStore,
    )
    assert len(exported) == 3
    assert all(item is not None for item in exported)


def test_credentials_provider_profile_exports() -> None:
    module = importlib.import_module("scion_sdk.credentials.provider_profile")
    exported = (module.ResolvedProviderProfile,)
    assert len(exported) == 1
    assert all(item is not None for item in exported)


def test_http_egress_exports() -> None:
    module = importlib.import_module("scion_sdk.http.egress")
    exported = (
        module.AsyncDnsPinnedEgressTransport,
        module.DnsPinnedEgressTransport,
        module.EgressDecision,
    )
    assert len(exported) == 3
    assert all(item is not None for item in exported)


def test_http_support_exports() -> None:
    module = importlib.import_module("scion_sdk.http.support")
    exported = (
        module.DEFAULT_ERROR_MAP,
        module.DEFAULT_MAX_RETRIES_429,
    )
    assert len(exported) == 2
    assert all(item is not None for item in exported)


def test_mcp_env_drift_exports() -> None:
    module = importlib.import_module("scion_sdk.mcp.env_drift")
    exported = (
        module.FRAMEWORK_ENV,
        module.RUNTIME_ALLOWLIST,
        module.framework_dynamic_families,
    )
    assert len(exported) == 3
    assert all(item is not None for item in exported)


def test_mcp_graphql_exports() -> None:
    module = importlib.import_module("scion_sdk.mcp.graphql")
    exported = (
        module.GET_TYPE_DETAILS_QUERY,
        module.LIST_TYPES_QUERY,
        module.graphql_failure_payload,
    )
    assert len(exported) == 3
    assert all(item is not None for item in exported)


def test_mcp_served_security_exports() -> None:
    module = importlib.import_module("scion_sdk.mcp.served_security")
    exported = (module.SERVED_TRANSPORTS,)
    assert len(exported) == 1
    assert all(item is not None for item in exported)


def test_paths_exports() -> None:
    module = importlib.import_module("scion_sdk.paths")
    exported = (
        module.cache_dir,
        module.config_dir,
    )
    assert len(exported) == 2
    assert all(item is not None for item in exported)
