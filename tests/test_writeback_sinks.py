"""Write-back sinks: the fail-closed, dry-run-first, governed entry point."""

from __future__ import annotations

import ast
import asyncio
import json
from pathlib import Path

import pytest

from agent_connector_sdk.writeback.errors import (
    AuthorizationDeniedError,
    SourceVersionConflictError,
)
from agent_connector_sdk.writeback_sinks import core, run_writeback, spec_link
from agent_connector_sdk.writeback_sinks.governed import (
    PATCH_FIELD,
    SinkGrant,
    build_change_set,
    execute_governed,
)
from agent_connector_sdk.writeback_sinks.models import GraphNode
from agent_connector_sdk.writeback_sinks.sinks.capability import push_capabilities

DOMAIN = "governedfake"

pytestmark = [pytest.mark.spec("SDK-SOURCE-INGEST-R600")]


class FakeSink:
    domain = DOMAIN
    enable_flag = "GOVERNEDFAKE_ENABLE_WRITE"

    def __init__(
        self, *, fail: bool = False, failure: BaseException | None = None
    ) -> None:
        self.calls: list[bool] = []
        self.fail = fail
        self.failure = failure

    def run(self, ctx, ops, *, dry_run: bool) -> core.WritebackResult:
        self.calls.append(dry_run)
        if self.failure is not None and not dry_run:
            raise self.failure
        if self.fail and not dry_run:
            raise RuntimeError("sink exploded mid-batch")
        result = core.WritebackResult(target=self.domain)
        if dry_run:
            result.proposals.append({"op": "create", "items": ops.get("creations")})
        else:
            result.created = len(ops.get("creations") or [])
        return result


@pytest.fixture
def flag(monkeypatch):
    """Set the write enable flag for every sink."""

    def _set(enabled: bool) -> None:
        monkeypatch.setattr(core, "setting", lambda k, d=None, cast=None: enabled)

    return _set


@pytest.fixture
def ledger(monkeypatch, tmp_path) -> Path:
    root = tmp_path / "ledger"
    monkeypatch.setattr(
        "agent_connector_sdk.writeback_sinks.governed.ledger_root", lambda: root
    )
    return root


@pytest.fixture
def fake_sink():
    def _register(sink: FakeSink) -> FakeSink:
        core.register_sink(sink)
        return sink

    yield _register
    core._SINKS.pop(DOMAIN, None)


def grant(**overrides) -> SinkGrant:
    values = {
        "target": DOMAIN,
        "enable_flag": FakeSink.enable_flag,
        "write_enabled": True,
    }
    return SinkGrant(**{**values, **overrides})


def only_dir(root: Path) -> Path:
    (directory,) = [p for p in root.iterdir() if p.is_dir()]
    return directory


def test_change_set_is_canonical_and_drops_private_ops():
    ops = {"creations": [{"type": "CI", "name": "a"}], "_approved": True, "client": 1}
    change_set = build_change_set(grant(), ops)
    assert change_set.change_set_digest == change_set.canonical_digest()
    assert change_set.field_scope == [PATCH_FIELD]
    assert change_set.desired_patch == {
        PATCH_FIELD: {"creations": [{"name": "a", "type": "CI"}]}
    }
    assert change_set.base_source_version == "unversioned"


@pytest.mark.spec("SDK-SOURCE-INGEST-R600.1")
def test_writeback_contract_validates_ids_and_exposes_typed_invocation(fake_sink):
    sink = fake_sink(FakeSink())
    assert isinstance(sink, core.WritebackSink)
    assert core.get_sink(DOMAIN) is sink
    result = core.WritebackResult(target=DOMAIN)
    ctx = core.WritebackContext()
    invocation = core.WritebackInvocation(ctx, {"creations": []}, None, result, True)
    assert invocation.unpack() == (ctx, {"creations": []}, None, result, True)

    change_set = build_change_set(grant(), {"creations": []}, now_ms=0)
    assert all(
        getattr(change_set, field)
        for field in (
            "change_set_id",
            "connector_id",
            "entity_id",
            "idempotency_key",
            "required_capability",
            "source_instance_id",
            "tenant_id",
        )
    )
    with pytest.raises(ValueError, match="target"):
        SinkGrant(target=" ", enable_flag=FakeSink.enable_flag, write_enabled=True)
    with pytest.raises(ValueError, match="enable_flag"):
        SinkGrant(target=DOMAIN, enable_flag="", write_enabled=True)
    with pytest.raises(ValueError, match="target"):
        core.WritebackResult()

    class InvalidSink:
        domain = ""
        enable_flag = FakeSink.enable_flag

        def run(self, ctx, ops, *, dry_run):
            return core.WritebackResult(target=DOMAIN)

    with pytest.raises(ValueError, match=r"sink\.domain"):
        core.register_sink(InvalidSink())


