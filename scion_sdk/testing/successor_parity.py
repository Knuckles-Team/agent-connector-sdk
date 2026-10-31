"""SCION-CONNECTOR-CONTROL-R020.4: a successor release keeps every predecessor tool."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Any

__all__ = ["SuccessorToolParity", "compare_successor_tools"]


@dataclass(frozen=True)
class SuccessorToolParity:
    """Per-tool outcome of comparing a predecessor release with its successor."""

    kept: tuple[str, ...]
    split: Mapping[str, tuple[str, ...]]
    covered: Mapping[str, str]
    lost: tuple[str, ...]
    dispatch_remaining: tuple[str, ...]

    @property
    def accepted(self) -> bool:
        """True when no predecessor tool is lost and no dispatch tool remains."""
        return not self.lost and not self.dispatch_remaining


def compare_successor_tools(
    predecessor: Iterable[str],
    successor: Iterable[str],
    *,
    covered_by: Mapping[str, str] | None = None,
    dispatch_tools: Iterable[str] = (),
) -> SuccessorToolParity:
    """Classify each predecessor tool as kept, split, covered or lost.

    ``covered_by`` maps an old name to the served per-operation tool that makes
    the same API call. A served action-dispatch tool fails the release.
    """
    old = list(predecessor)
    new = list(successor)
    if len(set(old)) != len(old) or len(set(new)) != len(new):
        raise ValueError("tool lists must not contain duplicate names")
    served = set(new)
    covers = dict(covered_by or {})
    kept: list[str] = []
    split: dict[str, tuple[str, ...]] = {}
    covered: dict[str, str] = {}
    lost: list[str] = []
    for name in old:
        if name in served:
            kept.append(name)
            continue
        kind, value = _classify_missing(name, served, covers)
        if kind == "split":
            split[name] = value
        elif kind == "covered":
            covered[name] = value
        else:
            lost.append(name)
    remaining = tuple(sorted(served & set(dispatch_tools)))
    return SuccessorToolParity(tuple(kept), split, covered, tuple(lost), remaining)


def _classify_missing(
    name: str, served: set[str], covers: Mapping[str, str]
) -> tuple[str, Any]:
    """Classify a predecessor tool absent from the successor."""
    parts = tuple(sorted(n for n in served if n.startswith(f"{name}_")))
    if parts:
        return "split", parts
    if covers.get(name) in served:
        return "covered", covers[name]
    return "lost", None
