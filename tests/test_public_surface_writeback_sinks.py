"""Public surface of the write-back sinks: every exported name resolves from its module."""

from __future__ import annotations

import importlib


def test_writeback_sinks_exports() -> None:
    module = importlib.import_module("agent_connector_sdk.writeback_sinks")
    exported = (
        module.WritebackInvocation,
        module.WritebackSink,
        module.get_sink,
        module.list_sinks,
    )
    assert len(exported) == 4
    assert all(item is not None for item in exported)


def test_writeback_sinks__env_exports() -> None:
    module = importlib.import_module("agent_connector_sdk.writeback_sinks._env")
    exported = (
        module.runtime_dir,
        module.run_sync_isolated,
        module.stamp_bitemporal,
    )
    assert len(exported) == 3
    assert all(item is not None for item in exported)


def test_writeback_sinks_core_exports() -> None:
    module = importlib.import_module("agent_connector_sdk.writeback_sinks.core")
    exported = (
        module.resolve_writeback_client,
        module.WritebackClientMixin,
        module.resolve_external_id,
    )
    assert len(exported) == 3
    assert all(item is not None for item in exported)


def test_writeback_sinks_governed_exports() -> None:
    module = importlib.import_module("agent_connector_sdk.writeback_sinks.governed")
    exported = (
        module.GovernedOutcome,
        module.SinkWriteBackTransport,
        module.ledger_root,
    )
    assert len(exported) == 3
    assert all(item is not None for item in exported)


def test_writeback_sinks_sinks_ansible_exports() -> None:
    module = importlib.import_module(
        "agent_connector_sdk.writeback_sinks.sinks.ansible"
    )
    exported = (module.AnsibleSink,)
    assert len(exported) == 1
    assert all(item is not None for item in exported)


def test_writeback_sinks_sinks_archimate_exports() -> None:
    module = importlib.import_module(
        "agent_connector_sdk.writeback_sinks.sinks.archimate"
    )
    exported = (module.ArchimateSink,)
    assert len(exported) == 1
    assert all(item is not None for item in exported)


def test_writeback_sinks_sinks_capability_exports() -> None:
    module = importlib.import_module(
        "agent_connector_sdk.writeback_sinks.sinks.capability"
    )
    exported = (
        module.make_writeback_fn,
        module.resolve_writeback_fn,
        module.CapabilitySink,
    )
    assert len(exported) == 3
    assert all(item is not None for item in exported)


def test_writeback_sinks_sinks_ciso_assistant_exports() -> None:
    module = importlib.import_module(
        "agent_connector_sdk.writeback_sinks.sinks.ciso_assistant"
    )
    exported = (module.CisoAssistantSink,)
    assert len(exported) == 1
    assert all(item is not None for item in exported)


def test_writeback_sinks_sinks_egeria_exports() -> None:
    module = importlib.import_module("agent_connector_sdk.writeback_sinks.sinks.egeria")
    exported = (module.EgeriaSink,)
    assert len(exported) == 1
    assert all(item is not None for item in exported)


def test_writeback_sinks_sinks_emerald_exports() -> None:
    module = importlib.import_module(
        "agent_connector_sdk.writeback_sinks.sinks.emerald"
    )
    exported = (module.EmeraldSink,)
    assert len(exported) == 1
    assert all(item is not None for item in exported)


def test_writeback_sinks_sinks_erpnext_exports() -> None:
    module = importlib.import_module(
        "agent_connector_sdk.writeback_sinks.sinks.erpnext"
    )
    exported = (module.ErpNextSink,)
    assert len(exported) == 1
    assert all(item is not None for item in exported)


def test_writeback_sinks_sinks_home_assistant_exports() -> None:
    module = importlib.import_module(
        "agent_connector_sdk.writeback_sinks.sinks.home_assistant"
    )
    exported = (module.HomeAssistantSink,)
    assert len(exported) == 1
    assert all(item is not None for item in exported)


