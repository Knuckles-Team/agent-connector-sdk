"""Synthetic D18 source for a tenant-scoped served write-back proof."""

from __future__ import annotations

import secrets
from pathlib import Path
from typing import Any, Literal

from epistemic_graph.generated.write_back import (
    ReconciliationObservation,
    SourceChangeSet,
    WriteBackAttempt,
    WriteBackAuthorizationMode,
    WriteBackEffectStatus,
    WriteBackReceipt,
    WriteBackReceiptRecordAttempt,
)
from fastmcp import FastMCP
from fastmcp.server.dependencies import get_access_token
from pydantic import BaseModel, ConfigDict, Field, JsonValue

from agent_connector_sdk.credentials.resolver import CredentialResolver
from agent_connector_sdk.mcp.network import (
    NetworkServingConfig,
    build_network_serving_config,
)
from agent_connector_sdk.mcp.server import create_mcp_server
from agent_connector_sdk.ports.session import TransportEndpoint
from agent_connector_sdk.ports.writeback_ledger import WriteBackLedger
from agent_connector_sdk.transports.mcp import McpTransport
from agent_connector_sdk.writeback.connector import DurableWritableConnector
from agent_connector_sdk.writeback.durable_transport import FileWriteBackTransport
from agent_connector_sdk.writeback.epistemic_graph import EpistemicGraphWriteBackLedger
from agent_connector_sdk.writeback.errors import WriteBackPersistenceError
from agent_connector_sdk.writeback.models import DryRunObservation

__all__ = [
    "LiveSyntheticWriteBackEvidence",
    "SyntheticWriteBackResult",
    "build_synthetic_writeback_eg_server",
    "build_synthetic_writeback_server",
    "build_synthetic_writeback_test_namespace_server",
    "run_live_synthetic_writeback_acceptance",
    "seed_synthetic_writeback_test_source",
    "serve_synthetic_writeback_test_namespace",
    "verify_synthetic_writeback_source_effect",
]

CONNECTOR_ID = "synthetic-writeback"
SOURCE_INSTANCE_ID = "synthetic-source"
CAPABILITY = "ticket.write"


class SyntheticWriteBackResult(BaseModel):
    """Source observation and EG receipt identity returned by the synthetic tool."""

    model_config = ConfigDict(extra="forbid")

    action: Literal["dry_run", "apply", "reconcile"]
    observation: dict[str, JsonValue]
    receipt_id: str | None
    server_instance_id: str = Field(min_length=1)


