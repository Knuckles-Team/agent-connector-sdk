"""Parse and flatten Git tree objects read through ``git cat-file --batch``.

Kept apart from the provider that drives the Git subprocess: every function
here is pure or takes an already-open pipe, so the wire protocol (one tree
object requested and parsed at a time) and the walk result (one flat,
sorted list of blob entries per root) are each independently testable.
"""

from __future__ import annotations

import asyncio
from collections import deque

from agent_connector_sdk.repository.errors import RepositoryTransportError
from agent_connector_sdk.repository.refs import RepositoryTreeEntry

#: Internal wire-protocol module: nothing here is public SDK surface.
__all__: list[str] = []

_TREE_MODE = b"40000"
_BLOB_MODES = (b"100644", b"100755", b"120000")
TreeRecord = tuple[bytes, str, str]
TreeObjects = dict[str, tuple[TreeRecord, ...]]


def _parse_tree_payload(oid: str, payload: bytes) -> tuple[TreeRecord, ...]:
    """Parse one ``git cat-file --batch`` tree payload into ``(mode, name, child)``."""
    record_size = len(bytes.fromhex(oid))
    records: list[TreeRecord] = []
    offset = 0
    while offset < len(payload):
        boundary = payload.find(b"\0", offset)
        if boundary < 0 or boundary + 1 + record_size > len(payload):
            raise RepositoryTransportError("git cat-file returned malformed tree")
        mode_name = payload[offset:boundary]
        object_id = payload[boundary + 1 : boundary + 1 + record_size]
        offset = boundary + 1 + record_size
        mode, name_bytes = mode_name.split(b" ", 1)
        records.append((mode, name_bytes.decode("utf-8"), object_id.hex()))
    return tuple(records)


async def _read_one_tree(
    stdin: asyncio.StreamWriter,
    stdout: asyncio.StreamReader,
    oid: str,
) -> tuple[TreeRecord, ...]:
    """Request one tree object over an open ``git cat-file --batch`` pipe."""
    stdin.write(f"{oid}\n".encode("ascii"))
    await stdin.drain()
    header = (await stdout.readline()).split()
    if len(header) != 3 or header[0].decode("ascii") != oid or header[1] != b"tree":
        raise RepositoryTransportError(f"git cat-file did not return tree {oid}")
    size = int(header[2])
    raw = await stdout.readexactly(size + 1)
    if raw[-1:] != b"\n":
        raise RepositoryTransportError("git cat-file returned malformed tree framing")
    return _parse_tree_payload(oid, raw[:-1])


async def _collect_tree_objects(
    stdin: asyncio.StreamWriter,
    stdout: asyncio.StreamReader,
    roots: tuple[str, ...],
) -> TreeObjects:
    """Read every tree reachable from ``roots`` over one open batch pipe."""
    objects: TreeObjects = {}
    pending = deque(roots)
    requested: set[str] = set()
    while pending:
        oid = pending.popleft()
        if oid in requested:
            continue
        requested.add(oid)
        records = await _read_one_tree(stdin, stdout, oid)
        objects[oid] = records
        pending.extend(
            child
            for mode, _, child in records
            if mode == _TREE_MODE and child not in requested
        )
    return objects


async def _check_batch_exit(process: asyncio.subprocess.Process) -> None:
    if process.returncode == 0:
        return
    if process.stderr is None:
        raise RepositoryTransportError("git cat-file failed with no stderr pipe")
    message = (await process.stderr.read()).decode("utf-8", "replace").strip()
    raise RepositoryTransportError(f"git cat-file failed: {message}")


def _tree_children(
    stack: list[tuple[str, str]],
    entries: list[RepositoryTreeEntry],
    prefix: str,
    records: tuple[TreeRecord, ...],
) -> None:
    """Apply one tree object's records: queue child trees, collect blob entries."""
    for mode, name, child in records:
        path = f"{prefix}{name}"
        if mode == _TREE_MODE:
            stack.append((child, f"{path}/"))
        elif mode in _BLOB_MODES:
            entries.append(RepositoryTreeEntry(path=path, blob_id=child))


def _flatten_tree(root: str, objects: TreeObjects) -> tuple[RepositoryTreeEntry, ...]:
    """Walk ``objects`` from ``root``, collecting blob entries by full path."""
    entries: list[RepositoryTreeEntry] = []
    stack = [(root, "")]
    while stack:
        oid, prefix = stack.pop()
        _tree_children(stack, entries, prefix, objects[oid])
    return tuple(sorted(entries, key=lambda item: item.path))
