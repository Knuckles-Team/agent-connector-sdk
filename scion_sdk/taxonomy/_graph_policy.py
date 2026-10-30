"""Validate host approval for one bounded taxonomy graph."""

from collections.abc import Mapping, Sequence

from scion_sdk.taxonomy.provider import _valid_id


def _validate_crosswalk(
    provider: str, identifiers: Sequence[str], crosswalk: Mapping[str, tuple[str, str]]
) -> None:
    prefix = "NCBITaxon" if provider == "ncbi" else "GBIF"
    expected = {f"{prefix}:{identifier}" for identifier in identifiers}
    if set(crosswalk) != expected:
        raise ValueError("crosswalk does not cover the admitted taxon set")
    _crosswalk_pairs(provider, identifiers, crosswalk, prefix=prefix)


def _valid_pair(pair: object) -> bool:
    return (
        isinstance(pair, tuple)
        and len(pair) == 2
        and all(_valid_id(value) for value in pair)
    )


def _crosswalk_pairs(
    provider: str,
    identifiers: Sequence[str],
    crosswalk: Mapping[str, tuple[str, str]],
    *,
    prefix: str,
) -> None:
    pairs = list(crosswalk.values())
    if any(not _valid_pair(pair) for pair in pairs):
        raise ValueError("invalid taxon crosswalk")
    if len({pair[0] for pair in pairs}) != len(pairs) or len(
        {pair[1] for pair in pairs}
    ) != len(pairs):
        raise ValueError("taxon crosswalk must be one-to-one")
    index = 0 if provider == "ncbi" else 1
    if any(
        crosswalk[f"{prefix}:{identifier}"][index] != identifier
        for identifier in identifiers
    ):
        raise ValueError("crosswalk conflicts with admitted provider identity")


def _validate_policy(
    identifiers: Sequence[str], *, max_records: int, ranks: Mapping[str, str]
) -> None:
    _validate_bound(identifiers, max_records)
    if len(identifiers) + min(len(identifiers), len(ranks)) > 1024:
        raise ValueError("taxonomy graph exceeds source batch record bound")
    if not ranks or len(set(ranks.values())) != len(ranks):
        raise ValueError("invalid admitted taxon ranks")
    if any(
        not isinstance(key, str) or not key or not isinstance(value, str) or not value
        for key, value in ranks.items()
    ):
        raise ValueError("invalid admitted taxon ranks")


def _validate_bound(identifiers: Sequence[str], max_records: int) -> None:
    if (
        not identifiers
        or type(max_records) is not int
        or not 1 <= max_records <= 1000
        or len(identifiers) > max_records
    ):
        raise ValueError("invalid taxonomy graph bound")
    if len(set(identifiers)) != len(identifiers) or any(
        not _valid_id(value) for value in identifiers
    ):
        raise ValueError("invalid taxonomy identifiers")