class LiveSyntheticWriteBackEvidence(BaseModel):
    """Serializable boundary evidence carried across a server restart."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    tenant_id: str
    change_set_id: str
    change_set_digest: str
    receipt_id: str
    receipt_sequence: int
    post_source_version: str
    server_instance_id: str = Field(min_length=1)


async def _latest_receipt_id(
    ledger: WriteBackLedger, tenant_id: str, change_set_id: str
) -> str:
    after_sequence: int | None = None
    receipt_id = ""
    while True:
        page = await ledger.receipts(
            tenant_id, change_set_id, after_sequence=after_sequence, limit=256
        )
        if page.receipts:
            receipt_id = page.receipts[-1].receipt.receipt_id
        if page.next_sequence is None:
            break
        if after_sequence is not None and page.next_sequence <= after_sequence:
            raise WriteBackPersistenceError("EG receipt pagination did not advance")
        after_sequence = page.next_sequence
    if not receipt_id:
        raise WriteBackPersistenceError("EG did not persist a write-back receipt")
    return receipt_id


def _require_synthetic_caller(required_client_id: str | None) -> None:
    if required_client_id is None:
        return
    access = get_access_token()
    if access is None or access.client_id != required_client_id:
        raise WriteBackPersistenceError("synthetic caller is not granted")
    if "writeback:synthetic" not in access.scopes:
        raise WriteBackPersistenceError("synthetic caller lacks write-back scope")


def _register_synthetic_writeback(
    mcp: FastMCP[Any],
    ledger: WriteBackLedger,
    source_dir: Path,
    *,
    tenant_id: str,
    required_client_id: str | None = None,
) -> FastMCP[Any]:
    if not tenant_id or not tenant_id.strip():
        raise ValueError("tenant_id must not be empty")
    expected_tenant = tenant_id
    server_instance_id = secrets.token_hex(16)
    transport = FileWriteBackTransport(source_dir)
    connector = DurableWritableConnector(CONNECTOR_ID, transport, ledger)

    @mcp.tool()
    async def synthetic_writeback(
        action: Literal["dry_run", "apply", "reconcile"],
        tenant_id: str,
        change_set_id: str,
    ) -> SyntheticWriteBackResult:
        """Preview, apply or reconcile a pre-authorized synthetic ticket change."""
        _require_synthetic_caller(required_client_id)
        if tenant_id != expected_tenant:
            raise WriteBackPersistenceError("synthetic tenant is not granted")
        change_set = await ledger.get(tenant_id, change_set_id)
        if change_set is None:
            raise WriteBackPersistenceError("EG change set does not exist")
        if (
            change_set.connector_id != CONNECTOR_ID
            or change_set.source_instance_id != SOURCE_INSTANCE_ID
            or change_set.required_capability != CAPABILITY
            or change_set.field_scope != ["status"]
        ):
            raise WriteBackPersistenceError("synthetic source scope mismatch")
        observation: DryRunObservation | WriteBackAttempt | ReconciliationObservation
        if action == "dry_run":
            observation = await connector.dry_run(change_set)
            receipt_id = None
        elif action == "apply":
            observation = await connector.apply(change_set)
            receipt_id = await _latest_receipt_id(ledger, tenant_id, change_set_id)
        else:
            observation = await connector.reconcile(change_set)
            receipt_id = await _latest_receipt_id(ledger, tenant_id, change_set_id)
        return SyntheticWriteBackResult(
            action=action,
            observation=observation.model_dump(mode="json"),
            receipt_id=receipt_id,
            server_instance_id=server_instance_id,
        )

    return mcp


def build_synthetic_writeback_server(
    ledger: WriteBackLedger, source_dir: Path, *, tenant_id: str
) -> FastMCP[Any]:
    """Serve an in-process fixture for one test tenant.

    The caller seeds ``FileWriteBackTransport`` with a synthetic ticket. The
    tool never creates an approval or accepts a caller-supplied change set.
    Use the test-namespace builder for a network listener.
    """
    return _register_synthetic_writeback(
        FastMCP(CONNECTOR_ID, version="1.0.0"),
        ledger,
        source_dir,
        tenant_id=tenant_id,
    )


def build_synthetic_writeback_eg_server(
    eg_client: Any,
    source_dir: Path,
    *,
    graph: str,
    tenant_id: str,
) -> FastMCP[Any]:
    """Bind the test source to EG's generated durable WriteBack operations.

    ``eg_client`` must already carry a tenant-granted verified context. EG
    authorizes every create, read and receipt append; the SDK never mints a
    principal or stores a credential in this fixture.
    """
    if not graph or not graph.strip():
        raise ValueError("graph must not be empty")
    return build_synthetic_writeback_server(
        EpistemicGraphWriteBackLedger(eg_client, graph=graph),
        source_dir,
        tenant_id=tenant_id,
    )


def build_synthetic_writeback_test_namespace_server(
    eg_client: Any,
    source_dir: Path,
    *,
    graph: str,
    tenant_id: str,
    client_id: str,
    command_args: list[str],
    credential_resolver: CredentialResolver | None = None,
) -> tuple[FastMCP[Any], NetworkServingConfig]:
    """Compose an authenticated test-namespace listener with EG authority.

    The caller supplies the tenant-granted EG client and credential references.
    The network listener requires the standard SDK exposure policy, an auth
    provider, one exact client identity, and ``writeback:synthetic`` scope.
    """
    if not all(value and value.strip() for value in (graph, tenant_id, client_id)):
        raise ValueError("graph, tenant_id and client_id are required")
    args, mcp, _ = create_mcp_server(
        CONNECTOR_ID,
        version="1.0.0",
        command_args=command_args,
        credential_resolver=credential_resolver,
    )
    if args.transport != "streamable-http" or args.auth_type == "none":
        raise ValueError("test namespace requires authenticated streamable HTTP")
    config = build_network_serving_config(args)
    if config is None:
        raise ValueError("test namespace needs a network serving boundary")
    server = _register_synthetic_writeback(
        mcp,
        EpistemicGraphWriteBackLedger(eg_client, graph=graph),
        source_dir,
        tenant_id=tenant_id,
        required_client_id=client_id,
    )
    return server, config


async def serve_synthetic_writeback_test_namespace(
    eg_client: Any,
    source_dir: Path,
    *,
    graph: str,
    tenant_id: str,
    client_id: str,
    command_args: list[str],
    credential_resolver: CredentialResolver | None = None,
) -> None:
    """Run the authenticated listener with its validated address and policy."""
    server, config = build_synthetic_writeback_test_namespace_server(
        eg_client,
        source_dir,
        graph=graph,
        tenant_id=tenant_id,
        client_id=client_id,
        command_args=command_args,
        credential_resolver=credential_resolver,
    )
    await server.run_async(
        transport=config.transport,
        host=config.host,
        port=config.port,
        **config.fastmcp_run_kwargs(),
    )


def seed_synthetic_writeback_test_source(
    source_dir: Path,
    change: SourceChangeSet,
    *,
    initial_fields: dict[str, JsonValue],
) -> None:
    """Seed one fresh disposable source; refuse an existing state file."""
    if source_dir.is_symlink() or any(
        (source_dir / name).exists() for name in ("entities.json", "effects.json")
    ):
        raise WriteBackPersistenceError("synthetic test source already exists")
    _require_live_change(
        change,
        tenant_id=change.tenant_id,
        change_set_id=change.change_set_id,
        expected_mode=change.authorization.mode,
    )
    if set(initial_fields) != set(change.field_scope) or all(
        initial_fields[field] == change.desired_patch[field]
        for field in change.field_scope
    ):
        raise ValueError("synthetic source seed must contain a changed field")
    FileWriteBackTransport(source_dir).seed(
        change.entity_id, change.base_source_version, initial_fields
    )


async def verify_synthetic_writeback_source_effect(
    source_dir: Path,
    change: SourceChangeSet,
    evidence: LiveSyntheticWriteBackEvidence,
) -> None:
    """Read the durable source independently after the server restart."""
    if not (source_dir / "entities.json").is_file():
        raise WriteBackPersistenceError("synthetic source state is unavailable")
    _require_live_change(
        change,
        tenant_id=evidence.tenant_id,
        change_set_id=evidence.change_set_id,
        expected_mode=change.authorization.mode,
    )
    if evidence.change_set_digest != change.change_set_digest:
        raise WriteBackPersistenceError(
            "synthetic source evidence is for another change"
        )
    source = FileWriteBackTransport(source_dir)
    current = await source.read_current(change)
    effect = await source.prior_effect(change)
    if (
        effect is None
        or effect.effect_status is not WriteBackEffectStatus.APPLIED
        or effect.post_source_version != evidence.post_source_version
        or current.source_version != evidence.post_source_version
        or any(
            current.fields.get(field) != change.desired_patch[field]
            for field in change.field_scope
        )
    ):
        raise WriteBackPersistenceError("synthetic source effect does not bind receipt")


def _require_live_change(
    change: SourceChangeSet | None,
    *,
    tenant_id: str,
    change_set_id: str,
    expected_mode: WriteBackAuthorizationMode,
) -> SourceChangeSet:
    if change is None or (
        change.tenant_id != tenant_id
        or change.change_set_id != change_set_id
        or change.change_set_digest != change.canonical_digest()
        or change.connector_id != CONNECTOR_ID
        or change.source_instance_id != SOURCE_INSTANCE_ID
        or change.required_capability != CAPABILITY
        or change.field_scope != ["status"]
        or not change.authorization.authorized
        or change.authorization.mode is not expected_mode
    ):
        raise WriteBackPersistenceError("live synthetic change set is not granted")
    return change


async def _single_live_receipt(
    ledger: WriteBackLedger, change: SourceChangeSet
) -> WriteBackReceipt | None:
    page = await ledger.receipts(change.tenant_id, change.change_set_id, limit=2)
    if page.next_sequence is not None or len(page.receipts) > 1:
        raise WriteBackPersistenceError("live synthetic receipt is not unique")
    if not page.receipts:
        return None
    record = page.receipts[0]
    if not isinstance(record, WriteBackReceiptRecordAttempt):
        raise WriteBackPersistenceError("live synthetic receipt is not an attempt")
    receipt = record.receipt
    if (
        receipt.tenant_id != change.tenant_id
        or receipt.change_set_id != change.change_set_id
        or receipt.change_set_digest != change.change_set_digest
        or receipt.actor != change.actor
        or receipt.authorization != change.authorization
        or receipt.policy_digest != change.policy_digest
        or receipt.effect_status is not WriteBackEffectStatus.APPLIED
    ):
        raise WriteBackPersistenceError("live synthetic receipt binding mismatch")
    return receipt


def _require_live_acceptance_inputs(
    endpoint: TransportEndpoint, graph: str, tenant_id: str, change_set_id: str
) -> None:
    if not graph or not graph.strip() or not tenant_id or not tenant_id.strip():
        raise ValueError("graph and tenant_id are required")
    if not change_set_id or not change_set_id.strip():
        raise ValueError("change_set_id is required")
    if not endpoint.url or not (endpoint.bearer_token or endpoint.auth):
        raise ValueError("live acceptance requires an authenticated URL endpoint")


def _require_live_prior(
    prior: LiveSyntheticWriteBackEvidence | None,
    before: WriteBackReceipt | None,
    change: SourceChangeSet,
) -> None:
    if prior is None:
        if before is not None:
            raise WriteBackPersistenceError("live synthetic change was already applied")
        return
    if (
        prior.tenant_id != change.tenant_id
        or prior.change_set_id != change.change_set_id
        or prior.change_set_digest != change.change_set_digest
        or before is None
        or before.receipt_id != prior.receipt_id
        or before.sequence != prior.receipt_sequence
        or before.post_source_version != prior.post_source_version
    ):
        raise WriteBackPersistenceError("live synthetic restart evidence mismatch")


async def run_live_synthetic_writeback_acceptance(
    eg_client: Any,
    endpoint: TransportEndpoint,
    *,
    graph: str,
    tenant_id: str,
    change_set_id: str,
    expected_mode: WriteBackAuthorizationMode,
    prior: LiveSyntheticWriteBackEvidence | None = None,
    transport: McpTransport | None = None,
) -> LiveSyntheticWriteBackEvidence:
    """Probe a served SDK→EG approval/apply/receipt boundary.

    The caller injects an already verified tenant-granted EG client and an
    authenticated network endpoint. Run once, restart the served connector,
    then run again with the first result as ``prior``. This helper never seeds
    a source, creates a grant, mints an EG identity or restarts a deployment.
    """
    _require_live_acceptance_inputs(endpoint, graph, tenant_id, change_set_id)
    ledger = EpistemicGraphWriteBackLedger(eg_client, graph=graph)
    change = _require_live_change(
        await ledger.get(tenant_id, change_set_id),
        tenant_id=tenant_id,
        change_set_id=change_set_id,
        expected_mode=expected_mode,
    )
    before = await _single_live_receipt(ledger, change)
    _require_live_prior(prior, before, change)
    arguments = {"tenant_id": tenant_id, "change_set_id": change_set_id}
    preview_instance_id: str | None = None
    async with (transport or McpTransport()).session(endpoint) as session:
        identity = await session.server_identity()
        if identity.name != CONNECTOR_ID:
            raise WriteBackPersistenceError("live synthetic server identity mismatch")
        if prior is None:
            preview = SyntheticWriteBackResult.model_validate(
                await session.call_tool(
                    "synthetic_writeback", {"action": "dry_run", **arguments}
                )
            )
            preview_instance_id = preview.server_instance_id
            dry_run = DryRunObservation.model_validate(preview.observation)
            if (
                preview.action != "dry_run"
                or preview.receipt_id is not None
                or dry_run.change_set_digest != change.change_set_digest
                or dry_run.source_version != change.base_source_version
                or dry_run.desired_patch_digest != change.patch_digest()
                or dry_run.changed_fields != ("status",)
            ):
                raise WriteBackPersistenceError("live synthetic dry-run was not clean")
        applied = SyntheticWriteBackResult.model_validate(
            await session.call_tool(
                "synthetic_writeback", {"action": "apply", **arguments}
            )
        )
    attempt = WriteBackAttempt.model_validate(applied.observation)
    after = await _single_live_receipt(ledger, change)
    if (
        applied.action != "apply"
        or after is None
        or applied.receipt_id != after.receipt_id
        or attempt.effect_status is not WriteBackEffectStatus.APPLIED
        or any(
            getattr(after, field) != getattr(attempt, field)
            for field in type(attempt).model_fields
        )
    ):
        raise WriteBackPersistenceError("live synthetic apply/receipt mismatch")
    if (prior is None and applied.server_instance_id != preview_instance_id) or (
        prior is not None and applied.server_instance_id == prior.server_instance_id
    ):
        raise WriteBackPersistenceError(
            "live synthetic server instance did not advance"
        )
    evidence = LiveSyntheticWriteBackEvidence(
        tenant_id=tenant_id,
        change_set_id=change_set_id,
        change_set_digest=change.change_set_digest,
        receipt_id=after.receipt_id,
        receipt_sequence=after.sequence,
        post_source_version=after.post_source_version,
        server_instance_id=applied.server_instance_id,
    )
    if (
        prior is not None
        and evidence.model_copy(update={"server_instance_id": prior.server_instance_id})
        != prior
    ):
        raise WriteBackPersistenceError("live synthetic replay changed the effect")
    return evidence
