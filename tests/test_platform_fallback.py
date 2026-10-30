"""Bounded fallback preserves authority and reports observed backend failures."""

import hashlib
import json

import pytest
from pydantic import BaseModel, ConfigDict, field_validator

from agent_connector_sdk.adapters.platform_backend import (
    AdmittedPlatformBackend,
    BackendAdmissionRefusal,
    BackendFailure,
    BackendPage,
    PlatformAuthorizer,
    PlatformBackendAdmission,
    platform_record_schema_digest,
)
from agent_connector_sdk.adapters.platform_fallback import (
    PlatformFallback,
    PlatformStatusError,
)
from agent_connector_sdk.adapters.platform_models import (
    BackendAttempt,
    BackendPolicy,
    EquivalenceContract,
    PlatformCapability,
    PlatformRequest,
)
from agent_connector_sdk.adapters.platform_status import (
    DEFAULT_STATUS_ENTRIES,
    DEFAULT_STATUS_TTL_SECONDS,
    PlatformStatusStore,
)
from agent_connector_sdk.http.retry import RetryPolicy
from agent_connector_sdk.identity import ActorContext, ActorType


class FixtureRecord(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    id: str
    title: str = ""


class SlowRecord(BaseModel):
    id: str

    @field_validator("id")
    @classmethod
    def slow_validation(cls, value):
        import os
        import time
        from pathlib import Path

        marker = Path(os.environ["SCION_TEST_VALIDATOR_MARKER"])
        marker.with_suffix(".started").write_text("started")
        time.sleep(2)
        marker.write_text("finished")
        return value


DIGEST = platform_record_schema_digest(FixtureRecord)


def capability():
    equivalent = EquivalenceContract(
        platform_id="demo",
        resource_visibility="public",
        account_scope="shared",
        query_semantics="v1",
        output_schema_digest=DIGEST,
    )

    def policy(name):
        return BackendPolicy(
            backend_id=name,
            adapter_id=name,
            adapter_version="1",
            enabled=True,
            auth_mode="public",
            credential_ref=None,
            allowed_destinations=("example.org",),
            equivalence_contract=equivalent,
            quota_group="shared",
            max_attempts=1,
            retry_policy="v1",
            output_schema_digest=DIGEST,
        )

    return PlatformCapability(
        platform_id="demo",
        channel_id="items",
        operation="search",
        schema_revision="1",
        policy_revision="1",
        required_scope="search",
        backends=(policy("first"), policy("second")),
    )


def request():
    return PlatformRequest(
        request_id="request",
        tenant_id="tenant",
        principal_id="actor",
        connector_id="connector",
        platform_id="demo",
        channel_id="items",
        operation="search",
        query="private search",
    )


class Authority:
    def __init__(self, allow=True):
        self.allow = allow

    async def authorize(self, actor, request, capability):
        return self.allow

    async def verify_continuation(self, actor, request, capability):
        return False


class Backend:
    def __init__(self, result, calls, name, policy):
        self.result, self.calls, self.name, self.policy = result, calls, name, policy
        self.output_model = FixtureRecord

    async def read(self, request, *, timeout_ms):
        self.calls.append(self.name)
        if isinstance(self.result, BackendFailure):
            raise self.result
        return self.result


class Admission:
    def __init__(self, results):
        self.results, self.calls = results, []

    async def admit(self, actor, request, policy):
        return Backend(
            self.results[policy.backend_id], self.calls, policy.backend_id, policy
        )


def actor(authenticated=True):
    return ActorContext(
        actor_id="actor",
        actor_type=ActorType.HUMAN,
        tenant_id="tenant",
        authenticated=authenticated,
    )


@pytest.mark.spec("SCION-SOURCE-INGEST-R012.2")
@pytest.mark.asyncio
async def test_fallback_returns_empty_success_and_reports_attempts():
    admission = Admission(
        {
            "first": BackendFailure("upstream_unavailable"),
            "second": BackendPage(records=()),
        }
    )
    authority: PlatformAuthorizer = Authority()
    admitted: PlatformBackendAdmission = admission
    backend: AdmittedPlatformBackend = await admitted.admit(
        actor(), request(), capability().backends[0]
    )
    assert backend.policy == capability().backends[0]
    client = PlatformFallback(
        (capability(),),
        connector_id="connector",
        authorizer=authority,
        admission=admitted,
        retry_policies={"v1": RetryPolicy(max_attempts=1)},
    )
    result = await client.execute(actor(), request())
    assert result.outcome == "ok" and result.selected_backend == "second"
    assert admission.calls == ["first", "second"]
    assert [attempt.reason for attempt in result.attempts] == [
        "upstream_unavailable",
        None,
    ]
    assert result.channel_status.health == "degraded"
    assert (result.tenant_id, result.principal_id, result.connector_id) == (
        "tenant",
        "actor",
        "connector",
    )
    assert (result.policy_revision, result.output_schema_digest) == ("1", DIGEST)
    assert "private search" not in repr(result)


@pytest.mark.spec("SCION-SOURCE-INGEST-R012.2")
@pytest.mark.spec("SCION-SOURCE-INGEST-R012.4")
@pytest.mark.asyncio
async def test_denied_and_terminal_failure_do_not_fallback():
    admission = Admission(
        {"first": BackendFailure("unauthorized"), "second": BackendPage(records=())}
    )
    denied = PlatformFallback(
        (capability(),),
        connector_id="connector",
        authorizer=Authority(False),
        admission=admission,
        retry_policies={"v1": RetryPolicy(max_attempts=1)},
    )
    assert (await denied.execute(actor(), request())).reason == "unauthorized"
    assert admission.calls == []
    allowed = PlatformFallback(
        (capability(),),
        connector_id="connector",
        authorizer=Authority(),
        admission=admission,
        retry_policies={"v1": RetryPolicy(max_attempts=1)},
    )
    assert (await allowed.execute(actor(), request())).reason == "unauthorized"
    assert admission.calls == ["first"]


@pytest.mark.spec("SCION-SOURCE-INGEST-R012.2")
@pytest.mark.spec("SCION-SOURCE-INGEST-R012.4")
@pytest.mark.asyncio
async def test_governed_http_backends_fallback_and_stop_on_denial():
    from agent_connector_sdk.adapters.platform_http import PlatformHttpBackend
    from agent_connector_sdk.http.options import HttpClientOptions
    from agent_connector_sdk.testing.http_server import (
        ScriptedHttpServer,
        ScriptedResponse,
    )

    with (
        ScriptedHttpServer(
            ScriptedResponse(status=503), ScriptedResponse(status=403)
        ) as first,
        ScriptedHttpServer(ScriptedResponse(body=b'{"records":[]}')) as second,
    ):
        base = capability()
        policies = tuple(
            p.model_copy(update={"allowed_destinations": ("127.0.0.1",)})
            for p in base.backends
        )
        cap = base.model_copy(update={"backends": policies})
        backends = {
            policy.backend_id: PlatformHttpBackend(
                policy,
                HttpClientOptions(
                    base_url=server.base_url,
                    retry=RetryPolicy(max_attempts=1),
                    pin_egress=True,
                    allow_loopback=True,
                ),
                "/search",
                output_model=FixtureRecord,
            )
            for policy, server in zip(policies, (first, second), strict=True)
        }

        class HttpAdmission:
            async def admit(self, actor, request, policy):
                return backends[policy.backend_id]

        client = PlatformFallback(
            (cap,),
            connector_id="connector",
            authorizer=Authority(),
            admission=HttpAdmission(),
            retry_policies={"v1": RetryPolicy(max_attempts=1)},
        )
        ok = await client.execute(actor(), request())
        assert ok.outcome == "ok" and ok.selected_backend == "second"
        assert len(first.requests) == len(second.requests) == 1
        denied = await client.execute(actor(), request())
        assert denied.reason == "unauthorized"
        assert len(first.requests) == 2 and len(second.requests) == 1


@pytest.mark.spec("SCION-SOURCE-INGEST-R012.4")
@pytest.mark.asyncio
async def test_platform_refusal_never_becomes_an_accepted_empty_page():
    from test_event_feeds import CONNECTOR, FakeEventSession, _tool_descriptor

    from agent_connector_sdk.adapters.mcp_tool import McpToolSourceAdapter
    from agent_connector_sdk.adapters.platform_fallback import _refused
    from agent_connector_sdk.manifest.presets import ToolPreset
    from agent_connector_sdk.ports.errors import SourceContractError
    from agent_connector_sdk.runner.syncing import SyncTarget, sync_stream
    from agent_connector_sdk.testing.sinks import InMemorySink

    preset = ToolPreset(
        name="stream",
        server="demo",
        tool="platform_search",
        records_path="records",
        result_contract="platform",
        params_style="args",
        arguments={"request": request().model_dump(mode="json")},
        id_field="id",
        pagination="none",
    )
    adapter = McpToolSourceAdapter(
        preset,
        connector=CONNECTOR,
        mapping_reference=f"connector:{CONNECTOR}#mappings/Event",
    )
    refusal = _refused(
        request(), "chain_exhausted", capability=capability()
    ).model_dump(mode="json")
    session = FakeEventSession(
        descriptor=_tool_descriptor(preset.tool), pages=[refusal]
    )
    sink = InMemorySink()
    with pytest.raises(SourceContractError, match="chain_exhausted"):
        await sync_stream(session, adapter, SyncTarget(CONNECTOR, sink, max_pages=1))
    assert not sink.batches


@pytest.mark.spec("SCION-SOURCE-INGEST-R012.2")
@pytest.mark.spec("SCION-SOURCE-INGEST-R012.4")
@pytest.mark.asyncio
async def test_deadline_preserves_started_attempt_without_retry(monkeypatch):
    import anyio
    import anyio.to_process

    async def verify_without_worker_startup(fn, *args, **kwargs):
        return fn(*args)

    monkeypatch.setattr(anyio.to_process, "run_sync", verify_without_worker_startup)

    class SlowBackend:
        def __init__(self, policy):
            self.policy = policy
            self.output_model = FixtureRecord

        async def read(self, request, *, timeout_ms):
            await anyio.sleep(5)
            return BackendPage(records=())

    class SlowAdmission:
        async def admit(self, actor, request, policy):
            return SlowBackend(policy)

    client = PlatformFallback(
        (capability(),),
        connector_id="connector",
        authorizer=Authority(),
        admission=SlowAdmission(),
        retry_policies={"v1": RetryPolicy(max_attempts=1)},
    )
    result = await client.execute(
        actor(), request().model_copy(update={"deadline_ms": 2000})
    )
    assert result.reason == "deadline_exceeded"
    assert len(result.attempts) == 1 and result.attempts[0].reason == "timeout"


@pytest.mark.spec("SCION-SOURCE-INGEST-R012.5")
@pytest.mark.asyncio
async def test_backend_exception_is_typed_and_does_not_expose_message():
    class BrokenBackend:
        def __init__(self, policy):
            self.policy = policy
            self.output_model = FixtureRecord

        async def read(self, request, *, timeout_ms):
            raise RuntimeError("private-upstream-detail")

    class BrokenAdmission:
        async def admit(self, actor, request, policy):
            return BrokenBackend(policy)

    client = PlatformFallback(
        (capability(),),
        connector_id="connector",
        authorizer=Authority(),
        admission=BrokenAdmission(),
        retry_policies={"v1": RetryPolicy(max_attempts=1)},
    )
    result = await client.execute(actor(), request())
    assert result.reason == "invalid_response"
    assert len(result.attempts) == 1
    assert "private-upstream-detail" not in repr(result)


@pytest.mark.spec("SCION-SOURCE-INGEST-R012.5")
@pytest.mark.asyncio
async def test_status_is_isolated_from_other_principal():
    admission = Admission(
        {"first": BackendPage(records=()), "second": BackendPage(records=())}
    )
    client = PlatformFallback(
        (capability(),),
        connector_id="connector",
        authorizer=Authority(),
        admission=admission,
        retry_policies={"v1": RetryPolicy(max_attempts=1)},
    )
    assert (await client.execute(actor(), request())).outcome == "ok"
    other_actor = ActorContext(
        actor_id="other",
        actor_type=ActorType.HUMAN,
        tenant_id="tenant",
        authenticated=True,
    )
    other_request = request().model_copy(update={"principal_id": "other"})
    assert (await client.status(other_actor, other_request)).health == "unknown"
    other_tenant = ActorContext(
        actor_id="other",
        actor_type=ActorType.HUMAN,
        tenant_id="other-tenant",
        authenticated=True,
    )
    other_request = other_request.model_copy(update={"tenant_id": "other-tenant"})
    assert (await client.status(other_tenant, other_request)).health == "unknown"
    assert (await client.status(actor(), request())).health == "healthy"


@pytest.mark.asyncio
async def test_rate_limit_waits_then_retries_same_backend_without_fallback():
    from agent_connector_sdk.adapters.platform_http import PlatformHttpBackend
    from agent_connector_sdk.http.options import HttpClientOptions
    from agent_connector_sdk.testing.http_server import (
        ScriptedHttpServer,
        ScriptedResponse,
    )

    with (
        ScriptedHttpServer(
            ScriptedResponse(status=429, headers={"Retry-After": "0"}),
            ScriptedResponse(body=b'{"records":[]}'),
        ) as first,
        ScriptedHttpServer(ScriptedResponse(body=b'{"records":[]}')) as second,
    ):
        base = capability()
        first_policy = base.backends[0].model_copy(
            update={"allowed_destinations": ("127.0.0.1",), "max_attempts": 2}
        )
        second_policy = base.backends[1].model_copy(
            update={"allowed_destinations": ("127.0.0.1",)}
        )
        cap = base.model_copy(update={"backends": (first_policy, second_policy)})
        backends = {
            policy.backend_id: PlatformHttpBackend(
                policy,
                HttpClientOptions(
                    base_url=server.base_url,
                    retry=RetryPolicy(max_attempts=1),
                    pin_egress=True,
                    allow_loopback=True,
                ),
                "/search",
                output_model=FixtureRecord,
            )
            for policy, server in zip(cap.backends, (first, second), strict=True)
        }

        class AdmissionForHttp:
            async def admit(self, actor, request, policy):
                return backends[policy.backend_id]

        client = PlatformFallback(
            (cap,),
            connector_id="connector",
            authorizer=Authority(),
            admission=AdmissionForHttp(),
            retry_policies={"v1": RetryPolicy(max_attempts=2)},
        )
        result = await client.execute(actor(), request())
        assert result.outcome == "ok" and result.selected_backend == "first"
        assert [entry.reason for entry in result.attempts] == ["rate_limited", None]
        assert len(first.requests) == 2 and not second.requests


@pytest.mark.spec("SCION-SOURCE-INGEST-R012.5")
@pytest.mark.asyncio
async def test_status_expires_without_reusing_stale_backend_health(monkeypatch):
    from types import SimpleNamespace

    from agent_connector_sdk.adapters import platform_status

    now = [1000]
    monkeypatch.setattr(
        platform_status,
        "time",
        SimpleNamespace(time=lambda: now[0], monotonic=lambda: now[0]),
    )
    admission = Admission(
        {"first": BackendPage(records=()), "second": BackendPage(records=())}
    )
    client = PlatformFallback(
        (capability(),),
        connector_id="connector",
        authorizer=Authority(),
        admission=admission,
        retry_policies={"v1": RetryPolicy(max_attempts=1)},
    )
    assert (await client.execute(actor(), request())).channel_status.health == "healthy"
    now[0] += 61
    expired = await client.status(actor(), request())
    assert expired.health == "unknown" and expired.selected_backend is None
    assert expired.backend_states[0].health == "untested"
    assert expired.observed_at == 1000
    assert admission.calls == ["first"]


@pytest.mark.asyncio
async def test_unavailable_status_authority_has_no_upstream_exception():
    class BrokenAuthority(Authority):
        async def authorize(self, actor, request, capability):
            raise RuntimeError("private-authority-detail")

    admission = Admission(
        {"first": BackendPage(records=()), "second": BackendPage(records=())}
    )
    client = PlatformFallback(
        (capability(),),
        connector_id="connector",
        authorizer=BrokenAuthority(),
        admission=admission,
        retry_policies={"v1": RetryPolicy(max_attempts=1)},
    )
    with pytest.raises(PlatformStatusError) as failure:
        await client.status(actor(), request())
    assert failure.value.__context__ is None
    assert "private-authority-detail" not in str(failure.value)
    assert admission.calls == []


def test_status_store_bounds_and_unknown_observations():
    store = PlatformStatusStore()
    cap = capability()
    failure = BackendAttempt(
        sequence=1,
        backend_id="first",
        attempt_number=1,
        outcome="failed",
        reason="connection_failed",
        started_at=1,
        elapsed_ms=1,
    )
    for index in range(DEFAULT_STATUS_ENTRIES + 1):
        req = request().model_copy(update={"principal_id": f"actor-{index}"})
        status = store.record(req, cap, (failure,), None)
        assert status.expires_at - status.observed_at == DEFAULT_STATUS_TTL_SECONDS
    oldest = request().model_copy(update={"principal_id": "actor-0"})
    assert store.get(oldest, cap).health == "unknown"


@pytest.mark.asyncio
async def test_governed_http_refuses_oversized_response_without_fallback():
    from agent_connector_sdk.adapters.platform_http import (
        MAX_PLATFORM_RESPONSE_BYTES,
        PlatformHttpBackend,
    )
    from agent_connector_sdk.http.options import HttpClientOptions
    from agent_connector_sdk.testing.http_server import (
        ScriptedHttpServer,
        ScriptedResponse,
    )

    with ScriptedHttpServer(
        ScriptedResponse(body=b"x" * (MAX_PLATFORM_RESPONSE_BYTES + 1))
    ) as first:
        base = capability()
        first_policy = base.backends[0].model_copy(
            update={"allowed_destinations": ("127.0.0.1",)}
        )
        cap = base.model_copy(update={"backends": (first_policy, base.backends[1])})
        backend = PlatformHttpBackend(
            first_policy,
            HttpClientOptions(
                base_url=first.base_url,
                retry=RetryPolicy(max_attempts=1),
                pin_egress=True,
                allow_loopback=True,
            ),
            "/search",
            output_model=FixtureRecord,
        )

        class OneAdmission:
            async def admit(self, actor, request, policy):
                return backend if policy.backend_id == "first" else None

        client = PlatformFallback(
            (cap,),
            connector_id="connector",
            authorizer=Authority(),
            admission=OneAdmission(),
            retry_policies={"v1": RetryPolicy(max_attempts=1)},
        )
        result = await client.execute(actor(), request())
        assert result.reason == "invalid_response"
        assert len(result.attempts) == 1 and len(first.requests) == 1


@pytest.mark.spec("SCION-SOURCE-INGEST-R012.3")
@pytest.mark.asyncio
async def test_served_fallback_result_reaches_source_sync_sink(monkeypatch, tmp_path):
    import hashlib
    import json

    from agent_connector_sdk.adapters.mcp_tool import McpToolSourceAdapter
    from agent_connector_sdk.adapters.platform_http import PlatformHttpBackend
    from agent_connector_sdk.http.options import HttpClientOptions
    from agent_connector_sdk.identity import use_actor
    from agent_connector_sdk.manifest.presets import ToolPreset
    from agent_connector_sdk.mcp.server import create_mcp_server
    from agent_connector_sdk.ports.session import TransportEndpoint
    from agent_connector_sdk.runner.syncing import SyncTarget, sync_stream
    from agent_connector_sdk.testing.http_server import (
        ScriptedHttpServer,
        ScriptedResponse,
    )
    from agent_connector_sdk.testing.sinks import InMemorySink
    from agent_connector_sdk.transports.mcp import McpTransport

    content = {"id": "item-1", "title": "Synthetic item"}
    raw = json.dumps(
        content, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode()
    payload = {
        "records": [
            {
                "content": content,
                "provenance": {
                    "source_id": "fixture",
                    "backend_id": "second",
                    "retrieved_at": 1,
                    "content_digest": "sha256:" + hashlib.sha256(raw).hexdigest(),
                    "coverage": "complete",
                },
            }
        ]
    }
    payload["continuation"] = {
        "token": "fixture-cursor",
        "tenant_id": "tenant",
        "query_digest": "sha256:"
        + hashlib.sha256(request().query.encode()).hexdigest(),
        "backend_id": "second",
        "policy_revision": "1",
        "output_schema_digest": DIGEST,
    }
    next_content = {"id": "item-2", "title": "Second synthetic item"}
    next_raw = json.dumps(
        next_content, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode()
    next_payload = {
        "records": [
            {
                "content": next_content,
                "provenance": {
                    "source_id": "fixture",
                    "backend_id": "second",
                    "retrieved_at": 1,
                    "content_digest": "sha256:" + hashlib.sha256(next_raw).hexdigest(),
                    "coverage": "complete",
                },
            }
        ]
    }
    with (
        ScriptedHttpServer(ScriptedResponse(status=503)) as first,
        ScriptedHttpServer(
            ScriptedResponse(body=json.dumps(payload).encode()),
            ScriptedResponse(body=json.dumps(next_payload).encode()),
        ) as second,
    ):
        base = capability()
        policies = tuple(
            p.model_copy(update={"allowed_destinations": ("127.0.0.1",)})
            for p in base.backends
        )
        cap = base.model_copy(update={"backends": policies})
        backends = {
            policy.backend_id: PlatformHttpBackend(
                policy,
                HttpClientOptions(
                    base_url=server.base_url,
                    retry=RetryPolicy(max_attempts=1),
                    pin_egress=True,
                    allow_loopback=True,
                ),
                "/search",
                output_model=FixtureRecord,
            )
            for policy, server in zip(policies, (first, second), strict=True)
        }

        class FixtureAuthority(Authority):
            async def verify_continuation(self, actor, request, capability):
                return request.continuation.token == "fixture-cursor"

        fallback = PlatformFallback(
            (cap,),
            connector_id="connector",
            authorizer=FixtureAuthority(),
            admission=certified_http_admission(monkeypatch, tmp_path, backends),
            retry_policies={"v1": RetryPolicy(max_attempts=1)},
        )
        _, server, _ = create_mcp_server(
            "demo", version="1.0.0", command_args=[], platform_fallback=fallback
        )
        preset = ToolPreset(
            name="items",
            server="demo",
            tool="platform_search",
            params_style="args",
            arguments={"request": request().model_dump(mode="json")},
            records_path="records",
            result_contract="platform",
            id_field="content.id",
            pagination="cursor",
            cursor_param="request.continuation",
            cursor_path="continuation",
        )
        adapter = McpToolSourceAdapter(
            preset, connector="demo", mapping_reference="connector:demo#mappings/Item"
        )
        sink = InMemorySink()
        with use_actor(actor()):
            async with McpTransport().session(
                TransportEndpoint(in_process=server)
            ) as session:
                await sync_stream(
                    session, adapter, SyncTarget("demo", sink, max_pages=2)
                )
        assert len(first.requests) == 1 and len(second.requests) == 2
        records = [
            record for batch in sink.batches.values() for record in batch.records
        ]
        assert [record.record_id for record in records] == ["item-1", "item-2"]
        assert all(
            record.payload["provenance"]["backend_id"] == "second" for record in records
        )


@pytest.mark.asyncio
async def test_unverified_continuation_refuses_before_backend():
    import hashlib

    from agent_connector_sdk.adapters.platform_models import Continuation

    req = request()
    cursor = Continuation(
        token="-".join(("fixture", "cursor")),
        tenant_id="tenant",
        query_digest="sha256:" + hashlib.sha256(req.query.encode()).hexdigest(),
        backend_id="first",
        policy_revision="1",
        output_schema_digest=DIGEST,
    )
    admission = Admission(
        {"first": BackendPage(records=()), "second": BackendPage(records=())}
    )
    client = PlatformFallback(
        (capability(),),
        connector_id="connector",
        authorizer=Authority(),
        admission=admission,
        retry_policies={"v1": RetryPolicy(max_attempts=1)},
    )
    result = await client.execute(
        actor(), req.model_copy(update={"continuation": cursor})
    )
    assert result.reason == "invalid_request" and not admission.calls
    assert (
        await client.status(actor(), req.model_copy(update={"continuation": cursor}))
        is None
    )
    assert not admission.calls


def test_nested_page_arguments_preserve_static_request_without_mutation():
    from agent_connector_sdk.adapters.mcp_tool_paging import tool_arguments
    from agent_connector_sdk.manifest.presets import ToolPreset

    preset = ToolPreset(
        name="demo",
        server="demo",
        tool="search",
        params_style="args",
        result_contract="platform",
        arguments={"request": {"query": "term", "limit": 3}},
    )
    output = tool_arguments(preset, {"request": {"continuation": {"token": "next"}}})
    assert output == {
        "request": {"query": "term", "limit": 3, "continuation": {"token": "next"}}
    }
    assert preset.arguments == {"request": {"query": "term", "limit": 3}}
    generic = preset.model_copy(update={"result_contract": "generic"})
    assert tool_arguments(generic, {"request": {"limit": 2}}) == {
        "request": {"limit": 2}
    }


@pytest.mark.asyncio
async def test_unconfigured_backend_is_skipped_and_reported_without_attempt():
    calls = []

    class AdmissionWithGap:
        async def admit(self, actor, request, policy):
            if policy.backend_id == "first":
                return BackendAdmissionRefusal("unconfigured")
            return Backend(BackendPage(records=()), calls, policy.backend_id, policy)

    client = PlatformFallback(
        (capability(),),
        connector_id="connector",
        authorizer=Authority(),
        admission=AdmissionWithGap(),
        retry_policies={"v1": RetryPolicy(max_attempts=1)},
    )
    result = await client.execute(actor(), request())
    assert result.outcome == "ok" and calls == ["second"]
    assert len(result.attempts) == 1
    assert result.skipped_backends[0].reason == "unconfigured"
    assert result.channel_status.backend_states[0].health == "unconfigured"


@pytest.mark.asyncio
async def test_certified_admission_loads_only_pinned_authorized_entrypoint(monkeypatch):
    from types import SimpleNamespace

    from agent_connector_sdk import discovery
    from agent_connector_sdk.adapters.platform_admission import (
        CertifiedPlatformAdmission,
        PlatformBackendFactory,
    )
    from agent_connector_sdk.discovery import (
        PLATFORM_BACKEND_GROUP,
        CertifiedExtensions,
    )

    calls = []
    loaded = []

    class Factory:
        async def open(self, actor, request, policy):
            return Backend(BackendPage(records=()), calls, policy.backend_id, policy)

    factory: PlatformBackendFactory = Factory()

    class Entry:
        name = "first"
        value = "fixture:factory"
        dist = SimpleNamespace(metadata={"Name": "fixture-distribution"}, version="1")

        def load(self):
            loaded.append(True)
            return factory

    entry = Entry()
    monkeypatch.setattr(
        discovery,
        "entry_points",
        lambda group, name=None: (
            [entry]
            if group == PLATFORM_BACKEND_GROUP and (name is None or name == entry.name)
            else []
        ),
    )
    certified = CertifiedExtensions(
        [(PLATFORM_BACKEND_GROUP, "first", "fixture-distribution", "1")]
    )
    admission = CertifiedPlatformAdmission(certified)
    selected = await admission.admit(actor(), request(), capability().backends[0])
    assert selected.policy == capability().backends[0]
    assert loaded == [True]
    loaded.clear()
    mismatch = capability().backends[0].model_copy(update={"adapter_version": "2"})
    rejected = await admission.admit(actor(), request(), mismatch)
    assert rejected.reason == "uncertified" and loaded == []
    denied = CertifiedPlatformAdmission(CertifiedExtensions([]))
    rejected = await denied.admit(actor(), request(), capability().backends[0])
    assert rejected.reason == "uncertified" and loaded == []


def certified_http_admission(monkeypatch, tmp_path, backends):
    """Install fixture distribution metadata and use real SDK discovery."""
    import sys
    from types import ModuleType

    from agent_connector_sdk.adapters.platform_admission import (
        CertifiedPlatformAdmission,
    )
    from agent_connector_sdk.discovery import (
        PLATFORM_BACKEND_GROUP,
        CertifiedExtensions,
    )

    class Factory:
        def __init__(self, backend):
            self.backend = backend

        async def open(self, actor, request, policy):
            return self.backend

    module_name = "synthetic_platform_provider"
    module = ModuleType(module_name)
    metadata = tmp_path / "fixture_distribution-1.dist-info"
    metadata.mkdir()
    (metadata / "METADATA").write_text(
        "Metadata-Version: 2.1\nName: fixture-distribution\nVersion: 1\n",
        encoding="utf-8",
    )
    declarations = [f"[{PLATFORM_BACKEND_GROUP}]"]
    for name, backend in backends.items():
        setattr(module, name, Factory(backend))
        declarations.append(f"{name} = {module_name}:{name}")
    (metadata / "entry_points.txt").write_text(
        "\n".join(declarations) + "\n", encoding="utf-8"
    )
    monkeypatch.syspath_prepend(str(tmp_path))
    monkeypatch.setitem(sys.modules, module_name, module)
    certified = CertifiedExtensions(
        (PLATFORM_BACKEND_GROUP, name, "fixture-distribution", "1") for name in backends
    )
    return CertifiedPlatformAdmission(certified)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "status, reason",
    [
        (401, "unauthorized"),
        (403, "unauthorized"),
        (404, "not_found"),
        (429, "rate_limited"),
        (400, "invalid_response"),
    ],
)
async def test_http_refusal_cannot_be_downgraded_to_retryable(status, reason):
    admission = Admission(
        {
            "first": BackendFailure("connection_failed", http_status=status),
            "second": BackendPage(records=()),
        }
    )
    client = PlatformFallback(
        (capability(),),
        connector_id="connector",
        authorizer=Authority(),
        admission=admission,
        retry_policies={"v1": RetryPolicy(max_attempts=1)},
    )
    result = await client.execute(actor(), request())
    assert result.reason == reason
    assert admission.calls == ["first"]


@pytest.mark.asyncio
async def test_verified_scope_authorizer_requires_matching_token_scope_and_tenant(
    monkeypatch,
):
    from types import SimpleNamespace

    from fastmcp.server import dependencies

    from agent_connector_sdk.mcp.platform_tools import VerifiedScopeAuthorizer

    token = SimpleNamespace(
        client_id="actor",
        claims={"sub": "actor", "tenant_id": "tenant"},
        scopes=["search"],
    )
    monkeypatch.setattr(dependencies, "get_access_token", lambda: token)

    class RecordingAuthority(Authority):
        calls = 0

        async def verify_continuation(self, actor, request, capability):
            self.calls += 1
            return True

    delegate = RecordingAuthority()
    authorizer = VerifiedScopeAuthorizer(delegate)
    assert await authorizer.authorize(actor(), request(), capability())
    token.scopes = []
    assert not await authorizer.authorize(actor(), request(), capability())
    assert not await authorizer.verify_continuation(actor(), request(), capability())
    assert delegate.calls == 0
    token.scopes = ["search"]
    assert await authorizer.verify_continuation(actor(), request(), capability())
    assert delegate.calls == 1
    token.claims["tenant"] = "different"
    assert not await authorizer.authorize(actor(), request(), capability())
    token.claims = {"sub": "other", "tenant_id": "tenant"}
    assert not await authorizer.authorize(actor(), request(), capability())


def test_platform_result_rejects_partial_or_mismatched_scope():
    from pydantic import ValidationError

    from agent_connector_sdk.adapters.platform_models import PlatformResult

    data = {
        "request_id": "request",
        "request_digest": DIGEST,
        "outcome": "refused",
        "reason": "unauthorized",
    }
    with pytest.raises(ValidationError, match="scope"):
        PlatformResult.model_validate({**data, "tenant_id": "tenant"})
    with pytest.raises(ValidationError, match="policy"):
        PlatformResult.model_validate({**data, "policy_revision": "1"})


@pytest.mark.spec("SCION-SOURCE-INGEST-R012.3")
def test_platform_registration_refuses_collisions_before_adding_any_tools():
    from fastmcp import FastMCP

    from agent_connector_sdk.mcp.platform_tools import register_platform_tools
    from agent_connector_sdk.mcp.tool_surface import registered_tools

    server = FastMCP("demo")

    @server.tool(name="platform_search")
    def existing() -> str:
        return "existing"

    admission = Admission(
        {"first": BackendPage(records=()), "second": BackendPage(records=())}
    )
    fallback = PlatformFallback(
        (capability(),),
        connector_id="connector",
        authorizer=Authority(),
        admission=admission,
        retry_policies={"v1": RetryPolicy(max_attempts=1)},
    )
    with pytest.raises(ValueError, match="already registered"):
        register_platform_tools(server, fallback)
    assert set(registered_tools(server)) == {"platform_search"}


@pytest.mark.asyncio
async def test_http_backend_snapshots_headers_before_caller_mutation():
    from agent_connector_sdk.adapters.platform_http import PlatformHttpBackend
    from agent_connector_sdk.http.options import HttpClientOptions
    from agent_connector_sdk.testing.http_server import (
        ScriptedHttpServer,
        ScriptedResponse,
    )

    headers = {"X-Client": "initial"}
    with ScriptedHttpServer(ScriptedResponse(body=b'{"records":[]}')) as upstream:
        policy = (
            capability()
            .backends[0]
            .model_copy(update={"allowed_destinations": ("127.0.0.1",)})
        )
        options = HttpClientOptions(
            base_url=upstream.base_url,
            headers=headers,
            retry=RetryPolicy(max_attempts=1),
            pin_egress=True,
            allow_loopback=True,
        )
        backend = PlatformHttpBackend(
            policy, options, "/search", output_model=FixtureRecord
        )
        headers["X-Client"] = "changed"
        headers["Authorization"] = "private-fixture-value"
        assert (await backend.read(request(), timeout_ms=1000)).records == ()
        assert upstream.requests[0].headers["x-client"] == "initial"
        assert "authorization" not in upstream.requests[0].headers


@pytest.mark.asyncio
async def test_backend_schema_mismatch_refuses_before_provider_call():
    class OtherRecord(BaseModel):
        value: int

    class WrongSchemaAdmission:
        async def admit(self, actor, request, policy):
            backend = Backend(BackendPage(records=()), [], policy.backend_id, policy)
            backend.output_model = OtherRecord
            return backend

    client = PlatformFallback(
        (capability(),),
        connector_id="connector",
        authorizer=Authority(),
        admission=WrongSchemaAdmission(),
        retry_policies={"v1": RetryPolicy(max_attempts=1)},
    )
    result = await client.execute(actor(), request())
    assert result.reason == "trust_failed" and not result.attempts


@pytest.mark.asyncio
async def test_nonimportable_record_model_refuses_before_provider_call():
    class LocalRecord(BaseModel):
        id: str

    digest = platform_record_schema_digest(LocalRecord)
    base = capability()
    equivalent = base.backends[0].equivalence_contract.model_copy(
        update={"output_schema_digest": digest}
    )
    policies = tuple(
        policy.model_copy(
            update={"equivalence_contract": equivalent, "output_schema_digest": digest}
        )
        for policy in base.backends
    )
    cap = base.model_copy(update={"backends": policies})
    calls = []

    class LocalAdmission:
        async def admit(self, actor, request, policy):
            backend = Backend(BackendPage(records=()), calls, policy.backend_id, policy)
            backend.output_model = LocalRecord
            return backend

    client = PlatformFallback(
        (cap,),
        connector_id="connector",
        authorizer=Authority(),
        admission=LocalAdmission(),
        retry_policies={"v1": RetryPolicy(max_attempts=1)},
    )
    result = await client.execute(actor(), request())
    assert result.reason == "trust_failed"
    assert not calls and not result.attempts


@pytest.mark.asyncio
async def test_validation_worker_startup_uses_request_deadline(monkeypatch):
    import anyio
    import anyio.to_process

    async def slow_start(*args, **kwargs):
        await anyio.sleep_forever()

    monkeypatch.setattr(anyio.to_process, "run_sync", slow_start)
    admission = Admission(
        {"first": BackendPage(records=()), "second": BackendPage(records=())}
    )
    client = PlatformFallback(
        (capability(),),
        connector_id="connector",
        authorizer=Authority(),
        admission=admission,
        retry_policies={"v1": RetryPolicy(max_attempts=1)},
    )
    result = await client.execute(
        actor(), request().model_copy(update={"deadline_ms": 20})
    )
    assert result.reason == "deadline_exceeded"
    assert not result.attempts and not admission.calls


@pytest.mark.asyncio
async def test_invalid_record_schema_refuses_without_trying_another_backend():
    from agent_connector_sdk.adapters.platform_models import PlatformRecord, Provenance

    content = {"id": 9, "secret": "private-fixture"}
    digest = (
        "sha256:"
        + hashlib.sha256(
            json.dumps(
                content, sort_keys=True, separators=(",", ":"), ensure_ascii=False
            ).encode()
        ).hexdigest()
    )
    record = PlatformRecord(
        content=content,
        provenance=Provenance(
            source_id="fixture",
            backend_id="first",
            retrieved_at=1,
            content_digest=digest,
            coverage="complete",
        ),
    )
    admission = Admission(
        {"first": BackendPage(records=(record,)), "second": BackendPage(records=())}
    )
    client = PlatformFallback(
        (capability(),),
        connector_id="connector",
        authorizer=Authority(),
        admission=admission,
        retry_policies={"v1": RetryPolicy(max_attempts=1)},
    )
    result = await client.execute(actor(), request())
    assert result.reason == "invalid_response" and admission.calls == ["first"]
    assert "private-fixture" not in repr(result)


def test_platform_source_preset_refuses_missing_envelope_fields():
    from agent_connector_sdk.adapters.mcp_tool_records import raw_records
    from agent_connector_sdk.manifest.presets import ToolPreset
    from agent_connector_sdk.ports.errors import MalformedSourceDataError

    preset = ToolPreset.from_mapping(
        "items",
        {
            "server": "demo",
            "tool": "search",
            "records_path": "records",
            "result_contract": "platform",
        },
    )
    assert preset.result_contract == "platform"
    with pytest.raises(MalformedSourceDataError, match="platform result is malformed"):
        raw_records(preset, {"outcome": "ok", "records": []})


@pytest.mark.spec("SCION-SOURCE-INGEST-R012.4")
@pytest.mark.asyncio
async def test_exhausted_chain_and_unsupported_capability_are_distinct():
    admission = Admission(
        {
            "first": BackendFailure("connection_failed"),
            "second": BackendFailure("upstream_unavailable"),
        }
    )
    client = PlatformFallback(
        (capability(),),
        connector_id="connector",
        authorizer=Authority(),
        admission=admission,
        retry_policies={"v1": RetryPolicy(max_attempts=1)},
    )
    exhausted = await client.execute(actor(), request())
    assert exhausted.reason == "chain_exhausted"
    assert [entry.reason for entry in exhausted.attempts] == [
        "connection_failed",
        "upstream_unavailable",
    ]
    assert exhausted.channel_status.health == "unavailable"
    assert admission.calls == ["first", "second"]
    unsupported = await client.execute(
        actor(), request().model_copy(update={"platform_id": "unknown"})
    )
    assert unsupported.reason == "unsupported_capability"
    assert admission.calls == ["first", "second"]


@pytest.mark.spec("SCION-SOURCE-INGEST-R012.2")
@pytest.mark.spec("SCION-SOURCE-INGEST-R012.4")
@pytest.mark.asyncio
async def test_external_cancellation_stops_current_attempt_and_never_falls_back():
    import anyio

    calls = []
    finished = []
    started = anyio.Event()

    class CancelBackend:
        def __init__(self, policy):
            self.policy = policy
            self.output_model = FixtureRecord

        async def read(self, request, *, timeout_ms):
            calls.append(self.policy.backend_id)
            started.set()
            try:
                await anyio.sleep_forever()
            finally:
                finished.append(self.policy.backend_id)

    class CancelAdmission:
        async def admit(self, actor, request, policy):
            return CancelBackend(policy)

    client = PlatformFallback(
        (capability(),),
        connector_id="connector",
        authorizer=Authority(),
        admission=CancelAdmission(),
        retry_policies={"v1": RetryPolicy(max_attempts=1)},
    )
    async with anyio.create_task_group() as group:
        group.start_soon(client.execute, actor(), request())
        with anyio.fail_after(10):
            await started.wait()
        group.cancel_scope.cancel()
    assert calls == finished == ["first"]


@pytest.mark.asyncio
async def test_source_rejects_platform_result_for_a_different_request():
    from test_event_feeds import CONNECTOR, FakeEventSession, _tool_descriptor

    from agent_connector_sdk.adapters.mcp_tool import McpToolSourceAdapter
    from agent_connector_sdk.adapters.platform_fallback import _refused
    from agent_connector_sdk.manifest.presets import ToolPreset
    from agent_connector_sdk.ports.errors import SourceContractError
    from agent_connector_sdk.runner.syncing import SyncTarget, sync_stream
    from agent_connector_sdk.testing.sinks import InMemorySink

    preset = ToolPreset(
        name="stream",
        server="demo",
        tool="platform_search",
        records_path="records",
        result_contract="platform",
        params_style="args",
        arguments={"request": request().model_dump(mode="json")},
        id_field="id",
        pagination="none",
    )
    adapter = McpToolSourceAdapter(
        preset,
        connector=CONNECTOR,
        mapping_reference=f"connector:{CONNECTOR}#mappings/Event",
    )
    different = request().model_copy(update={"query": "another query"})
    response = _refused(
        different, "chain_exhausted", capability=capability()
    ).model_dump(mode="json")
    session = FakeEventSession(
        descriptor=_tool_descriptor(preset.tool), pages=[response]
    )
    sink = InMemorySink()
    with pytest.raises(SourceContractError, match="does not match the source request"):
        await sync_stream(session, adapter, SyncTarget(CONNECTOR, sink, max_pages=1))
    assert not sink.batches


@pytest.mark.asyncio
async def test_source_refuses_oversized_platform_envelope_before_submission():
    from test_event_feeds import CONNECTOR, FakeEventSession, _tool_descriptor

    from agent_connector_sdk.adapters.mcp_tool import McpToolSourceAdapter
    from agent_connector_sdk.adapters.platform_http import MAX_PLATFORM_RESPONSE_BYTES
    from agent_connector_sdk.manifest.presets import ToolPreset
    from agent_connector_sdk.ports.errors import SourceContractError
    from agent_connector_sdk.runner.syncing import SyncTarget, sync_stream
    from agent_connector_sdk.testing.sinks import InMemorySink

    preset = ToolPreset(
        name="stream",
        server="demo",
        tool="platform_search",
        records_path="records",
        result_contract="platform",
        params_style="args",
        arguments={"request": request().model_dump(mode="json")},
        id_field="id",
        pagination="none",
    )
    adapter = McpToolSourceAdapter(
        preset,
        connector=CONNECTOR,
        mapping_reference=f"connector:{CONNECTOR}#mappings/Event",
    )
    response = {"records": [{"content": "x" * (MAX_PLATFORM_RESPONSE_BYTES + 100_000)}]}
    session = FakeEventSession(
        descriptor=_tool_descriptor(preset.tool), pages=[response]
    )
    sink = InMemorySink()
    with pytest.raises(SourceContractError, match="does not match the source request"):
        await sync_stream(session, adapter, SyncTarget(CONNECTOR, sink, max_pages=1))
    assert not sink.batches


def test_generic_source_response_is_not_reinterpreted_as_platform_envelope():
    from agent_connector_sdk.adapters.mcp_tool_records import raw_records
    from agent_connector_sdk.manifest.presets import ToolPreset

    preset = ToolPreset(
        name="items", server="demo", tool="search", records_path="records"
    )
    generic = {
        "request_id": "vendor-id",
        "request_digest": "vendor-digest",
        "outcome": "ok",
        "records": [{"id": "item"}],
    }
    assert raw_records(preset, generic) == [{"id": "item"}]


@pytest.mark.asyncio
async def test_record_validation_respects_backend_attempt_timeout(
    monkeypatch, tmp_path
):
    import anyio

    marker = tmp_path / "validator.finished"
    monkeypatch.setenv("SCION_TEST_VALIDATOR_MARKER", str(marker))
    from agent_connector_sdk.adapters.platform_models import PlatformRecord, Provenance

    digest = platform_record_schema_digest(SlowRecord)
    base = capability()
    equivalent = base.backends[0].equivalence_contract.model_copy(
        update={"output_schema_digest": digest}
    )
    policies = tuple(
        policy.model_copy(
            update={
                "equivalence_contract": equivalent,
                "output_schema_digest": digest,
                "timeout_ms": 1000,
            }
        )
        for policy in base.backends
    )
    cap = base.model_copy(update={"backends": policies})
    content = {"id": "fixture"}
    content_digest = (
        "sha256:"
        + hashlib.sha256(
            json.dumps(content, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
    )
    record = PlatformRecord(
        content=content,
        provenance=Provenance(
            source_id="fixture",
            backend_id="first",
            retrieved_at=1,
            content_digest=content_digest,
            coverage="complete",
        ),
    )
    calls = []

    class SlowAdmission:
        async def admit(self, actor, request, policy):
            result = (
                BackendPage(records=(record,))
                if policy.backend_id == "first"
                else BackendPage(records=())
            )
            backend = Backend(result, calls, policy.backend_id, policy)
            backend.output_model = SlowRecord
            return backend

    client = PlatformFallback(
        (cap,),
        connector_id="connector",
        authorizer=Authority(),
        admission=SlowAdmission(),
        retry_policies={"v1": RetryPolicy(max_attempts=1)},
    )
    result = await client.execute(actor(), request())
    assert result.outcome == "ok" and result.selected_backend == "second"
    assert [attempt.reason for attempt in result.attempts] == ["timeout", None]
    assert calls == ["first", "second"]
    assert marker.with_suffix(".started").exists()
    await anyio.sleep(2.1)
    assert not marker.exists()
