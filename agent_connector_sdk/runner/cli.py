"""The ``connector-sync`` console script.

``connector-sync --config runner.yml`` serves every configured connector until
stopped; ``--once`` runs one full cycle per connector and exits ``0`` only when
every connector succeeded. Exit ``2`` means the runner could not start.
"""

from __future__ import annotations

import argparse
import logging
from collections.abc import Sequence
from pathlib import Path

import anyio

from agent_connector_sdk.config import setting
from agent_connector_sdk.credentials.references import SecretReferenceError
from agent_connector_sdk.discovery import (
    ExtensionActivationError,
    ExtensionDiscoveryError,
)
from agent_connector_sdk.runner.composition import default_services
from agent_connector_sdk.runner.errors import RunnerConfigurationError
from agent_connector_sdk.runner.health_server import HealthServer, parse_health_address
from agent_connector_sdk.runner.logs import configure_logging
from agent_connector_sdk.runner.services import RunnerServices
from agent_connector_sdk.runner.static_registry import (
    StaticConfigRegistry,
    load_runner_config,
)
from agent_connector_sdk.runner.supervisor import ConnectorSyncRunner

__all__ = ["build_parser", "default_state_dir", "main"]

_logger = logging.getLogger(__name__)

_STARTUP_ERRORS = (
    RunnerConfigurationError,
    ExtensionActivationError,
    ExtensionDiscoveryError,
    SecretReferenceError,
    LookupError,
)


def default_state_dir() -> Path:
    """``$XDG_STATE_HOME/connector-sync``, else ``~/.local/state/connector-sync``."""
    base = setting("XDG_STATE_HOME") or str(Path.home() / ".local" / "state")
    return Path(base) / "connector-sync"


def build_parser() -> argparse.ArgumentParser:
    """The command-line parser."""
    parser = argparse.ArgumentParser(
        prog="connector-sync",
        description="Provision connector content and sync connector presets.",
    )
    parser.add_argument("--config", type=Path, required=True, help="runner YAML")
    parser.add_argument(
        "--state-dir", type=Path, default=None, help="reserved process-state directory"
    )
    parser.add_argument("--sink", default="epistemic_graph", help="sink extension")
    parser.add_argument("--once", action="store_true", help="one cycle, then exit")
    parser.add_argument("--log-format", choices=("json", "text"), default="json")
    parser.add_argument(
        "--health-addr",
        default=None,
        help=(
            "PORT or HOST:PORT serving /health and /health/ready "
            "(env RUNNER_HEALTH_ADDR); disabled unless set, and not started "
            "for --once"
        ),
    )
    parser.add_argument(
        "--health-allow-non-loopback",
        action="store_true",
        help="allow --health-addr to bind a non-loopback host (e.g. a pod IP)",
    )
    return parser


def _health_server(
    args: argparse.Namespace, services: RunnerServices
) -> HealthServer | None:
    """Start the health listener when configured for a long-lived run.

    Raises:
        RunnerConfigurationError: the address is malformed, or non-loopback
            without ``--health-allow-non-loopback``.
    """
    address = args.health_addr or setting("RUNNER_HEALTH_ADDR")
    if address is None or args.once or services.health is None:
        return None
    host, port = parse_health_address(str(address))
    server = HealthServer(
        services.health,
        host=host,
        port=port,
        allow_non_loopback=args.health_allow_non_loopback,
    )
    server.start()
    return server


def _start(args: argparse.Namespace) -> tuple[RunnerServices, HealthServer | None]:
    """Build services and, when configured, the health listener.

    Raises:
        RunnerConfigurationError: bad config, credentials, or health address.
        ExtensionActivationError, ExtensionDiscoveryError, SecretReferenceError,
        LookupError: an extension is uncertified, missing, or misconfigured.
    """
    config = load_runner_config(args.config)
    services = default_services(
        config.settings,
        state_dir=args.state_dir or default_state_dir(),
        sink_name=args.sink,
    )
    return services, _health_server(args, services)


def _run(runner: ConnectorSyncRunner, *, once: bool) -> int:
    """Run ``runner`` to completion (``--once``) or forever; the exit code."""
    if once:
        results = anyio.run(runner.run_once)
        return 0 if all(results.values()) else 1
    anyio.run(runner.run_forever)
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    """Run the connector-sync runner; returns the process exit code."""
    args = build_parser().parse_args(argv)
    configure_logging(args.log_format)
    try:
        services, health_server = _start(args)
    except _STARTUP_ERRORS as exc:
        _logger.error("connector-sync cannot start: %s", exc)
        return 2
    runner = ConnectorSyncRunner(StaticConfigRegistry(args.config), services)
    try:
        return _run(runner, once=args.once)
    finally:
        if health_server is not None:
            health_server.stop()
