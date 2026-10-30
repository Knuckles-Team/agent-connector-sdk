"""Activate platform backend providers under the SDK extension policy."""

from __future__ import annotations

from typing import Protocol, cast

from scion_sdk.adapters.platform_backend import (
    AdmittedPlatformBackend,
    BackendAdmissionRefusal,
)
from scion_sdk.adapters.platform_models import BackendPolicy, PlatformRequest
from scion_sdk.discovery import (
    PLATFORM_BACKEND_GROUP,
    ActivationPolicy,
    ExtensionActivationError,
    load_extension,
)
from scion_sdk.identity import ActorContext


class PlatformBackendFactory(Protocol):
    """A certified provider constructs a backend without calling the source.

    Each source request belongs in the backend's one-attempt ``read`` method,
    so fallback can account for it under the shared deadline and retry budget.
    """

    async def open(
        self, actor: ActorContext, request: PlatformRequest, policy: BackendPolicy
    ) -> AdmittedPlatformBackend: ...


class CertifiedPlatformAdmission:
    """Load only the exact installed adapter version approved by the host."""

    def __init__(self, activation_policy: ActivationPolicy) -> None:
        self._policy = activation_policy

    async def admit(
        self, actor: ActorContext, request: PlatformRequest, policy: BackendPolicy
    ) -> AdmittedPlatformBackend | BackendAdmissionRefusal:
        try:
            loaded = load_extension(
                PLATFORM_BACKEND_GROUP,
                policy.adapter_id,
                policy=self._policy,
                expected_version=policy.adapter_version,
            )
        except LookupError:
            return BackendAdmissionRefusal("unconfigured")
        except ExtensionActivationError:
            return BackendAdmissionRefusal("uncertified")
        if not callable(getattr(loaded, "open", None)):
            return BackendAdmissionRefusal("ineligible")
        return await cast(PlatformBackendFactory, loaded).open(actor, request, policy)
