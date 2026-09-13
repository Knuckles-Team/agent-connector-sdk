"""The connector-sync console script, its composition root and structured logs."""

from __future__ import annotations

import json
import logging
import sys
from collections.abc import Iterator
from pathlib import Path

import pytest
import yaml
from fleet_fixtures import FRESHRSS_CONNECTORS, FRESHRSS_ROOT

from agent_connector_sdk.discovery import (
    TRANSPORT_GROUP,
    CertifiedExtensions,
    ExtensionActivationError,
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
    built = default_services(
        RunnerSettings(), state_dir=tmp_path, sink_name="epistemic_graph"
    )
    assert isinstance(built, RunnerServices)
    assert isinstance(built.transport, McpTransport)
    assert isinstance(built.sink, EpistemicGraphSink)
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
            policy=CertifiedExtensions(()),
        )


def test_cli_exits_2_when_it_cannot_start(tmp_path: Path) -> None:
    (tmp_path / "broken.yml").write_text("connectors: [unclosed")
    assert main(["--config", str(tmp_path / "broken.yml"), "--log-format", "text"]) == 2
    empty = tmp_path / "empty.yml"
    empty.write_text("connectors: []\n")
    state = ["--state-dir", str(tmp_path / "state")]
    assert main(["--config", str(empty), "--once", "--sink", "missing", *state]) == 2
    assert main(["--config", str(empty), "--once", *state]) == 0


def test_cli_skips_the_health_server_for_once(tmp_path: Path) -> None:
    empty = tmp_path / "empty.yml"
    empty.write_text("connectors: []\n")
    state = ["--state-dir", str(tmp_path / "state")]
    # A non-loopback address with no --health-allow-non-loopback would refuse
    # to bind if the health server were started; --once must never start it.
    assert (
        main(["--config", str(empty), "--once", "--health-addr", "0.0.0.0:0", *state])
        == 0
    )


def test_cli_exits_2_for_an_unconfigured_non_loopback_health_addr(
    tmp_path: Path,
) -> None:
    empty = tmp_path / "empty.yml"
    empty.write_text("connectors: []\n")
    state = ["--state-dir", str(tmp_path / "state")]
    assert main(["--config", str(empty), "--health-addr", "0.0.0.0:0", *state]) == 2


def test_cli_once_over_stdio_is_blocked_by_the_w1_sink(
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
    assert main(["--config", str(config), "--once", "--state-dir", str(state)]) == 1
    lines = [
        json.loads(line)
        for line in capfd.readouterr().err.splitlines()
        if line.startswith("{")
    ]
    failures = [line for line in lines if line.get("event") == "connector_failed"]
    assert failures and "RF-ADR-009 W1" in failures[0]["error"]
    assert not state.exists()
