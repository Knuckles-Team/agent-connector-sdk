"""Per-parent fan-out of a declared source (SDK-SOURCE-INGEST-R004.28).

A source that reads something owned by another record (the work items of a
project) declares ``for_each``: the parent source it follows, the tool
argument that receives the parent value, and the parent record field the
value comes from. The runner sweeps the parent source, then runs the child
once per parent record, bounded by :data:`MAX_FAN_OUT`.
"""

from __future__ import annotations

from collections.abc import Mapping

from pydantic import BaseModel, ConfigDict, Field

__all__ = ["MAX_FAN_OUT", "ForEach", "ForEachRefusal", "check_for_each"]

#: The most parent records one child source fans out over.
MAX_FAN_OUT = 200


class ForEach(BaseModel):
    """Run a source once per record of ``source``, passing ``field`` as ``argument``."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    source: str = Field(min_length=1, description="The parent source_id to follow.")
    argument: str = Field(
        min_length=1, description="The child tool argument that receives the value."
    )
    field: str = Field(
        default="id", min_length=1, description="The parent record field to pass."
    )


class ForEachRefusal(ValueError):
    """A fan-out declaration or run refused; ``reason`` is a stable machine code."""

    def __init__(self, reason: str, message: str) -> None:
        super().__init__(f"{reason}: {message}")
        self.reason = reason


def check_for_each(parents: Mapping[str, ForEach | None]) -> None:
    """Refuse an unknown parent source or a cycle.

    Args:
        parents: Every source id mapped to its ``for_each`` (or ``None``).

    Raises:
        ForEachRefusal: ``unknown_parent_source`` or ``for_each_cycle``.
    """
    for source_id, link in parents.items():
        chain = [source_id]
        while link is not None:
            if link.source not in parents:
                raise ForEachRefusal(
                    "unknown_parent_source",
                    f"source {chain[-1]!r} follows undeclared source {link.source!r}",
                )
            if link.source in chain:
                raise ForEachRefusal(
                    "for_each_cycle",
                    f"sources {' -> '.join([*chain, link.source])} form a cycle",
                )
            chain.append(link.source)
            link = parents[link.source]
