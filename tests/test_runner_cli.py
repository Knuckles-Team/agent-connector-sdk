"""The connector-sync console script, its composition root and structured logs."""

from __future__ import annotations

import json
import logging
import sys
from collections.abc import Iterator
from pathlib import Path

import pytest
import yaml
from epistemic_graph.generated.connector_pack import (
    AgentLibraryMutationContext,
    McpCatalogSnapshotBinding,
)
from fleet_fixtures import FRESHRSS_CONNECTORS, FRESHRSS_ROOT

from agent_connector_sdk import decide
from agent_connector_sdk.decide.epistemic_graph import EpistemicGraphDecisionRunner
from agent_connector_sdk.decide.transport import GeneratedTransport
from agent_connector_sdk.discovery import (
    TRANSPORT_GROUP,
    CertifiedExtensions,
    ExtensionActivationError,
    ExtensionDiscoveryError,
    sdk_reference_extensions,
)
from agent_connector_sdk.runner.cli import build_parser, default_state_dir, main
from agent_connector_sdk.runner.composition import default_services, extension_instance
from agent_connector_sdk.runner.descriptors import RunnerSettings
from agent_connector_sdk.runner.logs import (
    RUNNER_LOGGER,
    JsonLogFormatter,
    configure_logging,
    structured,
)
from agent_connector_sdk.runner.services import RunnerServices
from agent_connector_sdk.sinks.epistemic_graph import EpistemicGraphSink
from agent_connector_sdk.transports.mcp import McpTransport


async def _pack_import_authority(
    connector: str,
) -> tuple[McpCatalogSnapshotBinding, AgentLibraryMutationContext]:
    raise AssertionError(f"authority resolver unexpectedly called for {connector}")


@pytest.fixture(autouse=True)
def _restore_runner_logger(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    monkeypatch.delenv("OPENBAO_ADDR", raising=False)
    yield
    logger = logging.getLogger(RUNNER_LOGGER)
    logger.handlers = []
    logger.propagate = True


def test_structured_json_logs() -> None:
    logger = configure_logging("json")
    assert logger.name == RUNNER_LOGGER and not logger.propagate
    record = logging.LogRecord(
        RUNNER_LOGGER, logging.INFO, __file__, 1, "connector %s ok", ("demo",), None
    )
    record.structured = structured("pack_imported", "demo", imported=3)["structured"]
    document = json.loads(JsonLogFormatter().format(record))
    assert document["event"] == "pack_imported" and document["imported"] == 3
    assert document["message"] == "connector demo ok" and document["level"] == "INFO"
    text = configure_logging("text").handlers[0].formatter
    assert text is not None and not isinstance(text, JsonLogFormatter)


def test_parser_and_state_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    args = build_parser().parse_args(["--config", "runner.yml"])
    assert (args.sink, args.once, args.log_format, args.state_dir) == (
        "epistemic_graph",
        False,
        "json",
        None,
    )
    assert (args.health_addr, args.health_allow_non_loopback) == (None, False)
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path))
    assert default_state_dir() == tmp_path / "connector-sync"
    monkeypatch.delenv("XDG_STATE_HOME")
    assert default_state_dir() == Path.home() / ".local/state/connector-sync"


def test_default_services_load_certified_extensions(tmp_path: Path) -> None:
    verified_client = object()
    built = default_services(
        RunnerSettings(),
        state_dir=tmp_path,
        sink_name="epistemic_graph",
        sink_client=verified_client,
        pack_import_authority=_pack_import_authority,
    )
    assert isinstance(built, RunnerServices)
    assert isinstance(built.transport, McpTransport)
    assert isinstance(built.sink, EpistemicGraphSink)
    assert built.sink._client is verified_client
    assert built.sink._pack_import_authority is _pack_import_authority
    assert sorted(kind.kind for kind in built.kinds) == [
        "prompt",
        "resource",
        "skill",
        "tool",
    ]
    policy = sdk_reference_extensions()
    assert isinstance(
        extension_instance(TRANSPORT_GROUP, "mcp", policy=policy), McpTransport
    )
    with pytest.raises(ExtensionActivationError):
        default_services(
            RunnerSettings(),
            state_dir=tmp_path,
            sink_name="epistemic_graph",
            sink_client=verified_client,
            pack_import_authority=_pack_import_authority,
            policy=CertifiedExtensions(()),
        )
    with pytest.raises(ExtensionDiscoveryError, match="pack import authority"):
        default_services(
            RunnerSettings(), state_dir=tmp_path, sink_name="epistemic_graph"
        )