@pytest.mark.spec("SDK-SOURCE-INGEST-R600.3")
def test_writeback_wiring_uses_preflight_and_approval_queue(fake_sink, flag):
    flag(True)
    sink = FakeSink()
    sink.risk_tier = "high_stakes"
    fake_sink(sink)
    events = []
    queued = []

    def preflight(target, received_sink, ops):
        events.append(("preflight", target))
        assert received_sink is sink
        assert ops["_enqueue_proposal"] is enqueue
        return None

    def enqueue(target, ops, proposals):
        events.append(("enqueue", target))
        queued.append((target, ops, proposals))
        return "proposal-1"

    out = run_writeback(
        DOMAIN,
        dry_run=False,
        creations=[{"name": "a"}],
        _preflight=preflight,
        _enqueue_proposal=enqueue,
    )
    assert out["status"] == "queued"
    assert out["proposal_id"] == "proposal-1"
    assert events == [("preflight", DOMAIN), ("enqueue", DOMAIN)]
    assert queued and queued[0][2] == [{"op": "create", "items": [{"name": "a"}]}]
    assert sink.calls == [True]


@pytest.mark.spec("SDK-SOURCE-INGEST-R600.3")
def test_writeback_package_has_no_harness_import_or_duplicate_entrypoint():
    package = Path(__file__).parents[1] / "agent_connector_sdk"
    imported_harness_modules = []
    duplicate_entrypoints = []
    for path in package.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                modules = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom):
                modules = [node.module or ""]
            else:
                continue
            imported_harness_modules.extend(
                module
                for module in modules
                if module == "agent_utilities" or module.startswith("agent_utilities.")
            )
        if path.name == "core.py" and path.parent.name == "writeback_sinks":
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and (
                (isinstance(node.func, ast.Name) and node.func.id == "run_writeback")
                or (
                    isinstance(node.func, ast.Attribute)
                    and node.func.attr == "run_writeback"
                )
            ):
                duplicate_entrypoints.append(str(path))
    assert imported_harness_modules == []
    assert duplicate_entrypoints == []


def test_dry_run_proposes_and_writes_no_ledger(fake_sink, ledger, flag):
    flag(False)
    sink = fake_sink(FakeSink())
    out = run_writeback(DOMAIN, dry_run=True, creations=[{"name": "a"}])
    assert out["status"] == "completed"
    assert sink.calls == [True]
    assert out["proposals"] == [{"op": "create", "items": [{"name": "a"}]}]
    assert out["governed_writeback"]["authorization_mode"] == "standing_policy"
    assert not ledger.exists()


@pytest.mark.spec("SDK-SOURCE-INGEST-R600.2")
def test_live_write_records_change_set_audit_and_receipt(fake_sink, ledger, flag):
    flag(True)
    sink = fake_sink(FakeSink())
    out = run_writeback(DOMAIN, dry_run=False, creations=[{"name": "a"}])
    assert (out["status"], out["created"], sink.calls) == ("completed", 1, [False])
    directory = only_dir(ledger)
    assert (directory / "audit_reservation.json").exists()
    receipts = json.loads((directory / "receipts.json").read_text())
    assert [r["receipt"]["effect_status"] for r in receipts] == ["applied"]


# spec: SDK-SOURCE-INGEST-R600.4
def test_live_write_refused_without_flag(fake_sink, ledger, flag):
    flag(False)
    sink = fake_sink(FakeSink())
    out = run_writeback(DOMAIN, dry_run=False, creations=[{"name": "a"}])
    assert out["status"] == "refused"
    assert sink.calls == [] and not ledger.exists()


@pytest.mark.spec("SDK-SOURCE-INGEST-R600.5")
def test_sink_failure_manifest_binds_uncertain_evidence_after_preflight(
    fake_sink, ledger, flag
):
    flag(True)
    sink = FakeSink(fail=True)
    fake_sink(sink)
    events = []

    def preflight(target, received_sink, ops):
        events.append((target, received_sink))
        assert ops["creations"] == [{"name": "a"}]
        return None

    out = run_writeback(
        DOMAIN,
        dry_run=False,
        creations=[{"name": "a"}],
        _preflight=preflight,
    )
    evidence = out["governed_writeback"]
    receipt = json.loads((only_dir(ledger) / "receipts.json").read_text())[0]["receipt"]
    assert out["status"] == "error" and "exploded" in out["error"]
    assert events == [(DOMAIN, sink)]
    assert sink.calls == [False]
    assert evidence == {
        "connector_id": f"agent-utilities.writeback.{DOMAIN}",
        "change_set_id": receipt["change_set_id"],
        "change_set_digest": receipt["change_set_digest"],
        "authorization_mode": "standing_policy",
        "effect_status": "outcome_uncertain",
    }
    assert receipt["idempotency_key"] == f"{DOMAIN}:{evidence['change_set_id']}"
    assert len(json.loads((only_dir(ledger) / "receipts.json").read_text())) == 1


