"""Artifact kind conformance checks."""

from __future__ import annotations

from collections.abc import Sequence

from agent_connector_sdk.contracts import CapturedArtifact
from agent_connector_sdk.ports.artifact_kind import ArtifactKind
from agent_connector_sdk.ports.errors import MalformedArtifactError
from agent_connector_sdk.testing.results import ConformanceResult, SessionFactory

__all__ = ["check_artifact_kind", "check_artifact_rejects_malformed"]


async def _listing(
    kind: ArtifactKind, sessions: SessionFactory
) -> tuple[CapturedArtifact, ...]:
    async with sessions() as session:
        return await kind.list_entries(session, await session.server_identity())


def _validation_problems(
    kind: ArtifactKind, entries: Sequence[CapturedArtifact]
) -> list[str]:
    problems: list[str] = []
    for entry in entries:
        try:
            kind.validate(entry)
        except MalformedArtifactError as exc:
            problems.append(f"{entry.uri}: {exc}")
            continue
    return problems


async def check_artifact_kind(
    kind: ArtifactKind, sessions: SessionFactory
) -> list[ConformanceResult]:
    """Listing is non-empty, every entry validates and maps, digests are stable."""
    first = await _listing(kind, sessions)
    second = await _listing(kind, sessions)
    problems = _validation_problems(kind, first)
    stable = first == second
    return [
        ConformanceResult(
            "artifact-listing", bool(first), "" if first else "no entries listed"
        ),
        ConformanceResult("artifact-validation", not problems, "; ".join(problems)),
        ConformanceResult(
            "artifact-determinism", stable, "" if stable else "listings differ"
        ),
    ]


def check_artifact_rejects_malformed(
    kind: ArtifactKind, malformed: CapturedArtifact
) -> ConformanceResult:
    """A malformed entry of this kind is rejected by ``validate``."""
    try:
        kind.validate(malformed)
    except MalformedArtifactError:
        return ConformanceResult("artifact-malformed-rejection", True)
    return ConformanceResult(
        "artifact-malformed-rejection", False, f"{malformed.uri} was accepted"
    )
