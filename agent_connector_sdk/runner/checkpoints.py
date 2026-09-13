"""A checkpoint store of one JSON file per connector, replaced atomically."""

from __future__ import annotations

import os
import re
from pathlib import Path

import anyio
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from agent_connector_sdk.contracts import (
    IngestionReceipt,
    PackImportReceipt,
    SyncCursor,
)
from agent_connector_sdk.runner.errors import CheckpointStoreError

__all__ = ["JsonFileCheckpointStore"]

_SAFE_NAME = re.compile(r"[a-z0-9][a-z0-9._-]{0,127}")


class _ConnectorState(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    pack_digest: str | None = None
    cursors: dict[str, SyncCursor] = Field(default_factory=dict)


def _read_state(path: Path) -> _ConnectorState:
    try:
        payload = path.read_bytes()
    except FileNotFoundError:
        return _ConnectorState()
    except OSError as exc:
        raise CheckpointStoreError(f"checkpoint {path.name} is unreadable") from exc
    try:
        return _ConnectorState.model_validate_json(payload)
    except ValidationError as exc:
        raise CheckpointStoreError(f"checkpoint {path.name} is corrupt") from exc


def _write_state(path: Path, state: _ConnectorState) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    with temporary.open("wb") as handle:
        handle.write(state.model_dump_json().encode("utf-8"))
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, path)


class JsonFileCheckpointStore:
    """Committed cursors and pack digests under ``directory``.

    A corrupt file raises instead of restarting a stream from the beginning.
    """

    def __init__(self, directory: Path) -> None:
        self._directory = directory
        self._lock = anyio.Lock()

    def _path(self, connector: str) -> Path:
        if not _SAFE_NAME.fullmatch(connector):
            raise CheckpointStoreError("connector name is not a safe file name")
        return self._directory / f"{connector}.json"

    async def _load(self, connector: str) -> _ConnectorState:
        return await anyio.to_thread.run_sync(_read_state, self._path(connector))

    async def committed_cursor(self, connector: str, stream: str) -> SyncCursor | None:
        """The last committed cursor of ``stream``."""
        return (await self._load(connector)).cursors.get(stream)

    async def imported_pack_digest(self, connector: str) -> str | None:
        """The digest of the last imported pack."""
        return (await self._load(connector)).pack_digest

    async def record_ingestion(self, connector: str, receipt: IngestionReceipt) -> None:
        """Store the cursor the receipt committed."""
        cursor = receipt.committed_cursor
        async with self._lock:
            state = await self._load(connector)
            cursors = {**state.cursors, cursor.stream: cursor}
            updated = state.model_copy(update={"cursors": cursors})
            await anyio.to_thread.run_sync(_write_state, self._path(connector), updated)

    async def record_pack_import(
        self, connector: str, receipt: PackImportReceipt
    ) -> None:
        """Store the pack digest the receipt acknowledged."""
        async with self._lock:
            state = await self._load(connector)
            updated = state.model_copy(update={"pack_digest": receipt.pack_digest})
            await anyio.to_thread.run_sync(_write_state, self._path(connector), updated)