@pytest.mark.parametrize(
    "failure",
    [TimeoutError("sink deadline"), asyncio.CancelledError("sink cancelled")],
    ids=["timeout", "cancel"],
)
@pytest.mark.spec("SDK-SOURCE-INGEST-R600.5")
def test_timeout_and_cancelled_sink_failures_remain_uncertain(
    fake_sink, ledger, flag, failure
):
    flag(True)
    sink = FakeSink(failure=failure)
    fake_sink(sink)
    out = run_writeback(DOMAIN, dry_run=False, creations=[{"name": "a"}])
    assert out["status"] == "error"
    assert out["error"] in {"sink deadline", "sink cancelled", "CancelledError"}
    assert out["governed_writeback"]["effect_status"] == "outcome_uncertain"
    assert sink.calls == [False]
    receipts = json.loads((only_dir(ledger) / "receipts.json").read_text())
    assert len(receipts) == 1
    assert receipts[0]["receipt"]["effect_status"] == "outcome_uncertain"


@pytest.mark.parametrize(
    ("overrides", "ops", "error"),
    [
        ({"write_enabled": False}, {"creations": []}, AuthorizationDeniedError),
        (
            {},
            {"expected_source_version": "v1", "current_source_version": "v2"},
            SourceVersionConflictError,
        ),
    ],
)
def test_governed_refusal_happens_before_the_sink(tmp_path, overrides, ops, error):
    sink = FakeSink()
    with pytest.raises(error):
        execute_governed(
            sink,
            core.WritebackContext(),
            ops,
            grant=grant(**overrides),
            dry_run=False,
            root=tmp_path,
        )
    assert sink.calls == []


def test_approved_replay_uses_proposal_approval_mode(tmp_path):
    outcome = execute_governed(
        FakeSink(),
        core.WritebackContext(),
        {"creations": [{"name": "a"}]},
        grant=grant(approved=True),
        dry_run=False,
        root=tmp_path,
    )
    assert outcome.evidence()["authorization_mode"] == "proposal_approval"
    assert outcome.result.created == 1


def test_unknown_target_errors():
    assert run_writeback("nope", dry_run=True)["status"] == "error"


def test_high_stakes_live_write_without_queue_is_refused(fake_sink, ledger, flag):
    flag(True)
    sink = FakeSink()
    sink.risk_tier = "high_stakes"
    fake_sink(sink)
    out = run_writeback(DOMAIN, dry_run=False, creations=[{"name": "a"}])
    assert out["status"] == "refused" and sink.calls == [True]


# --- vendor sinks -----------------------------------------------------------


class FakeLeanix:
    def __init__(self):
        self.relations, self.created = [], []

    def meta_model(self):
        return {
            "relation_map": {
                "relApplicationToITComponent": (
                    "REL_APPLICATION_TO_IT_COMPONENT",
                    "ITComponent",
                )
            }
        }

    def create_fact_sheet_relation(self, fs_id, rel_field, target_id):
        self.relations.append((fs_id, rel_field, target_id))
        return {"id": fs_id}

    def create_fact_sheet(self, fs_type, name):
        self.created.append((fs_type, name))
        return {"id": "new-1"}


class FakeBackend:
    def execute(self, query, params=None):
        return [
            {"id": "app:a1", "guid": "lx-a1"},
            {"id": "itcomponent:ic1", "guid": "lx-ic1"},
        ]


def rel(target="itcomponent:ic1"):
    return {
        "source": "app:a1",
        "rel_type": "REL_APPLICATION_TO_IT_COMPONENT",
        "target": target,
    }