@pytest.fixture
def _reset_decide_runner() -> Iterator[None]:
    yield
    decide.install_runner(None)


def test_default_services_installs_no_decide_runner_without_a_tenant(
    tmp_path: Path, _reset_decide_runner: None, caplog: pytest.LogCaptureFixture
) -> None:
    """A verified client with no tenant: never invented, logged once."""
    with caplog.at_level(logging.WARNING):
        built = default_services(
            RunnerSettings(),
            state_dir=tmp_path,
            sink_name="epistemic_graph",
            sink_client=object(),
            pack_import_authority=_pack_import_authority,
        )
    assert built.decide_runner is None
    assert decide.current_runner() is None
    warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert len(warnings) == 1
    assert "no decide_tenant" in warnings[0].message


def test_decide_runner_logs_nothing_for_a_non_eg_sink(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """No verified session at all is unremarkable -- nothing to warn about."""
    from agent_connector_sdk.runner.composition import _decide_runner

    with caplog.at_level(logging.WARNING):
        assert (
            _decide_runner("other_sink", None, decide_tenant=None, decide_bindings=None)
            is None
        )
    assert not caplog.records


def test_default_services_installs_the_eg_backed_decide_runner_with_a_tenant(
    tmp_path: Path, _reset_decide_runner: None
) -> None:
    verified_client = object()
    built = default_services(
        RunnerSettings(),
        state_dir=tmp_path,
        sink_name="epistemic_graph",
        sink_client=verified_client,
        pack_import_authority=_pack_import_authority,
        decide_tenant="tenant-connector-sync",
    )
    assert isinstance(built.decide_runner, EpistemicGraphDecisionRunner)
    assert built.decide_runner.tenant == "tenant-connector-sync"
    assert isinstance(built.decide_runner.transport, GeneratedTransport)
    assert built.decide_runner.transport.client is verified_client
    assert built.decide_runner.transport.loop is None, (
        "no loop exists yet at composition-root time; a sync choose() falls "
        "back until a future change threads one through"
    )
    assert decide.current_runner() is built.decide_runner


def test_decide_runner_is_never_built_for_a_non_eg_sink_or_missing_inputs() -> None:
    from agent_connector_sdk.runner.composition import _decide_runner

    assert (
        _decide_runner(
            "other_sink", object(), decide_tenant="tenant-t", decide_bindings=None
        )
        is None
    )
    assert (
        _decide_runner(
            "epistemic_graph", None, decide_tenant="tenant-t", decide_bindings=None
        )
        is None
    )
    assert (
        _decide_runner(
            "epistemic_graph", object(), decide_tenant=None, decide_bindings=None
        )
        is None
    )


def test_resolve_decide_tenant_env_override_wins(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from agent_connector_sdk.runner.cli import _resolve_decide_tenant

    monkeypatch.delenv("RUNNER_DECIDE_TENANT", raising=False)
    assert _resolve_decide_tenant("injected-tenant") == "injected-tenant"
    assert _resolve_decide_tenant(None) is None
    monkeypatch.setenv("RUNNER_DECIDE_TENANT", "env-tenant")
    assert _resolve_decide_tenant("injected-tenant") == "env-tenant"
    assert _resolve_decide_tenant(None) == "env-tenant"


def test_cli_main_installs_the_decide_runner_with_a_verified_client(
    tmp_path: Path, _reset_decide_runner: None
) -> None:
    """The real CLI path (``main()``), not just ``default_services`` directly."""
    empty = tmp_path / "empty.yml"
    empty.write_text("connectors: []\n")
    state = ["--state-dir", str(tmp_path / "state")]
    verified_client = object()
    exit_code = main(
        ["--config", str(empty), "--once", *state],
        sink_client=verified_client,
        pack_import_authority=_pack_import_authority,
        decide_tenant="tenant-connector-sync",
    )
    assert exit_code == 0
    runner = decide.current_runner()
    assert isinstance(runner, EpistemicGraphDecisionRunner)
    assert runner.tenant == "tenant-connector-sync"
    assert isinstance(runner.transport, GeneratedTransport)
    assert runner.transport.client is verified_client


def test_cli_main_env_tenant_overrides_the_injected_one(
    tmp_path: Path, _reset_decide_runner: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("RUNNER_DECIDE_TENANT", "env-tenant")
    empty = tmp_path / "empty.yml"
    empty.write_text("connectors: []\n")
    state = ["--state-dir", str(tmp_path / "state")]
    exit_code = main(
        ["--config", str(empty), "--once", *state],
        sink_client=object(),
        pack_import_authority=_pack_import_authority,
        decide_tenant="injected-tenant",
    )
    assert exit_code == 0
    runner = decide.current_runner()
    assert isinstance(runner, EpistemicGraphDecisionRunner)
    assert runner.tenant == "env-tenant"


def test_cli_exits_2_when_it_cannot_start(tmp_path: Path) -> None:
    (tmp_path / "broken.yml").write_text("connectors: [unclosed")
    assert main(["--config", str(tmp_path / "broken.yml"), "--log-format", "text"]) == 2
    empty = tmp_path / "empty.yml"
    empty.write_text("connectors: []\n")
    state = ["--state-dir", str(tmp_path / "state")]
    assert main(["--config", str(empty), "--once", "--sink", "missing", *state]) == 2
    assert main(["--config", str(empty), "--once", *state]) == 2


def test_cli_skips_the_health_server_for_once(tmp_path: Path) -> None:
    empty = tmp_path / "empty.yml"
    empty.write_text("connectors: []\n")
    state = ["--state-dir", str(tmp_path / "state")]
    # A non-loopback address with no --health-allow-non-loopback would refuse
    # to bind if the health server were started; --once must never start it.
    assert (
        main(["--config", str(empty), "--once", "--health-addr", "0.0.0.0:0", *state])
        == 2
    )


def test_cli_exits_2_for_an_unconfigured_non_loopback_health_addr(
    tmp_path: Path,
) -> None:
    empty = tmp_path / "empty.yml"
    empty.write_text("connectors: []\n")
    state = ["--state-dir", str(tmp_path / "state")]
    assert main(["--config", str(empty), "--health-addr", "0.0.0.0:0", *state]) == 2


def test_cli_once_over_stdio_refuses_to_mint_an_engine_client(
    tmp_path: Path, capfd: pytest.CaptureFixture[str]
) -> None:
    server = Path(__file__).parent / "stdio_fleet_server.py"
    connector = {
        "connector": "freshrss-agent",
        "package_root": str(FRESHRSS_ROOT),
        "connectors_dir": str(FRESHRSS_CONNECTORS),
        "endpoint": {"command": sys.executable, "args": [str(server)]},
    }
    config = tmp_path / "runner.yml"
    config.write_text(yaml.safe_dump({"connectors": [connector]}))
    state = tmp_path / "state"
    assert main(["--config", str(config), "--once", "--state-dir", str(state)]) == 2
    lines = [
        json.loads(line)
        for line in capfd.readouterr().err.splitlines()
        if line.startswith("{")
    ]
    assert any(
        "requires an injected verified client" in line["message"] for line in lines
    )
    assert not state.exists()
