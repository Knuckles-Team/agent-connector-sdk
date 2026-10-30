"""The ``ingest-worker`` console script.

Exit ``2`` before claiming anything when the engine is unreachable or lacks the
task-queue methods. SIGTERM drains: the loop finishes its current job and exits.
"""

from __future__ import annotations

import argparse
import os
import signal
import sys
from collections.abc import Callable, Sequence
from typing import Any

from agent_connector_sdk.runner.ingest_worker import (
    IngestWorkerEngine,
    WorkerStopped,
    run_ingest_worker,
)

__all__ = ["build_parser", "main"]

_REQUIRED_METHODS = ("worker_admit", "task_queue_claim", "task_queue_ack")


def build_parser() -> argparse.ArgumentParser:
    """The command-line parser."""
    parser = argparse.ArgumentParser(
        prog="ingest-worker", description="Run ingest jobs."
    )
    parser.add_argument(
        "--workers",
        type=int,
        default=None,
        help="optional request ceiling; the engine's grant decides the count",
    )
    parser.add_argument("--engine-endpoint", required=True, help="engine endpoint")
    return parser


def _connect(endpoint: str) -> IngestWorkerEngine:
    """Open the generated engine client for ``endpoint``.

    The released engine client does not yet expose the task-queue and admission
    methods (EG-DURABLE-KERNEL-R073), so this raises ``OSError`` and the command
    exits 2 rather than claiming anything.
    """
    raise OSError(f"engine client at {endpoint} lacks the task-queue methods")


def main(
    argv: Sequence[str] | None = None,
    *,
    connect: Callable[[str], IngestWorkerEngine] = _connect,
    run_job: Callable[[dict[str, Any]], None] | None = None,
) -> int:
    """Run the worker; return the process exit code."""
    args = build_parser().parse_args(argv)
    try:
        engine = connect(args.engine_endpoint)
    except OSError as exc:
        print(f"ingest-worker: engine unreachable: {exc}", file=sys.stderr)
        return 2
    missing = [m for m in _REQUIRED_METHODS if not callable(getattr(engine, m, None))]
    if missing:
        print(f"ingest-worker: engine lacks {', '.join(missing)}", file=sys.stderr)
        return 2
    stop = {"now": False}
    signal.signal(signal.SIGTERM, lambda *_: stop.update(now=True))
    try:
        run_ingest_worker(
            engine,
            run_job or (lambda job: None),
            cores=os.cpu_count() or 1,
            memory_bytes=os.sysconf("SC_PAGE_SIZE") * os.sysconf("SC_PHYS_PAGES"),
            max_workers=args.workers,
            should_stop=lambda: stop["now"],
        )
    except WorkerStopped as exc:
        print(f"ingest-worker: {exc}", file=sys.stderr)
        return 2
    return 0
