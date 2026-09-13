"""The connector-sync scheduler: one supervisor for every connector.

There is no per-connector daemon. :meth:`ConnectorSyncRunner.run_forever` keeps
one worker task per registered connector inside one task group, re-reads the
registry on an interval to start new connectors and restart changed ones, and
bounds concurrent cycles with one capacity limiter.
"""

from __future__ import annotations

import logging

import anyio
from anyio.abc import TaskGroup, TaskStatus

from agent_connector_sdk.ports.connector_registry import ConnectorRegistry
from agent_connector_sdk.runner.descriptors import ConnectorDescriptor
from agent_connector_sdk.runner.errors import RunnerConfigurationError
from agent_connector_sdk.runner.health_reporting import (
    note_heartbeat,
    note_registry_loaded,
)
from agent_connector_sdk.runner.logs import structured
from agent_connector_sdk.runner.services import RunnerServices
from agent_connector_sdk.runner.worker import ConnectorWorker

__all__ = ["ConnectorSyncRunner"]

_logger = logging.getLogger(__name__)

_Running = dict[str, tuple[ConnectorDescriptor, anyio.CancelScope]]


async def _serve_worker(
    worker: ConnectorWorker,
    *,
    task_status: TaskStatus[anyio.CancelScope] = anyio.TASK_STATUS_IGNORED,
) -> None:
    scope = anyio.CancelScope()
    with scope:
        task_status.started(scope)
        await worker.serve()


class ConnectorSyncRunner:
    """Runs every registered connector.

    Args:
        registry: Lists the connectors to serve.
        services: The shared ports and settings.
    """

    def __init__(self, registry: ConnectorRegistry, services: RunnerServices) -> None:
        self._registry = registry
        self._services = services

    def _worker(
        self, descriptor: ConnectorDescriptor, limiter: anyio.CapacityLimiter
    ) -> ConnectorWorker:
        return ConnectorWorker(descriptor, self._services, limiter)

    async def run_once(self) -> dict[str, bool]:
        """Run one full cycle per connector; map each connector to its success."""
        limiter = anyio.CapacityLimiter(self._services.settings.max_concurrency)
        results: dict[str, bool] = {}

        async def run(descriptor: ConnectorDescriptor) -> None:
            results[descriptor.connector] = await self._worker(
                descriptor, limiter
            ).run_once()

        async with anyio.create_task_group() as tasks:
            for descriptor in await self._registry.connectors():
                tasks.start_soon(run, descriptor)
        return results

    async def run_forever(self) -> None:
        """Serve every connector until cancelled."""
        limiter = anyio.CapacityLimiter(self._services.settings.max_concurrency)
        running: _Running = {}
        async with anyio.create_task_group() as tasks:
            while True:
                await self._reconcile(tasks, running=running, limiter=limiter)
                # Beats only once a full reconcile pass returns -- a wedged
                # registry read or a stuck worker start never reaches this
                # line, so a hung loop goes stale instead of always "live".
                note_heartbeat(self._services.health)
                await anyio.sleep(self._services.settings.registry_refresh_seconds)

    async def _reconcile(
        self,
        tasks: TaskGroup,
        *,
        running: _Running,
        limiter: anyio.CapacityLimiter,
    ) -> None:
        try:
            registered = await self._registry.connectors()
        except RunnerConfigurationError as exc:
            _logger.error(
                "connector registry unreadable, keeping %d connectors: %s",
                len(running),
                exc,
                extra=structured("registry_unreadable", "", error=str(exc)),
            )
            return
        wanted = {descriptor.connector: descriptor for descriptor in registered}
        note_registry_loaded(self._services.health, tuple(wanted))
        for name in [n for n, (d, _) in running.items() if wanted.get(n) != d]:
            running.pop(name)[1].cancel()
            _logger.info(
                "connector %s stopped",
                name,
                extra=structured("connector_stopped", name),
            )
        for name, descriptor in wanted.items():
            if name not in running:
                scope = await tasks.start(
                    _serve_worker, self._worker(descriptor, limiter)
                )
                running[name] = (descriptor, scope)
                _logger.info(
                    "connector %s started",
                    name,
                    extra=structured("connector_started", name),
                )
