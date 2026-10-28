"""Shared host policy validation for bounded earth-observation streams."""

from collections.abc import Sequence

from agent_connector_sdk.taxonomy.provider import _valid_identifier_batch


def _validate_stream_policy(
    tenant: str,
    name: str,
    connector: str,
    *,
    revision: str,
    identifiers: Sequence[str],
    batch_size: int,
) -> None:
    """Refuse missing authority, duplicate IDs and unbounded source pages."""
    if not all((tenant, name, connector, revision)) or not _valid_identifier_batch(
        identifiers, batch_size
    ):
        raise ValueError("invalid earth-observation stream policy")
