"""Bounded, replaceable rendering of fitted analysis results."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from math import isfinite

from pydantic import StrictFloat


@dataclass(frozen=True)
class ReadableForm:
    """Declared template, bound and optional scoring information."""

    template_id: str
    max_chars: int = 4000
    question_set_ref: str | None = None
    score: StrictFloat | None = None

    def __post_init__(self) -> None:
        if not self.template_id:
            raise ValueError("template_id is required")
        if (
            isinstance(self.max_chars, bool)
            or not isinstance(self.max_chars, int)
            or self.max_chars < 0
        ):
            raise ValueError("max_chars must be nonnegative")
        if self.score is not None and (
            isinstance(self.score, bool)
            or not isinstance(self.score, (int, float))
            or not isfinite(self.score)
            or not 0 <= self.score <= 1
        ):
            raise ValueError("score must be a finite ratio between zero and one")


@dataclass(frozen=True)
class FittedTerm:
    """A fitted term and its reported effect."""

    name: str
    effect: str


@dataclass(frozen=True)
class FittedAnalysis:
    """The fitted terms and stated quality supplied by the analysis owner."""

    terms: tuple[FittedTerm, ...]
    fit_quality: str


def default_readable_renderer(result: FittedAnalysis) -> str:
    """Render each supplied term and the stated quality on separate lines."""
    lines = [f"{term.name}: {term.effect}" for term in result.terms]
    lines.append(f"Fit quality: {result.fit_quality}")
    return "\n".join(lines)


def render_readable(
    result: FittedAnalysis,
    form: ReadableForm,
    *,
    renderer: Callable[[FittedAnalysis], str] = default_readable_renderer,
) -> str:
    """Render text using the caller's renderer, capped at the declared bound."""
    return renderer(result)[: form.max_chars]
