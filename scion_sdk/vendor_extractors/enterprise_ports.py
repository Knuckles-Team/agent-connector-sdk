"""Host-supplied ports for enterprise operation dispatch."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from scion_sdk.identity import ActorContext
from scion_sdk.ports.writeback_ledger import WriteBackLedger
from scion_sdk.vendor_extractors.enterprise_contract import (
    EnterpriseCapability,
    EnterpriseOperation,
)
from scion_sdk.writeback.connector import DurableWritableConnector


class EnterpriseAuthority(Protocol):
    """The host verifies actor, company and operation authority before a call."""

    async def authorize(
        self, actor: ActorContext, request: EnterpriseOperation
    ) -> bool: ...


class EnterpriseReader(Protocol):
    """A connector translates one approved read into the common result."""

    async def read(self, request: EnterpriseOperation) -> object: ...


@dataclass(frozen=True)
class EnterpriseWriteTarget:
    """The host-qualified connector writer and its durable receipt authority."""

    writer: DurableWritableConnector
    ledger: WriteBackLedger


class EnterpriseWriteAdmission(Protocol):
    """Admit the exact installed source operation and its transaction contract."""

    async def admit(
        self,
        actor: ActorContext,
        request: EnterpriseOperation,
        capability: EnterpriseCapability,
    ) -> EnterpriseWriteTarget | None: ...