def test_writeback_sinks_sinks_identity_exports() -> None:
    module = importlib.import_module(
        "agent_connector_sdk.writeback_sinks.sinks.identity"
    )
    exported = (
        module.OktaSink,
        module.KeycloakSink,
    )
    assert len(exported) == 2
    assert all(item is not None for item in exported)


def test_writeback_sinks_sinks_issue_tracker_exports() -> None:
    module = importlib.import_module(
        "agent_connector_sdk.writeback_sinks.sinks.issue_tracker"
    )
    exported = (
        module.GitLabIssueSink,
        module.GitHubIssueSink,
        module.PlaneIssueSink,
        module.JiraIssueSink,
        module.JiraTransitionSink,
        module.PlaneStateSink,
    )
    assert len(exported) == 6
    assert all(item is not None for item in exported)


def test_writeback_sinks_sinks_leanix_exports() -> None:
    module = importlib.import_module("agent_connector_sdk.writeback_sinks.sinks.leanix")
    exported = (
        module.build_relation_field_resolver,
        module.LeanixSink,
    )
    assert len(exported) == 2
    assert all(item is not None for item in exported)


def test_writeback_sinks_sinks_legal_exports() -> None:
    module = importlib.import_module("agent_connector_sdk.writeback_sinks.sinks.legal")
    exported = (module.LegalSink,)
    assert len(exported) == 1
    assert all(item is not None for item in exported)


def test_writeback_sinks_sinks_mealie_exports() -> None:
    module = importlib.import_module("agent_connector_sdk.writeback_sinks.sinks.mealie")
    exported = (module.MealieSink,)
    assert len(exported) == 1
    assert all(item is not None for item in exported)


def test_writeback_sinks_sinks_nextcloud_exports() -> None:
    module = importlib.import_module(
        "agent_connector_sdk.writeback_sinks.sinks.nextcloud"
    )
    exported = (module.NextcloudSink,)
    assert len(exported) == 1
    assert all(item is not None for item in exported)


def test_writeback_sinks_sinks_ops_exports() -> None:
    module = importlib.import_module("agent_connector_sdk.writeback_sinks.sinks.ops")
    exported = (
        module.TechnitiumSink,
        module.CaddySink,
        module.UptimeKumaSink,
        module.KafkaSink,
        module.PortainerSink,
        module.LgtmSink,
    )
    assert len(exported) == 6
    assert all(item is not None for item in exported)


def test_writeback_sinks_sinks_process_exports() -> None:
    module = importlib.import_module(
        "agent_connector_sdk.writeback_sinks.sinks.process"
    )
    exported = (
        module.INTELLIGENCE_KEY,
        module.gather_intelligence,
        module.push_process_intelligence,
        module.GraphComputeReader,
        module.ProcessSink,
    )
    assert len(exported) == 5
    assert all(item is not None for item in exported)


def test_writeback_sinks_sinks_salesforce_exports() -> None:
    module = importlib.import_module(
        "agent_connector_sdk.writeback_sinks.sinks.salesforce"
    )
    exported = (module.SalesforceSink,)
    assert len(exported) == 1
    assert all(item is not None for item in exported)


def test_writeback_sinks_sinks_servicenow_exports() -> None:
    module = importlib.import_module(
        "agent_connector_sdk.writeback_sinks.sinks.servicenow"
    )
    exported = (module.ServiceNowSink,)
    assert len(exported) == 1
    assert all(item is not None for item in exported)


def test_writeback_sinks_sinks_twenty_exports() -> None:
    module = importlib.import_module("agent_connector_sdk.writeback_sinks.sinks.twenty")
    exported = (module.TwentySink,)
    assert len(exported) == 1
    assert all(item is not None for item in exported)


def test_writeback_sinks_sinks_wger_exports() -> None:
    module = importlib.import_module("agent_connector_sdk.writeback_sinks.sinks.wger")
    exported = (module.WgerSink,)
    assert len(exported) == 1
    assert all(item is not None for item in exported)
