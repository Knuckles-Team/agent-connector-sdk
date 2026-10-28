"""Model-level evidence; served fallback is separately required."""

import hashlib

import pytest
from pydantic import ValidationError

from agent_connector_sdk.adapters.platform_models import (
    BackendAttempt,
    BackendPolicy,
    BackendState,
    ChannelStatus,
    Continuation,
    EquivalenceContract,
    PlatformCapability,
    PlatformRecord,
    PlatformRequest,
    PlatformResult,
    Provenance,
    SkippedBackend,
    validate_request_binding,
)

pytestmark = pytest.mark.spec("SDK-SOURCE-INGEST-R012.7")
DIGEST = "sha256:" + "0" * 64


def _policy(backend_id: str = "first") -> BackendPolicy:
    return BackendPolicy(
        backend_id=backend_id,
        adapter_id="vendor",
        adapter_version="1",
        enabled=True,
        auth_mode="credential",
        credential_ref="env://PLATFORM_FIXTURE_CREDENTIAL",
        allowed_destinations=("api.example",),
        equivalence_contract=EquivalenceContract(
            platform_id="p",
            resource_visibility="private",
            account_scope="account",
            query_semantics="v1",
            output_schema_digest=DIGEST,
        ),
        quota_group="one",
        retry_policy="retry:v1",
        output_schema_digest=DIGEST,
    )


def _capability(operation: str = "search") -> PlatformCapability:
    return PlatformCapability.model_validate(
        {
            "platform_id": "p",
            "channel_id": "c",
            "operation": operation,
            "schema_revision": "1",
            "policy_revision": "2",
            "required_scope": "read",
            "backends": (_policy(), _policy("second")),
        }
    )


def _request() -> PlatformRequest:
    return PlatformRequest(
        request_id="r",
        tenant_id="t",
        principal_id="p",
        connector_id="c",
        platform_id="p",
        channel_id="c",
        operation="search",
        query="hello",
        continuation=Continuation(
            token="cursor",  # sanitizer:ignore - synthetic continuation fixture
            tenant_id="t",
            query_digest="sha256:" + hashlib.sha256(b"hello").hexdigest(),
            backend_id="first",
            policy_revision="2",
            output_schema_digest=DIGEST,
        ),
    )


def test_inventory_is_closed_bounded_and_equivalent() -> None:
    capability = _capability()
    assert capability.operation == "search"
    assert _capability("read").operation == "read"
    data = capability.model_dump()
    data["unknown"] = True
    with pytest.raises(ValidationError):
        PlatformCapability.model_validate(data)
    data.pop("unknown")
    data["backends"] = (data["backends"][0], data["backends"][0])
    with pytest.raises(ValidationError, match="duplicate"):
        PlatformCapability.model_validate(data)
    data["backends"] = (
        data["backends"][0],
        {
            **data["backends"][1],
            "backend_id": "other",
            "equivalence_contract": {
                **data["backends"][1]["equivalence_contract"],
                "account_scope": "other",
            },
        },
    )
    with pytest.raises(ValidationError, match="equivalence"):
        PlatformCapability.model_validate(data)
    with pytest.raises(ValidationError):
        BackendPolicy.model_validate({**_policy().model_dump(), "max_attempts": 3})
    with pytest.raises(ValidationError, match="private resources"):
        BackendPolicy.model_validate(
            {**_policy().model_dump(), "auth_mode": "public", "credential_ref": None}
        )


