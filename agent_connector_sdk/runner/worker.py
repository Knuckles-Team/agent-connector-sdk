"""One connector's supervised loop: connect, cycle, follow changes, back off."""

from __future__ import annotations

import logging
from collections.abc import Mapping

import anyio

from agent_connector_sdk.ports.change_source import ChangeEvent, ChangeSource
from agent_connector_sdk.ports.session import McpSession
from agent_connector_sdk.ports.source_adapter import SourceAdapter
from agent_connector_sdk.runner.backoff import Backoff
from agent_connector_sdk.runner.credentialed_endpoint import resolve_endpoint
from agent_connector_sdk.runner.descriptors import ConnectorDescriptor
from agent_connector_sdk.runner.health_reporting import (
    note_cycle_failure,
    note_cycle_success,
)
from agent_connector_sdk.runner.logs import structured
from agent_connector_sdk.runner.plans import (
    CyclePlan,
    change_plan,
    full_plan,
    load_sync_adapters,
)
from agent_connector_sdk.runner.provisioning import provision_content
from agent_connector_sdk.runner.services import RunnerServices
from agent_connector_sdk.runner.syncing import SyncTarget, sync_stream

__all__ = ["ConnectorWorker"]

_logger = logging.getLogger(__name__)

Adapters = Mapping[str, SourceAdapter]


class ConnectorWorker:
    """Serves one connector over one MCP session at a time.

    Args:
        descriptor: The connector to serve.
        services: The shared ports and settings.
        limiter: Bounds how many connector cycles run at once, runner-wide.
    """

    def __init__(
        self,
        descriptor: ConnectorDescriptor,
        services: RunnerServices,
        limiter: anyio.CapacityLimiter,
    ) -> None:
        self._descriptor = descriptor
        self._services = services
        self._limiter = limiter
        settings = services.settings
        self._backoff = Backoff(
            settings.backoff_initial_seconds, settings.backoff_max_seconds
        )
        self._resource_uris: frozenset[str] = frozenset()

    async def run_once(self) -> bool:
        """Connect and run one full cycle; ``False`` when it failed (logged)."""
        name = self._descriptor.connector
        try:
            await self._connect(follow=False)
        except Exception as exc:
            note_cycle_failure(self._services.health, name, next_retry_seconds=None)
            _logger.error(
                "connector %s failed: %s",
                name,
                exc,
                extra=structured("connector_failed", name, error=str(exc)),
            )
            return False
        return True

    async def serve(self) -> None:
        """Serve until cancelled, reconnecting with backoff after any failure."""
        name = self._descriptor.connector
        while True:
            try:
                await self._connect(follow=True)
            except Exception as exc:
                delay = self._backoff.next_delay()
                note_cycle_failure(
                    self._services.health, name, next_retry_seconds=delay
                )
                _logger.error(
                    "connector %s failed, retrying in %.1fs: %s",
                    name,
                    delay,
                    exc,
                    extra=structured(
                        "connector_failed", name, error=str(exc), retry_in=delay
                    ),
                )
                await anyio.sleep(delay)

    async def _connect(self, *, follow: bool) -> None:
        # Package validation and credential resolution both fail closed
        # before any session is opened.
        adapters = await anyio.to_thread.run_sync(load_sync_adapters, self._descriptor)
        endpoint = await resolve_endpoint(self._services, self._descriptor)
        async with self._services.transport.session(endpoint) as session:
            await self._cycle(session, adapters, full_plan(self._descriptor, adapters))
            self._backoff.reset()
            if follow:
                await self._follow(session, adapters)

    async def _follow(self, session: McpSession, adapters: Adapters) -> None:
        watched = await self._watch(session, None)
        while True:
            changes = await self._wait(session)
            plan = (
                change_plan(self._descriptor, changes, self._resource_uris)
                if changes
                else full_plan(self._descriptor, adapters)
            )
            await self._cycle(session, adapters, plan)
            watched = await self._watch(session, watched)

    async def _watch(
        self, session: McpSession, watched: frozenset[str] | None
    ) -> frozenset[str] | None:
        wanted = self._resource_uris | frozenset(self._descriptor.data_resources)
        if not isinstance(session, ChangeSource) or wanted == watched:
            return watched
        listening = await session.watch(sorted(wanted))
        name = self._descriptor.connector
        _logger.info(
            "connector %s follows changes by %s",
            name,
            "subscriptions/listen" if listening else "notifications and schedule",
            extra=structured(
                "change_subscription", name, listening=listening, resources=len(wanted)
            ),
        )
        return wanted

    async def _wait(self, session: McpSession) -> frozenset[ChangeEvent]:
        interval = self._descriptor.interval_seconds
        if not isinstance(session, ChangeSource):
            await anyio.sleep(interval)
            return frozenset()
        with anyio.move_on_after(interval):
            return await session.next_changes()
        return frozenset()

    async def _cycle(
        self, session: McpSession, adapters: Adapters, plan: CyclePlan
    ) -> None:
        async with self._limiter:
            if plan.provision:
                await self._provision(session)
            for preset in sorted(plan.presets):
                await self._sync(session, adapters[preset])
        note_cycle_success(self._services.health, self._descriptor.connector)

    async def _provision(self, session: McpSession) -> None:
        name, services = self._descriptor.connector, self._services
        outcome = await provision_content(
            session,
            connector=name,
            kinds=services.kinds,
            sink=services.sink,
        )
        self._resource_uris = outcome.resource_uris
        event = "pack_imported" if outcome.changed else "pack_unchanged"
        _logger.info(
            "connector %s %s %s",
            name,
            event,
            outcome.pack_digest,
            extra=structured(
                event, name, pack_digest=outcome.pack_digest, imported=outcome.imported
            ),
        )

    async def _sync(self, session: McpSession, adapter: SourceAdapter) -> None:
        descriptor, services = self._descriptor, self._services
        target = SyncTarget.configured(
            descriptor.connector,
            services.sink,
            descriptor.max_pages_per_cycle,
            descriptor.empty_authoritative_approval,
        )
        outcome = await sync_stream(session, adapter, target)
        _logger.info(
            "connector %s synced %s: %d pages, %d records, %d accepted",
            descriptor.connector,
            outcome.stream,
            outcome.pages,
            outcome.records,
            outcome.accepted,
            extra=structured(
                "stream_synced",
                descriptor.connector,
                stream=outcome.stream,
                pages=outcome.pages,
                records=outcome.records,
                accepted=outcome.accepted,
                exhausted=outcome.exhausted,
            ),
        )
