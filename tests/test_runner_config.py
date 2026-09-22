"""Runner configuration, descriptors, endpoints, plans, checkpoints and backoff."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import yaml
from fleet_fixtures import FRESHRSS_READING_LIST
from pydantic import ValidationError
from runner_support import freshrss_descriptor

from agent_connector_sdk.credentials.resolver import EnvironmentCredentialResolver
from agent_connector_sdk.ports.change_source import ChangeEvent
from agent_connector_sdk.ports.connector_registry import ConnectorRegistry
from agent_connector_sdk.runner.backoff import Backoff
from agent_connector_sdk.runner.descriptors import (
    ConnectorDescriptor,
    EndpointSpec,
    RunnerConfig,
    RunnerSettings,
)
from agent_connector_sdk.runner.endpoints import CredentialEndpoints, EndpointFactory
from agent_connector_sdk.runner.errors import (
    CredentialResolutionError,
    RunnerConfigurationError,
)
from agent_connector_sdk.runner.plans import (
    CyclePlan,
    change_plan,
    full_plan,
    load_sync_adapters,
)
from agent_connector_sdk.runner.static_registry import (
    StaticConfigRegistry,
    load_runner_config,
)


def _connector(**endpoint: Any) -> dict[str, Any]:
    return {
        "connector": "freshrss-agent",
        "package_root": "packages/freshrss-agent",
        "endpoint": endpoint or {"url": "https://freshrss.example.invalid/mcp"},
    }


def _write(path: Path, document: object) -> Path:
    path.write_text(yaml.safe_dump(document))
    return path


async def test_config_anchors_paths_and_lists_connectors(tmp_path: Path) -> None:
    config = _write(
        tmp_path / "runner.yml",
        {"settings": {"max_concurrency": 2}, "connectors": [_connector()]},
    )
    loaded = load_runner_config(config)
    assert isinstance(loaded, RunnerConfig)
    assert isinstance(loaded.settings, RunnerSettings)
    (descriptor,) = loaded.connectors
    assert descriptor.package_root == tmp_path.resolve() / "packages/freshrss-agent"
    assert descriptor.resolved_mapping_reference == "manifest:freshrss-agent"
    registry = StaticConfigRegistry(config)
    assert isinstance(registry, ConnectorRegistry)
    (listed,) = await registry.connectors()
    assert isinstance(listed, ConnectorDescriptor) and listed == descriptor


def test_config_rejects_literal_secrets_without_echoing_them(tmp_path: Path) -> None:
    literal = "example-literal-value-9f2c"
    endpoint = {"url": "https://freshrss.example.invalid/mcp", "bearer_token": literal}
    config = _write(tmp_path / "literal.yml", {"connectors": [_connector(**endpoint)]})
    with pytest.raises(RunnerConfigurationError) as caught:
        load_runner_config(config)
    assert literal not in str(caught.value) and caught.value.__cause__ is None
    duplicate = _write(
        tmp_path / "duplicate.yml", {"connectors": [_connector(), _connector()]}
    )
    (tmp_path / "broken.yml").write_text("connectors: [unclosed")
    (tmp_path / "large.yml").write_text("#" * (1024 * 1024 + 1))
    for path, message in (
        (duplicate, "more than once"),
        (tmp_path / "broken.yml", "not valid YAML"),
        (tmp_path / "large.yml", "too large"),
        (tmp_path / "missing.yml", "unreadable"),
    ):
        with pytest.raises(RunnerConfigurationError, match=message):
            load_runner_config(path)


def test_endpoint_spec_rules() -> None:
    for bad in (
        {},
        {"url": "https://a.invalid/mcp", "command": "demo-mcp"},
        {"command": "demo-mcp", "bearer_token": "env://TOKEN"},
        {"command": "demo-mcp", "env": {"TOKEN": "plain-value"}},
    ):
        with pytest.raises(ValidationError):
            EndpointSpec.model_validate(bad)


def test_credential_endpoints_resolve_or_refuse(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("CONNECTOR_SYNC_TEST_VALUE", "resolved-value-1")
    factory: EndpointFactory = CredentialEndpoints(EnvironmentCredentialResolver())
    descriptor = freshrss_descriptor(
        endpoint=EndpointSpec(
            command="freshrss-mcp",
            env={"FRESHRSS_TOKEN": "env://CONNECTOR_SYNC_TEST_VALUE"},
        )
    )
    endpoint = factory(descriptor)
    assert endpoint.env == {"FRESHRSS_TOKEN": "resolved-value-1"}
    assert "resolved-value-1" not in repr(endpoint)
    monkeypatch.delenv("CONNECTOR_SYNC_TEST_VALUE")
    with pytest.raises(CredentialResolutionError, match="could not be resolved"):
        factory(descriptor)


def test_load_sync_adapters_fails_closed(tmp_path: Path) -> None:
    assert list(load_sync_adapters(freshrss_descriptor())) == ["freshrss"]
    exact = "manifest:freshrss-agent#schema_mappings/news_article"
    assert list(load_sync_adapters(freshrss_descriptor(mapping_reference=exact))) == [
        "freshrss"
    ]
    for overrides, message in (
        ({"presets": ("missing",)}, "not in the manifest"),
        ({"data_resources": {"data://x": ("other",)}}, "is not selected"),
        ({"connector": "archivebox-api", "data_resources": {}}, "is connector"),
        ({"package_root": tmp_path}, "unreadable"),
        (
            {"mapping_reference": ("manifest:freshrss-agent#schema_mappings/missing")},
            "does not name a manifest mapping",
        ),
        (
            {"mapping_reference": "manifest:other#schema_mappings/news_article"},
            "must name this connector",
        ),
        (
            {"mapping_reference": "opaque:mapping"},
            "must name this connector",
        ),
    ):
        with pytest.raises(RunnerConfigurationError, match=message):
            load_sync_adapters(freshrss_descriptor(**overrides))


def test_cycle_plans() -> None:
    descriptor = freshrss_descriptor()
    assert full_plan(descriptor, ["freshrss"]) == CyclePlan(
        True, frozenset({"freshrss"})
    )
    updates = [
        ChangeEvent("resource", FRESHRSS_READING_LIST),
        ChangeEvent("resource", "data://unmapped"),
    ]
    assert change_plan(descriptor, updates, frozenset()) == CyclePlan(
        False, frozenset({"freshrss"})
    )
    skill = "skill://freshrss-feed-reader/SKILL.md"
    assert change_plan(
        descriptor, [ChangeEvent("resource", skill)], frozenset({skill})
    ).provision
    silent = freshrss_descriptor(provision=False)
    assert change_plan(silent, [ChangeEvent("tools")], frozenset()) == CyclePlan(
        False, frozenset()
    )


def test_backoff_doubles_to_its_maximum_and_resets() -> None:
    backoff = Backoff(1.0, 3.0)
    assert [backoff.next_delay() for _ in range(4)] == [1.0, 2.0, 3.0, 3.0]
    backoff.reset()
    assert backoff.next_delay() == 1.0
    with pytest.raises(ValueError):
        Backoff(2.0, 1.0)
