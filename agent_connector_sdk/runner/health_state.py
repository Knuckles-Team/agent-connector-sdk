"""Runner health state: a supervisor heartbeat, per-connector detail, readiness.

Nothing here opens a socket -- :mod:`agent_connector_sdk.runner.health_server`
serves this state over HTTP. Every synchronous method (everything but
:meth:`RunnerHealth.readiness`) is safe to call from a different thread than
the writers: the HTTP listener runs in its own background thread while the
supervisor's anyio event loop keeps updating this object. ``readiness`` is
``async`` -- it asks the configured sink directly -- so its caller supplies
the event loop (``health_server.py`` runs one fresh per call, since the HTTP
listener's thread has none of its own).
"""

from __future__ import annotations

import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, replace

from agent_connector_sdk.ports.sink import Sink
from agent_connector_sdk.runner.sink_probe import probe_sink_readiness, sink_reason

__all__ = ["ConnectorHealth", "HealthReport", "RunnerHealth"]

_SCHEDULER_COMPONENT = "scheduler_loop"
#: Default bound on a per-request sink readiness probe (see ``sink_probe.py``).
_DEFAULT_SINK_TIMEOUT_SECONDS = 5.0


@dataclass(frozen=True)
class ConnectorHealth:
    """One connector's last-known cycle and credential outcome."""

    connector: str
    last_success_monotonic: float | None = None
    consecutive_failures: int = 0
    next_retry_seconds: float | None = None
    credentials_ok: bool | None = None
    credential_error: str = ""

    def snapshot(self, *, now: float) -> dict[str, object]:
        """A JSON-safe view. Never carries a credential value."""
        since = (
            None
            if self.last_success_monotonic is None
            else now - self.last_success_monotonic
        )
        return {
            "last_success_seconds_ago": since,
            "consecutive_failures": self.consecutive_failures,
            "next_retry_seconds": self.next_retry_seconds,
            "credentials_ok": self.credentials_ok,
            "credential_error": self.credential_error,
        }


@dataclass(frozen=True)
class HealthReport:
    """One health response: the HTTP status and its JSON body."""

    ok: bool
    status: int
    body: dict[str, object]


class RunnerHealth:
    """Liveness/readiness state the supervisor loop and workers update.

    Args:
        sink: The configured sink; readiness calls ``sink.readiness()``.
        liveness_window_seconds: How long the scheduler heartbeat may go
            without updating before liveness reports unhealthy.
        sink_timeout_seconds: Bound on the per-request sink readiness probe,
            so a hung sink cannot hang a ``/health/ready`` request.
        clock: Monotonic time source; overridden by tests for determinism.
    """

    def __init__(
        self,
        *,
        sink: Sink,
        liveness_window_seconds: float,
        sink_timeout_seconds: float = _DEFAULT_SINK_TIMEOUT_SECONDS,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._sink = sink
        self._sink_timeout = sink_timeout_seconds
        self._window = liveness_window_seconds
        self._clock = clock
        self._lock = threading.Lock()
        self._heartbeat = clock()
        self._registry_loaded = False
        self._connectors: dict[str, ConnectorHealth] = {}

    def heartbeat(self) -> None:
        """Record that the scheduler loop completed another iteration."""
        with self._lock:
            self._heartbeat = self._clock()

    def sync_registry(self, connectors: tuple[str, ...]) -> None:
        """Mark the registry loaded and seed unseen connectors as unproven."""
        with self._lock:
            self._registry_loaded = True
            for name in connectors:
                self._connectors.setdefault(name, ConnectorHealth(connector=name))

    def record_credentials(self, connector: str, *, ok: bool, error: str = "") -> None:
        """Record whether ``connector``'s endpoint credentials resolved."""
        with self._lock:
            current = self._connectors.get(connector, ConnectorHealth(connector))
            self._connectors[connector] = replace(
                current, credentials_ok=ok, credential_error="" if ok else error
            )

    def record_cycle_success(self, connector: str) -> None:
        """Record that ``connector`` completed a cycle without error."""
        with self._lock:
            current = self._connectors.get(connector, ConnectorHealth(connector))
            self._connectors[connector] = replace(
                current,
                last_success_monotonic=self._clock(),
                consecutive_failures=0,
                next_retry_seconds=None,
            )

    def record_cycle_failure(
        self, connector: str, *, next_retry_seconds: float | None
    ) -> None:
        """Record that ``connector`` failed a cycle, and when it retries."""
        with self._lock:
            current = self._connectors.get(connector, ConnectorHealth(connector))
            self._connectors[connector] = replace(
                current,
                consecutive_failures=current.consecutive_failures + 1,
                next_retry_seconds=next_retry_seconds,
            )

    def liveness(self) -> HealthReport:
        """200 while the scheduler heartbeat is fresh; 503 naming it stale."""
        with self._lock:
            age = self._clock() - self._heartbeat
        if age <= self._window:
            return HealthReport(
                True, 200, {"status": "ok", "heartbeat_age_seconds": age}
            )
        body = {
            "status": "error",
            "component": _SCHEDULER_COMPONENT,
            "age_seconds": age,
            "max_age_seconds": self._window,
        }
        return HealthReport(False, 503, body)

    async def readiness(self) -> HealthReport:
        """200 only once the registry loaded, credentials resolved, sink usable.

        503 with every reason otherwise, plus per-connector detail (no secrets).
        The sink is asked directly (``sink.readiness()``), bounded by
        ``sink_timeout_seconds`` so a hung sink cannot hang this call.
        """
        with self._lock:
            registry_loaded = self._registry_loaded
            connectors = dict(self._connectors)
        reasons = [] if registry_loaded else ["registry not loaded"]
        unresolved = sorted(
            name
            for name, health in connectors.items()
            if health.credentials_ok is not True
        )
        if unresolved:
            reasons.append(f"credentials unresolved: {', '.join(unresolved)}")
        sink_state = await probe_sink_readiness(
            self._sink, timeout_seconds=self._sink_timeout
        )
        if not sink_state.ready:
            reasons.append(sink_reason(sink_state))
        now = self._clock()
        body: dict[str, object] = {
            "status": "ready" if not reasons else "not_ready",
            "reasons": reasons,
            "connectors": {
                name: health.snapshot(now=now) for name, health in connectors.items()
            },
        }
        return HealthReport(not reasons, 200 if not reasons else 503, body)