def test_leanix_dry_run_proposes_then_live_writes(flag):
    client = FakeLeanix()
    kw = {"backend": FakeBackend(), "client": client, "inferences": [rel()]}
    dry = run_writeback("leanix", dry_run=True, **kw)
    assert dry["relations_written"] == 0 and client.relations == []
    assert dry["proposals"][0]["relation"] == "relApplicationToITComponent"
    assert dry["proposals"][0]["provenance"] == core.PROVENANCE_TAG
    flag(False)
    refused = run_writeback("leanix", dry_run=False, **kw)
    assert refused["status"] == "refused" and "LEANIX_ENABLE_WRITE" in refused["reason"]
    flag(True)
    live = run_writeback(
        "leanix",
        dry_run=False,
        creations=[{"type": "DataObject", "name": "Ledger"}],
        **kw,
    )
    assert (live["relations_written"], live["created"]) == (1, 1)
    assert client.relations == [("lx-a1", "relApplicationToITComponent", "lx-ic1")]


def test_leanix_unresolvable_relation_is_skipped_and_no_client_skips(flag):
    flag(True)
    out = run_writeback(
        "leanix",
        backend=FakeBackend(),
        client=FakeLeanix(),
        inferences=[rel("app:unknown")],
        dry_run=False,
    )
    assert (out["skipped"], out["relations_written"]) == (1, 0)
    assert run_writeback("leanix", client=None, dry_run=True)["skipped"] == 1


class FakeCiso:
    def __init__(self):
        self.created = []

    def api_policies_create(self, body=None):
        self.created.append(("policy", body or {}))
        return type("R", (), {"data": {"id": "p1"}})()

    def api_applied_controls_create(self, body=None):
        self.created.append(("control", body or {}))
        return type("R", (), {"data": {"id": "c1"}})()


def test_ciso_dry_run_flag_and_live(flag):
    client = FakeCiso()
    items = [{"type": "Policy", "name": "P"}, {"type": "Control", "name": "C"}]
    dry = run_writeback("ciso_assistant", client=client, creations=items, dry_run=True)
    assert dry["created"] == 0 and client.created == []
    assert dry["proposals"][0]["op"] == "create_policy"
    flag(False)
    refused = run_writeback(
        "ciso_assistant", client=client, creations=items, dry_run=False
    )
    assert "CISO_ASSISTANT_ENABLE_WRITE" in refused["reason"]
    flag(True)
    live = run_writeback(
        "ciso_assistant", client=client, folder="root", creations=items, dry_run=False
    )
    assert live["created"] == 2
    assert [k for k, _ in client.created] == ["policy", "control"]
    assert all(p["folder"] == "root" for _, p in client.created)
    # a folder is required by the target system: creations without it are skipped
    client.created.clear()
    bare = run_writeback(
        "ciso_assistant", client=client, creations=items[:1], dry_run=False
    )
    assert bare["created"] == 0 and bare["skipped"] >= 1 and client.created == []


class FakeArchi:
    def __init__(self):
        self.added = []

    def add_element(self, type, name="", documentation="", properties=None):
        self.added.append((type, name))
        return f"id-{name}"


class FakeCapabilityLeanix:
    def __init__(self):
        self.created = []

    def postbusinesscapability(self, payload):
        self.created.append(payload["name"])


def derived(name="Billing", **props):
    return GraphNode(
        id=f"capability:derived:{name.lower()}",
        type="BusinessCapability",
        props={"name": name, "derived_from": "code", "provisional": True, **props},
    )


def test_capability_push_to_both_targets_and_dry_run():
    archi, leanix = FakeArchi(), FakeCapabilityLeanix()
    result = push_capabilities([derived()], archi_client=archi, leanix_client=leanix)
    assert result.created == 2
    assert archi.added == [("Capability", "Billing")] and leanix.created == ["Billing"]
    dry = push_capabilities([derived("X")], archi_client=archi, dry_run=True)
    assert dry.created == 0 and dry.proposals[0]["op"] == "create_capability"


@pytest.mark.parametrize(
    ("node", "existing", "attr"),
    [
        (
            GraphNode(
                id="capability:HR", type="BusinessCapability", props={"name": "HR"}
            ),
            [],
            "created",
        ),
        (derived(), ["billing"], "skipped"),
    ],
)
def test_capability_push_skips_upstream_and_existing(node, existing, attr):
    archi = FakeArchi()
    result = push_capabilities([node], archi_client=archi, existing_names=existing)
    assert result.created == 0 and archi.added == []
    if attr == "skipped":
        assert result.skipped == 1


def test_capability_failing_client_does_not_abort():
    class Boom:
        def add_element(self, **_):
            raise RuntimeError("down")

    leanix = FakeCapabilityLeanix()
    result = push_capabilities(
        [derived("X")], archi_client=Boom(), leanix_client=leanix
    )
    assert (result.errors, result.created) == (1, 1)


SPEC = {"feature_id": "feat-auth-v2", "title": "Auth v2", "user_stories": []}