def test_request_and_continuation_bindings_are_checked() -> None:
    request = _request()
    validate_request_binding(request, _capability())
    with pytest.raises(ValidationError):
        PlatformRequest.model_validate({**request.model_dump(), "limit": 101})
    with pytest.raises(ValidationError):
        PlatformRequest.model_validate({**request.model_dump(), "target": "unexpected"})
    for field, value in (
        ("backend_id", "other"),
        ("policy_revision", "old"),
        ("output_schema_digest", "sha256:" + "1" * 64),
        ("query_digest", DIGEST),
    ):
        cursor = request.continuation.model_copy(update={field: value})
        with pytest.raises(ValueError, match="continuation"):
            validate_request_binding(
                request.model_copy(update={"continuation": cursor}), _capability()
            )
    with pytest.raises(ValidationError, match="tenant"):
        PlatformRequest.model_validate({**request.model_dump(), "tenant_id": "other"})
    with pytest.raises(ValidationError, match="tenant"):
        validate_request_binding(
            request.model_copy(update={"tenant_id": "other"}), _capability()
        )


def test_success_and_refusal_are_distinct_and_attempts_are_ordered() -> None:
    attempt = BackendAttempt(
        sequence=1,
        backend_id="first",
        attempt_number=1,
        outcome="ok",
        started_at=1,
        elapsed_ms=1,
    )
    result = PlatformResult(
        request_id="r",
        request_digest=DIGEST,
        outcome="ok",
        selected_backend="first",
        attempts=(attempt,),
    )
    assert result.records == ()
    refused = PlatformResult(
        request_id="r",
        request_digest=DIGEST,
        outcome="refused",
        reason="chain_exhausted",
    )
    assert refused.selected_backend is None
    with pytest.raises(ValidationError):
        PlatformResult.model_validate(
            {**refused.model_dump(), "selected_backend": "first"}
        )
    with pytest.raises(ValidationError):
        PlatformResult.model_validate({**result.model_dump(), "attempts": ()})


def test_status_and_record_are_scoped_and_bounded() -> None:
    state = BackendState(backend_id="first", health="healthy", observed_at=10)
    status = ChannelStatus(
        tenant_id="t",
        connector_id="c",
        account_scope="a",
        platform_id="p",
        channel_id="c",
        operation="search",
        policy_revision="2",
        selected_backend="first",
        health="healthy",
        backend_states=(state,),
        observed_at=10,
        expires_at=20,
    )
    provenance = Provenance(
        source_id="doc",
        backend_id="first",
        retrieved_at=10,
        content_digest=DIGEST,
        coverage="complete",
    )
    record = PlatformRecord(content={"text": "ok"}, provenance=provenance)
    skipped = SkippedBackend(backend_id="other", reason="disabled")
    attempt = BackendAttempt(
        sequence=1,
        backend_id="first",
        attempt_number=1,
        outcome="ok",
        started_at=10,
        elapsed_ms=1,
    )
    result = PlatformResult(
        request_id="r",
        request_digest=DIGEST,
        outcome="ok",
        selected_backend="first",
        attempts=(attempt,),
        records=(record,),
        skipped_backends=(skipped,),
        channel_status=status,
        provenance=provenance,
    )
    assert result.channel_status.tenant_id == "t"
    with pytest.raises(ValidationError):
        ChannelStatus.model_validate({**status.model_dump(), "expires_at": 9})


def test_backend_refuses_literal_credentials_without_echoing_them() -> None:
    literal = "fixture-private-credential-value"
    with pytest.raises(ValidationError) as failure:
        BackendPolicy.model_validate(
            {**_policy().model_dump(), "credential_ref": literal}
        )
    assert literal not in str(failure.value)


def test_private_inputs_and_record_content_are_not_in_repr() -> None:
    from agent_connector_sdk.adapters.platform_models import PlatformRecord, Provenance

    private_query = "sensitive-query-fixture"
    private_content = "sensitive-content-fixture"
    request = _request().model_copy(
        update={"query": private_query, "continuation": None}
    )
    record = PlatformRecord(
        content={"text": private_content},
        provenance=Provenance(
            source_id="fixture",
            backend_id="first",
            retrieved_at=1,
            content_digest=DIGEST,
            coverage="complete",
        ),
    )
    assert private_query not in repr(request)
    assert private_content not in repr(record)
