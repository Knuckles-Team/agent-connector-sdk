"""MessagePack sizing for foreign-read rows (private sibling of foreign_read)."""

from __future__ import annotations

import importlib
from collections.abc import Sequence
from typing import TYPE_CHECKING, Any, cast

if TYPE_CHECKING:
    from scion_sdk.adapters._foreign_read_models import ForeignReadRow


def _pack_row(
    wire: dict[str, Any], packers: tuple[Any, Any], pack_binary: Any
) -> bytearray:
    normal, score = packers
    columns = pack_binary(dict(sorted(wire["columns"].items())))
    parts = (
        normal.pack_map_header(4),
        normal.pack("id"),
        normal.pack(wire["id"]),
        normal.pack("score"),
        normal.pack(None) if wire["score"] is None else score.pack(wire["score"]),
        normal.pack("columns"),
        columns,
        normal.pack("provenance"),
        normal.pack(wire["provenance"]),
    )
    return bytearray(b"".join(parts))


def _pack_rows(rows: Sequence[ForeignReadRow]) -> bytearray:
    from epistemic_graph.client import _pack_binary_msgpack

    msgpack = cast(Any, importlib.import_module("msgpack"))
    # ``use_single_float`` is applied only to the typed ``ForeignReadRow.score``
    # field; JSON column values keep the EG client codec's f64 behaviour.
    normal = msgpack.Packer(use_bin_type=True)
    score = msgpack.Packer(use_bin_type=True, use_single_float=True)
    encoded = bytearray(normal.pack_array_header(len(rows)))
    for row in rows:
        wire = row.model_dump(mode="json")
        encoded.extend(_pack_row(wire, (normal, score), _pack_binary_msgpack))
    return encoded


def _encoded_rows_bytes(rows: Sequence[ForeignReadRow]) -> int:
    """Return the EG client codec size for the named Rust row sequence.

    The engine's Rust boundary uses ``rmp_serde::to_vec_named(rows)``; the
    existing EG client owns the matching MessagePack transport codec. Rust's
    ``BTreeMap`` rows are normalized to sorted mapping keys before packing.
    """
    try:
        return len(_pack_rows(rows))
    except Exception:
        raise ValueError("foreign-read MessagePack codec unavailable") from None
