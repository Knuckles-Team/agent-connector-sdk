"""Host-authorized bounded local workspace reads."""

from __future__ import annotations

import asyncio
import hashlib
import time
from pathlib import Path
from typing import Any

from anyio import BrokenWorkerProcess, to_process
from pydantic import ValidationError

from scion_sdk.adapters.bookmark_io import _read_file
from scion_sdk.adapters.bookmark_models import BookmarkReadError
from scion_sdk.adapters.workspace_models import (
    WorkspaceFile,
    WorkspaceLocation,
    WorkspaceOutcome,
    WorkspaceRequest,
)
from scion_sdk.adapters.workspace_parse import (
    WorkspaceParseError,
    parse_workspace,
)

__all__ = ["WorkspaceReader", "register_workspace_tool"]

_SUFFIXES = {
    "text": ".txt",
    "pdf": ".pdf",
    "docx": ".docx",
    "xlsx": ".xlsx",
    "vtt": ".vtt",
    "srt": ".srt",
}


class WorkspaceReader:
    """Read declared files within an already authorized local root.

    Caller authentication and authorization are the registering host's
    responsibility; this reader binds the request to its configured authority.
    """

    def __init__(self, root: Path, *, authority: str) -> None:
        if not root.is_absolute() or not authority:
            raise ValueError("absolute root and authority are required")
        self._root = root
        self._authority = authority

    async def read(self, request: WorkspaceRequest) -> tuple[WorkspaceOutcome, ...]:
        """Return one ordered result for each manifest entry.

        Timeouts report unfinished files as cancelled and terminate active
        parser processes before returning.
        """
        request = WorkspaceRequest.model_validate(request.model_dump())
        if request.root_authority != self._authority:
            raise ValueError("workspace authority mismatch")
        limit = asyncio.Semaphore(request.max_tasks)

        async def one(file: WorkspaceFile) -> WorkspaceOutcome:
            async with limit:
                return await self._run_process(file, request)

        tasks = [asyncio.create_task(one(file)) for file in request.files]
        try:
            return await _collect(tasks, request)
        except BaseException:
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            raise

    async def _run_process(
        self, file: WorkspaceFile, request: WorkspaceRequest
    ) -> WorkspaceOutcome:
        start = asyncio.get_running_loop().time()
        try:
            return await to_process.run_sync(
                self._read_one, file, request, cancellable=True
            )
        except (BrokenWorkerProcess, OSError):
            return WorkspaceOutcome(
                file=file,
                outcome="failed",
                reason="parser_unavailable",
                elapsed_seconds=asyncio.get_running_loop().time() - start,
            )

    def _read_one(
        self, file: WorkspaceFile, request: WorkspaceRequest
    ) -> WorkspaceOutcome:
        start = time.monotonic()
        try:
            locations = self._extract(file, request)
            return WorkspaceOutcome(
                file=file,
                outcome="ok",
                locations=locations,
                elapsed_seconds=time.monotonic() - start,
            )
        except ValidationError:
            return WorkspaceOutcome(
                file=file,
                outcome="failed",
                reason="limit_exceeded",
                elapsed_seconds=time.monotonic() - start,
            )
        except WorkspaceParseError as exc:
            return WorkspaceOutcome(
                file=file,
                outcome="failed",
                reason=exc.reason,
                elapsed_seconds=time.monotonic() - start,
            )

    def _extract(
        self, file: WorkspaceFile, request: WorkspaceRequest
    ) -> tuple[WorkspaceLocation, ...]:
        if not file.relative_path.lower().endswith(_SUFFIXES[file.format]):
            raise WorkspaceParseError("unsupported_type")
        if file.parser_revision != "1":
            raise WorkspaceParseError("parser_unavailable")
        try:
            data = _read_file(self._root, file.relative_path, request.max_file_bytes)
        except BookmarkReadError as exc:
            raise WorkspaceParseError(
                "limit_exceeded"
                if exc.reason == "limit_exceeded"
                else "invalid_content"
                if exc.reason == "invalid_content"
                else "access_denied"
            ) from None
        if (
            len(data) != file.size_bytes
            or hashlib.sha256(data).hexdigest() != file.sha256
        ):
            raise WorkspaceParseError("invalid_content")
        return parse_workspace(
            data,
            file.format,
            expanded=request.max_expanded_bytes,
            max_pages=request.max_pages,
        )


async def _collect(
    tasks: list[asyncio.Task[WorkspaceOutcome]], request: WorkspaceRequest
) -> tuple[WorkspaceOutcome, ...]:
    done, pending = await asyncio.wait(tasks, timeout=request.deadline_seconds)
    for task in pending:
        task.cancel()
    await asyncio.gather(*pending, return_exceptions=True)
    return tuple(
        task.result()
        if task in done
        else WorkspaceOutcome(
            file=file,
            outcome="failed",
            reason="cancelled",
            elapsed_seconds=request.deadline_seconds,
        )
        for file, task in zip(request.files, tasks, strict=True)
    )


def register_workspace_tool(server: Any, reader: WorkspaceReader) -> None:
    """Register a read-only method on a host-authenticated MCP server."""

    async def workspace_read(request: WorkspaceRequest) -> tuple[WorkspaceOutcome, ...]:
        """Read an immutable manifest of files from the authorized root."""
        return await reader.read(request)

    server.tool(name="workspace_read", annotations={"readOnlyHint": True})(
        workspace_read
    )
