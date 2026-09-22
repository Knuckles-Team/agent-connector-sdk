"""Artifact kind conformance checks."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from agent_connector_sdk.certify.fingerprints import (
    EmptyToolSchemaError,
    tool_fingerprint,
    tool_name,
)
from agent_connector_sdk.contracts import CapturedArtifact
from agent_connector_sdk.ports.artifact_kind import ArtifactKind
from agent_connector_sdk.ports.errors import MalformedArtifactError
from agent_connector_sdk.testing.results import ConformanceResult, SessionFactory

__all__ = [
    "check_artifact_kind",
    "check_artifact_rejects_malformed",
    "check_tool_contract_pin_normalization",
]


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


async def check_tool_contract_pin_normalization(
    kind: ArtifactKind, sessions: SessionFactory
) -> ConformanceResult:
    """Independently recompute every tool entry's D18 ``sdk_contract_pin``.

    EG cannot recompute the SDK's compatibility-fingerprint schema
    normalization without reimplementing it
    (``PACK-IMPORT-DESIGN-DRAFT.md`` Section 5.1); its own write-time
    validation dropped the rule for exactly that reason (Section 3.10.1) and
    named the SDK TCK as the replacement (EH-199). This check is that
    replacement: it recomputes the pin from the same ``tools/list``
    definition the pack was built from and rejects any entry whose stored
    pin drifted from the recomputation, including the EH-215 regression
    shape where the served definition has no client-visible input schema at
    all (EH-135).
    """
    async with sessions() as session:
        tools = await session.list_tools()
        entries = await kind.list_entries(session, await session.server_identity())
    problems = _pin_problems(tools, entries)
    return ConformanceResult(
        "artifact-contract-pin-normalization", not problems, "; ".join(problems)
    )


def _pin_problems(
    tools: Sequence[Any], entries: Sequence[CapturedArtifact]
) -> list[str]:
    by_name = {tool_name(tool): tool for tool in tools}
    problems: list[str] = []
    for entry in entries:
        tool = by_name.get(entry.name)
        if tool is None:
            continue
        problems.extend(_pin_problem(entry, tool))
    return problems


def _pin_problem(entry: CapturedArtifact, tool: Any) -> list[str]:
    pin = entry.annotations.sdk_contract_pin if entry.annotations else None
    try:
        recomputed = tool_fingerprint(tool)
    except EmptyToolSchemaError:
        return [f"{entry.uri}: tools/list served no client-visible input schema"]
    if pin != recomputed:
        return [
            f"{entry.uri}: contract pin does not match the recomputed D18 fingerprint"
        ]
    return []
