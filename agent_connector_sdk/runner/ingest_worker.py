"""The ingest worker runner: the engine decides, the worker asks and obeys.

The worker owns no scheduling policy. Admission, lane, slot count, lease and
retry schedule all come from the engine reply; the worker runs the job body
and acks only after the body returned. A body that dies sends no ack, so the
engine redelivers the task (at-least-once).
"""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Protocol

__all__ = [
    "IngestWorkerEngine",
    "WorkerGrant",
    "WorkerStopped",
    "run_ingest_worker",
]


class WorkerStopped(Exception):
    """The worker could not run: admission refused or the engine gave no floor."""


@dataclass(frozen=True)
class WorkerGrant:
    """The engine's admission answer for this worker."""

    slots: int
    lane: str
    lease_seconds: float
    retry_after_seconds: float


class IngestWorkerEngine(Protocol):
    """The generated-client surface the worker uses (task queue and admission)."""

    def worker_admit(
        self, cores: int, memory_bytes: int, max_workers: int | None
    ) -> dict[str, Any]: ...

    def task_queue_claim(
        self, queue: str, lease_seconds: float
    ) -> dict[str, Any] | None: ...

    def task_queue_ack(self, task_id: str, outcome: str, detail: str = "") -> None: ...


def _grant(reply: dict[str, Any]) -> WorkerGrant:
    """Read a grant from an engine reply; refuse a reply with a missing value."""
    if reply.get("refused"):
        raise WorkerStopped(f"admission refused: {reply['refused']}")
    try:
        return WorkerGrant(
            slots=int(reply["slots"]),
            lane=str(reply["reserved_lane"]),
            lease_seconds=float(reply["lease_seconds"]),
            retry_after_seconds=float(reply["retry_after_seconds"]),
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise WorkerStopped(f"engine reply lacks a policy value: {exc!r}") from exc


def run_ingest_worker(
    engine: IngestWorkerEngine,
    run_job: Callable[[dict[str, Any]], None],
    *,
    cores: int,
    memory_bytes: int,
    max_workers: int | None = None,
    should_stop: Callable[[], bool] = lambda: False,
    sleep: Callable[[float], None] = time.sleep,
    commit: Callable[[dict[str, Any]], None] = lambda job: None,
) -> int:
    """Claim and run jobs until ``should_stop``; return the number acked.

    Raises :class:`WorkerStopped` when admission is refused or a policy value is
    absent from the engine reply; the worker never substitutes its own.
    """
    grant = _grant(engine.worker_admit(cores, memory_bytes, max_workers))
    done = 0
    while not should_stop():
        job = engine.task_queue_claim(grant.lane, grant.lease_seconds)
        if job is None:
            sleep(grant.retry_after_seconds)
            continue
        try:
            run_job(job)
        except Exception as exc:  # reported to the engine, which owns retry
            engine.task_queue_ack(str(job["task_id"]), "failed", repr(exc))
            continue
        engine.task_queue_ack(str(job["task_id"]), "succeeded")
        commit(job)
        done += 1
    return done
