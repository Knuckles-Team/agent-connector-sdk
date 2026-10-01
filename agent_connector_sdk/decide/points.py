"""The two connector decision points the SDK asks EG's ``Decide``.

Ported (not imported) from agent-utilities' equivalent points registry,
trimmed to only the two questions this package's call sites ask -- the SDK
does not carry agent-utilities' full decision-point catalog. A point is
only consulted when a :class:`Binding` pins its feature schema; an unbound
point runs its deterministic fallback without ever reaching EG. That keeps
EG off every hot path until an operator has published the schema (and,
later, a fitted head).
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from enum import Enum
from typing import Any, Protocol


class LogMode(Enum):
    """Whether a point's records are made durable in the decision log.

    ``SAMPLED`` is the evaluate-only mode for high-frequency, low-stakes
    points: one record in :attr:`DecisionPoint.sample_every`, chosen by
    record digest so the sample is reproducible, never by a clock.
    """

    ALWAYS = "always"
    SAMPLED = "sampled"
    NEVER = "never"


@dataclass(frozen=True, slots=True)
class DecisionPoint:
    """One decision the SDK asks EG to make."""

    question_id: str
    kind: str
    safety: str = "ordinary"
    log_mode: LogMode = LogMode.SAMPLED
    sample_every: int = 1

    @property
    def schema_component_id(self) -> str:
        """The FeatureSchema component an operator publishes for this point."""
        return f"decide.schema.{self.question_id}"


#: Which of a connector's tools serves one request; evaluate-only, sampled.
CONNECTOR_TOOL = DecisionPoint("au.connector.tool", "route", sample_every=16)
#: Which write-back proposal (or none); every record is durable.
CONNECTOR_WRITEBACK = DecisionPoint(
    "au.connector.writeback", "route", safety="write_back", log_mode=LogMode.ALWAYS
)

#: Every decision point this package can ask, by question id.
POINTS: dict[str, DecisionPoint] = {
    p.question_id: p for p in (CONNECTOR_TOOL, CONNECTOR_WRITEBACK)
}


@dataclass(frozen=True, slots=True)
class Binding:
    """The pinned components one point decides under.

    ``feature_schema`` and ``head`` are EG ``ComponentDependency`` dicts
    (``component_id``, ``kind``, ``definition_digest``); ``policy`` is a
    ``DecisionPolicyRef`` dict. No head means EG runs the deterministic
    ladder only, which under the default cold start abstains.
    """

    feature_schema: Mapping[str, Any]
    policy: Mapping[str, Any]
    head: Mapping[str, Any] | None = None


class Bindings(Protocol):
    """Where a point's binding comes from (config, a library lookup, ...)."""

    def binding_for(self, point: DecisionPoint) -> Binding | None: ...


@dataclass(frozen=True, slots=True)
class StaticBindings:
    """Bindings from a mapping of question id to :class:`Binding`."""

    by_question: Mapping[str, Binding]

    def binding_for(self, point: DecisionPoint) -> Binding | None:
        return self.by_question.get(point.question_id)


#: A :class:`Bindings` that never pins a schema -- every point stays
#: deterministic-fallback-only. The safe default until an operator publishes
#: real bindings.
EMPTY_BINDINGS = StaticBindings({})


def point(question_id: str) -> DecisionPoint:
    """The registered point for ``question_id`` (``KeyError`` names it)."""
    return POINTS[question_id]


__all__ = [
    "CONNECTOR_TOOL",
    "CONNECTOR_WRITEBACK",
    "EMPTY_BINDINGS",
    "POINTS",
    "Binding",
    "Bindings",
    "DecisionPoint",
    "LogMode",
    "StaticBindings",
    "point",
]
