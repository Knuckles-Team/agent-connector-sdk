"""Ingest under an engine-accepted contract.

The engine owns acceptance (``MEDULLA-TYPED-PACKS-R101``). The SDK compares the
accepted digest with the local declaration digest before any batch and names
the contract in the run evidence.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from epistemic_graph.generated.source_ingestion import SourceIngestionReceipt

from scion_sdk.ingest.errors import ContractNotAcceptedError, IngestError
from scion_sdk.ingest.model import IngestBinding

__all__ = [
    "AcceptedContract",
    "ContractEvidence",
    "ContractTransport",
    "contract_evidence",
    "require_accepted",
]


@dataclass(frozen=True)
class AcceptedContract:
    """What the engine reports as accepted for one connector."""

    digest: str
    revision: str = ""


@runtime_checkable
class ContractTransport(Protocol):
    """An ingest transport that can read the engine's accepted contract."""

    async def accepted_contract(self, connector: str) -> AcceptedContract | None:
        """The accepted contract, or ``None`` when the engine has none."""
        ...


@dataclass(frozen=True)
class ContractEvidence:
    """The contract one batch ran under, matched to the engine receipt."""

    iri: str
    revision: str
    digest: str
    mapping_digests: tuple[str, ...]
    receipt_id: str


async def require_accepted(transport: object, binding: IngestBinding) -> None:
    """Refuse with ``contract_not_accepted`` unless the digests agree."""
    if not binding.contract_iri:
        return
    if not isinstance(transport, ContractTransport):
        raise ContractNotAcceptedError(
            "contract_not_accepted: the transport cannot read the accepted contract"
        )
    accepted = await transport.accepted_contract(binding.connector)
    if accepted is None or accepted.digest != binding.contract_digest:
        raise ContractNotAcceptedError(
            f"contract_not_accepted: {binding.contract_iri} is not the "
            "engine's accepted contract"
        )
    if (
        binding.contract_revision
        and accepted.revision
        and accepted.revision != binding.contract_revision
    ):
        raise ContractNotAcceptedError(
            f"contract_not_accepted: revision {binding.contract_revision!r} "
            f"is not accepted ({accepted.revision!r})"
        )


def contract_evidence(
    binding: IngestBinding, receipt: SourceIngestionReceipt
) -> ContractEvidence:
    """Name the contract for one batch; it must match the engine's receipt."""
    prefix = f"{binding.contract_iri}#"
    digests = []
    for mapping in receipt.mappings:
        if mapping.connector_pack_digest != binding.contract_digest:
            raise IngestError("receipt mapping names a different contract digest")
        if not mapping.mapping_reference.startswith(prefix):
            raise IngestError("receipt mapping is outside the bound contract")
        digests.append(str(mapping.mapping_digest))
    return ContractEvidence(
        iri=binding.contract_iri,
        revision=binding.contract_revision,
        digest=binding.contract_digest,
        mapping_digests=tuple(digests),
        receipt_id=receipt.receipt_id,
    )
