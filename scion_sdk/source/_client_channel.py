"""Transport channel of the source client: deadline, refusals and receipts."""

from __future__ import annotations

import asyncio
from collections.abc import Mapping
from typing import Any

from pydantic import ValidationError

from scion_sdk.source._client_models import (
    REFUSAL_REASONS,
    PathOutcome,
    Provenance,
    Receipt,
    SourceRefusal,
    SourceRefusedError,
    SourceTransport,
    _digest,
    _Model,
)


class _SourceChannel:
    """Calls the transport under one deadline and remembers write receipts."""

    def __init__(self, transport: SourceTransport, deadline: float) -> None:
        self._transport = transport
        self._deadline = deadline
        self.receipts: dict[str, Receipt] = {}

    def cursor(
        self, continuation: str, binding: str, operation: str, operation_id: str
    ) -> str:
        """The provider cursor inside a continuation bound to this request."""
        prefix, _, cursor = continuation.partition(":")
        if prefix != binding[:16] or not cursor:
            raise self.refusal("conflict", operation, operation_id)
        return cursor

    async def write(self, operation: str, request: _Model) -> Receipt:
        payload = request.model_dump(mode="json")
        change_id = payload.pop("change_id", None)
        request_digest = _digest(payload)
        identity = change_id or request_digest[:32]
        operation_id = f"{operation}-{identity}"
        known = self.receipts.get(operation_id)
        if known is not None:
            if known.provenance.request_digest != request_digest:
                raise self.refusal("conflict", operation, operation_id)
            return known
        body = await self.invoke(
            operation, {**payload, "operation_id": operation_id}, operation_id
        )
        try:
            receipt = Receipt(
                provenance=Provenance(
                    repository_id=str(payload["repository_id"]),
                    revision=str(body["revision"]),
                    operation_id=operation_id,
                    request_digest=request_digest,
                    receipt_ref=str(body.get("receipt_ref") or "") or None,
                ),
                revision=str(body["revision"]),
                outcomes=tuple(PathOutcome(**o) for o in body.get("outcomes", ())),
            )
        except (KeyError, TypeError, ValidationError):
            raise self.refusal(
                "transport_unavailable", operation, operation_id
            ) from None
        self.receipts[operation_id] = receipt
        return receipt

    async def invoke(
        self, operation: str, payload: Mapping[str, Any], operation_id: str
    ) -> Mapping[str, Any]:
        try:
            reply = await asyncio.wait_for(
                self._transport.call(operation, payload), self._deadline
            )
        except TimeoutError:
            raise self.refusal("deadline_exceeded", operation, operation_id) from None
        except Exception:
            raise self.refusal(
                "transport_unavailable", operation, operation_id
            ) from None
        if not isinstance(reply, Mapping):
            raise self.refusal("transport_unavailable", operation, operation_id)
        if reply.get("status") == "refused":
            reason = reply.get("reason")
            if reason not in REFUSAL_REASONS:
                reason = "transport_unavailable"
            raise self.refusal(str(reason), operation, operation_id)
        result = reply.get("result")
        if reply.get("status") != "ok" or not isinstance(result, Mapping):
            raise self.refusal("transport_unavailable", operation, operation_id)
        return result

    @staticmethod
    def refusal(reason: str, operation: str, operation_id: str) -> SourceRefusedError:
        return SourceRefusedError(
            SourceRefusal(
                reason=reason,  # type: ignore[arg-type]
                operation=operation,
                operation_id=operation_id,
            )
        )