class FakePlane:
    def __init__(self):
        self.updated, self.links, self.comments = [], [], []

    def update_work_item(self, project_id, item_id, data):
        self.updated.append(data)

    def create_work_item_link(self, project_id, item_id, data):
        self.links.append(data)

    def create_work_item_comment(self, project_id, item_id, data):
        self.comments.append(data)

    def list_work_items(self, project_id):
        rows = [
            {"id": "w1", "name": "SSO", "assignees": ["u-alice"], "state": "todo"},
            {"id": "w2", "name": "Other", "assignees": ["u-bob"]},
        ]
        return type("R", (), {"data": {"results": rows}})()


def test_spec_link_dry_run_live_refusal_and_pull(monkeypatch):
    spec = dict(SPEC)
    dry = spec_link.link_spec(
        spec, target="plane", issue_id="w1", project_id="p", dry_run=True
    )
    assert {"update_item", "link_spec"} <= {a["op"] for a in dry["proposals"]}
    assert spec["external_links"]["plane"] == "w1"
    monkeypatch.setattr(spec_link, "setting", lambda k, d=None, cast=None: False)
    assert (
        spec_link.link_spec(SPEC, target="plane", issue_id="w1", dry_run=False)[
            "status"
        ]
        == "refused"
    )
    values = {"AGENT_USER_MAP": '{"a2a:planner": {"plane": "u-bot"}}'}
    monkeypatch.setattr(
        spec_link,
        "setting",
        lambda k, d=None, cast=None: (
            True if "ENABLE_WRITE" in k else values.get(k, d or "")
        ),
    )
    client = FakePlane()
    live = spec_link.link_spec(
        SPEC,
        target="plane",
        issue_id="w1",
        project_id="p",
        agent="a2a:planner",
        comment="linked",
        client=client,
        dry_run=False,
    )
    assert live["assignee"] == "u-bot" and client.links and client.comments
    pulled = spec_link.pull_assigned(
        "plane", user="u-alice", project_id="p", client=FakePlane()
    )
    assert [i["id"] for i in pulled["items"]] == ["w1"]


# --- the sink registry: every vendor sink is registered under its domain ---

from agent_connector_sdk.writeback_sinks import (  # noqa: E402
    WritebackSink,
    get_sink,
    list_sinks,
)
from agent_connector_sdk.writeback_sinks.sinks import (  # noqa: E402
    ansible,
    archimate,
    capability,
    ciso_assistant,
    egeria,
    emerald,
    erpnext,
    home_assistant,
    identity,
    issue_tracker,
    leanix,
    legal,
    mealie,
    nextcloud,
    ops,
    process,
    salesforce,
    servicenow,
    twenty,
    wger,
)

VENDOR_SINKS = (
    ansible.AnsibleSink,
    archimate.ArchimateSink,
    capability.CapabilitySink,
    ciso_assistant.CisoAssistantSink,
    egeria.EgeriaSink,
    emerald.EmeraldSink,
    erpnext.ErpNextSink,
    home_assistant.HomeAssistantSink,
    identity.OktaSink,
    identity.KeycloakSink,
    issue_tracker.GitLabIssueSink,
    issue_tracker.GitHubIssueSink,
    issue_tracker.PlaneIssueSink,
    issue_tracker.JiraIssueSink,
    issue_tracker.JiraTransitionSink,
    issue_tracker.PlaneStateSink,
    leanix.LeanixSink,
    legal.LegalSink,
    mealie.MealieSink,
    nextcloud.NextcloudSink,
    ops.TechnitiumSink,
    ops.CaddySink,
    ops.UptimeKumaSink,
    ops.KafkaSink,
    ops.PortainerSink,
    ops.LgtmSink,
    process.ProcessSink,
    salesforce.SalesforceSink,
    servicenow.ServiceNowSink,
    twenty.TwentySink,
    wger.WgerSink,
)


@pytest.mark.parametrize("sink_class", VENDOR_SINKS, ids=lambda c: c.__name__)
def test_every_vendor_sink_is_registered_under_its_domain(sink_class):
    assert sink_class.domain and sink_class.domain == sink_class.domain.lower()
    assert sink_class.enable_flag and sink_class.enable_flag.isupper()
    registered = get_sink(f"  {sink_class.domain.upper()} ")
    assert type(registered) is sink_class
    assert isinstance(registered, WritebackSink)
    assert sink_class.domain in list_sinks()


def test_registry_domains_are_unique_per_sink():
    domains = [sink_class.domain for sink_class in VENDOR_SINKS]
    assert len(domains) == len(set(domains))
    assert get_sink("no-such-target") is None
