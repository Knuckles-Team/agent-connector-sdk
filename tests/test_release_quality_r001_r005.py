"""Tests for the R001 isolated-consumer plan and R005 import-graph reproducibility helpers.

SDK-QUALITY-RELEASE-R001 and -R005 (see specs/SDK-QUALITY-RELEASE/requirements.md).
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import sys
from pathlib import Path

import pytest

SCRIPTS_DIR = Path(__file__).resolve().parents[1] / "scripts"


def _load(module_name: str):
    if str(SCRIPTS_DIR) not in sys.path:
        sys.path.insert(0, str(SCRIPTS_DIR))
    module_path = SCRIPTS_DIR / f"{module_name}.py"
    spec = importlib.util.spec_from_file_location(
        f"{module_name}_under_test", module_path
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


_graph = _load("check_import_graph_reproducibility")
_wheel = sys.modules["epistemic_graph_wheel_provenance"]
_compat = _load("check_wheel_consumer_compatibility")

FIXTURE = _graph.FIXTURE
compute_import_graph_evidence = _graph.compute_import_graph_evidence
read_recorded_graph = _graph.read_recorded_graph
CompatibilityGateError = _compat.CompatibilityGateError
isolated_install_plan = _compat.isolated_install_plan
pinned_graph_client_requirement = _compat.pinned_graph_client_requirement


@pytest.mark.spec("SDK-QUALITY-RELEASE-R001")
def test_pinned_graph_client_requirement_reads_the_declared_dependency() -> None:
    requirement = pinned_graph_client_requirement()
    assert requirement.startswith("epistemic-graph")
    assert any(op in requirement for op in (">=", "==", "~="))


@pytest.mark.spec("SDK-QUALITY-RELEASE-R001")
def test_pinned_graph_client_requirement_fails_closed_without_a_dependency() -> None:
    with pytest.raises(CompatibilityGateError):
        pinned_graph_client_requirement('[project]\nname = "x"\ndependencies = []\n')


@pytest.mark.spec("SDK-QUALITY-RELEASE-R001")
def test_isolated_install_plan_never_installs_from_the_source_overlay() -> None:
    plan = isolated_install_plan(
        Path("dist/agent_connector_sdk-1.0.0-py3-none-any.whl"),
        "epistemic-graph>=2.27.0,<3",
        Path("dist-consumer-venv"),
    )
    flat = [" ".join(command) for command in plan]
    assert any(cmd.startswith("uv venv") for cmd in flat)
    install_commands = [cmd for cmd in flat if "pip install" in cmd]
    assert install_commands, "plan must install the built wheel into the isolated venv"
    for command in install_commands:
        assert "-e ." not in command
        assert "agent_connector_sdk-1.0.0-py3-none-any.whl" in command
        assert "epistemic-graph>=2.27.0,<3" in command
        assert "--python dist-consumer-venv" in command


@pytest.mark.spec("SDK-QUALITY-RELEASE-R001")
def test_isolated_install_plan_rejects_a_non_wheel_path() -> None:
    with pytest.raises(CompatibilityGateError):
        isolated_install_plan(
            Path("dist/not-a-wheel.tar.gz"), "epistemic-graph>=2.27.0,<3", Path("venv")
        )


@pytest.mark.spec("SDK-QUALITY-RELEASE-R005")
def test_local_pinned_install_reproduces_hosted_import_graph() -> None:
    """The exact import graph computed under this pinned environment must
    equal the recorded graph committed from an equivalently pinned
    source-only resolve, proving local verification never drifts
    from the hosted release check without a visible, reviewable diff."""
    assert FIXTURE.exists(), "tests/fixtures/pinned_import_graph.txt must be committed"
    recorded = read_recorded_graph()
    evidence = compute_import_graph_evidence()
    live = list(evidence.graph)
    assert live == recorded, (
        "local import graph drifted from the recorded hosted result; "
        "re-run PYTHONPATH=.ci/epistemic-graph uv run --frozen --no-sync "
        "python scripts/check_import_graph_reproducibility.py --record"
    )


@pytest.mark.spec("SDK-QUALITY-RELEASE-R005")
def test_source_git_probe_ignores_sdk_hook_repository_context(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sdk_git_dir = _graph._git(_graph.ROOT, "rev-parse", "--absolute-git-dir")
    monkeypatch.setenv("GIT_DIR", sdk_git_dir)
    monkeypatch.setenv("GIT_WORK_TREE", str(_graph.ROOT))

    assert _graph._git(_graph.SOURCE_ROOT, "rev-parse", "HEAD") == (
        "a5b4a1f1f638baed374897578cc061f473e9687b"
    )
    assert (
        _graph._normalize_remote(
            _graph._git(_graph.SOURCE_ROOT, "remote", "get-url", "origin")
        )
        == _graph.SOURCE_REMOTE
    )


@pytest.mark.spec("SDK-QUALITY-RELEASE-R005")
def test_recorded_import_graph_is_sorted_and_deduplicated() -> None:
    recorded = read_recorded_graph()
    assert recorded == sorted(set(recorded))
    assert all("==" in entry for entry in recorded)


@pytest.mark.spec("SDK-QUALITY-RELEASE-R005")
def test_source_declaration_proves_dynamic_version_and_locked_dependencies() -> None:
    case = _source_declaration_case()
    locked = _graph._prove_source_declaration(**case)
    assert locked == (
        "httpx==0.28.1",
        "msgpack==1.2.1",
        "pydantic==2.13.5",
        "pyoxigraph==0.3.22",
    )


@pytest.mark.spec("SDK-QUALITY-RELEASE-R005")
@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("git_revision", "0" * 40, "checkout is"),
        ("source_version", "2.28.0", "source version"),
        ("import_origin", Path("/tmp/unpinned/epistemic_graph/__init__.py"), "origin"),
        ("git_remote", "https://example.invalid/epistemic-graph.git", "remote"),
    ],
)
def test_source_declaration_rejects_wrong_commit_origin_version_or_remote(
    field: str, value: object, message: str
) -> None:
    case = _source_declaration_case()
    case[field] = value
    with pytest.raises(_graph.ImportGraphError, match=message):
        _graph._prove_source_declaration(**case)


@pytest.mark.spec("SDK-QUALITY-RELEASE-R005")
def test_source_declaration_rejects_a_missing_locked_runtime_dependency() -> None:
    case = _source_declaration_case()
    case["lock_packages"] = [
        package for package in case["lock_packages"] if package["name"] != "pyoxigraph"
    ]
    with pytest.raises(_graph.ImportGraphError, match=r"absent from uv\.lock"):
        _graph._prove_source_declaration(**case)


@pytest.mark.spec("SDK-QUALITY-RELEASE-R005")
def test_source_declaration_rejects_a_missing_package_edge() -> None:
    case = _source_declaration_case()
    package = case["lock_package"]
    case["lock_package"] = _graph.LockedPackage(
        package.version,
        package.source,
        tuple(
            edge for edge in package.dependencies if edge.get("name") != "pyoxigraph"
        ),
    )
    with pytest.raises(_graph.ImportGraphError, match="runtime dependencies differ"):
        _graph._prove_source_declaration(**case)


@pytest.mark.spec("SDK-QUALITY-RELEASE-R005")
def test_activated_dependency_extras_are_traversed_transitively() -> None:
    packages = _extras_lock_packages()
    installed = _extras_installed_packages()
    graph, _ = _walk_extras_graph(packages, installed)
    assert graph == (
        "base-lib==1.0",
        "client-lib==1.0",
        "mail-lib==1.0",
        "middle==1.0",
        "root==1.0",
    )


@pytest.mark.spec("SDK-QUALITY-RELEASE-R005")
def test_missing_activated_extra_dependency_fails_closed() -> None:
    packages = _extras_lock_packages()
    installed = _extras_installed_packages()
    del installed["mail-lib"]
    with pytest.raises(
        _graph.ImportGraphError, match="no installed distribution metadata"
    ):
        _walk_extras_graph(packages, installed)


@pytest.mark.spec("SDK-QUALITY-RELEASE-R005")
def test_recorded_graph_provenance_separates_source_and_installed_evidence() -> None:
    evidence = compute_import_graph_evidence()
    graph_bytes = _graph._graph_bytes(evidence.graph)
    _graph._validate_recorded_provenance(evidence, graph_bytes)
    provenance = json.loads(_graph.PROVENANCE_FIXTURE.read_text(encoding="utf-8"))
    assert (
        hashlib.sha256(FIXTURE.read_bytes()).hexdigest() == provenance["graph_sha256"]
    )
    source = evidence.source_declarations[0]
    assert source.name == "epistemic-graph"
    assert source.version == "2.27.0"
    assert source.revision == "a5b4a1f1f638baed374897578cc061f473e9687b"
    assert any(item.startswith("pyoxigraph==") for item in source.locked_dependencies)
    assert {
        "epistemic_graph.generated.query",
        "epistemic_graph.generated.coordination",
    } <= set(source.consumed_modules)
    assert source.consumed_modules
    assert all(
        path.startswith(".ci/epistemic-graph/")
        for path in source.consumed_modules.values()
    )
    graph_names = {item.split("==", 1)[0] for item in evidence.graph}
    source_names = {source.name}
    installed_names = {
        item.split("==", 1)[0] for item in evidence.installed_distributions
    }
    assert graph_names == source_names | installed_names
    assert {
        "epistemic-graph",
        "pyoxigraph",
        "mcp",
        "authlib",
        "uvicorn",
        "email-validator",
    } <= graph_names
    assert isinstance(provenance["installed_distributions"], list)
    assert provenance["installed_distributions"] == list(
        evidence.installed_distributions
    )
    assert provenance["installed_evidence_kind"] == (
        "importlib.metadata distribution metadata"
    )


@pytest.mark.spec("SDK-QUALITY-RELEASE-R005")
@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("installed_distributions", ["forged==1.0"], "differs from live metadata"),
        ("installed_evidence_kind", "unverified cache", "evidence kind is unsupported"),
    ],
)
def test_recorded_provenance_rejects_tampered_installed_evidence(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    field: str,
    value: object,
    message: str,
) -> None:
    evidence = compute_import_graph_evidence()
    graph_bytes = _graph._graph_bytes(evidence.graph)
    provenance = json.loads(_graph.PROVENANCE_FIXTURE.read_text(encoding="utf-8"))
    provenance[field] = value
    path = tmp_path / "provenance.json"
    path.write_text(json.dumps(provenance), encoding="utf-8")
    monkeypatch.setattr(_graph, "PROVENANCE_FIXTURE", path)
    with pytest.raises(_graph.ImportGraphError, match=message):
        _graph._validate_recorded_provenance(evidence, graph_bytes)


def _source_declaration_case() -> dict[str, object]:
    revision = "a5b4a1f1f638baed374897578cc061f473e9687b"
    requirements = (
        "httpx>=0.24.0",
        "msgpack>=1.2.1",
        "pydantic>=2,<3",
        "pyoxigraph>=0.3.22",
    )
    source = _graph.SOURCE_REMOTE + f"?rev={revision}#{revision}"
    dependencies = tuple(
        {"name": name} for name in ("httpx", "msgpack", "pydantic", "pyoxigraph")
    )
    lock_package = _graph.LockedPackage(
        "2.27.0",
        {"git": source},
        dependencies,
    )
    packages = [
        {
            "name": "epistemic-graph",
            "version": "2.27.0",
            "source": {"git": source},
            "dependencies": list(dependencies),
        },
        {"name": "httpx", "version": "0.28.1", "source": {"registry": "pypi"}},
        {"name": "msgpack", "version": "1.2.1", "source": {"registry": "pypi"}},
        {"name": "pydantic", "version": "2.13.5", "source": {"registry": "pypi"}},
        {"name": "pyoxigraph", "version": "0.3.22", "source": {"registry": "pypi"}},
    ]
    lock_metadata = {
        "name": "epistemic-graph",
        "version": "2.27.0",
        "requires-python": ">=3.10",
        "requires-dist": list(requirements),
    }
    return {
        "name": "epistemic-graph",
        "source_version": "2.27.0",
        "source_requires_python": ">=3.10",
        "source_requires": requirements,
        "lock_package": lock_package,
        "lock_metadata": lock_metadata,
        "lock_source_url": _graph.SOURCE_REMOTE,
        "configured_revision": revision,
        "bootstrap_revision": revision,
        "git_revision": revision,
        "git_remote": _graph.SOURCE_REMOTE,
        "import_origin": Path(".ci/epistemic-graph/epistemic_graph/__init__.py"),
        "expected_import_origin": Path(
            ".ci/epistemic-graph/epistemic_graph/__init__.py"
        ),
        "environment": _graph.default_environment(),
        "lock_packages": packages,
    }


def _extras_lock_packages() -> list[dict[str, object]]:
    return [
        {
            "name": "root",
            "version": "1.0",
            "source": {"registry": "pypi"},
            "dependencies": [{"name": "middle", "extra": ["client"]}],
        },
        {
            "name": "middle",
            "version": "1.0",
            "source": {"registry": "pypi"},
            "dependencies": [
                {"name": "base-lib"},
                {
                    "name": "client-lib",
                    "extra": ["mail"],
                    "marker": "extra == 'client'",
                },
            ],
        },
        {
            "name": "base-lib",
            "version": "1.0",
            "source": {"registry": "pypi"},
            "dependencies": [],
        },
        {
            "name": "client-lib",
            "version": "1.0",
            "source": {"registry": "pypi"},
            "dependencies": [],
            "optional-dependencies": {"mail": [{"name": "mail-lib"}]},
        },
        {
            "name": "mail-lib",
            "version": "1.0",
            "source": {"registry": "pypi"},
            "dependencies": [],
        },
    ]


def _extras_installed_packages() -> dict[str, _graph.PackageMetadata]:
    return {
        "root": _graph.PackageMetadata("1.0", ("middle[client]>=1",)),
        "middle": _graph.PackageMetadata(
            "1.0",
            (
                "base-lib>=1",
                "client-lib[mail]>=1; extra == 'client'",
            ),
        ),
        "base-lib": _graph.PackageMetadata("1.0", ()),
        "client-lib": _graph.PackageMetadata(
            "1.0",
            ("mail-lib>=1; extra == 'mail'",),
        ),
        "mail-lib": _graph.PackageMetadata("1.0", ()),
    }


def _walk_extras_graph(
    packages: list[dict[str, object]],
    installed: dict[str, _graph.PackageMetadata],
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    return _graph._walk_graph(
        "root",
        packages=packages,
        environment=_graph.default_environment(),
        get_installed=lambda name: (
            (installed[name], object()) if name in installed else None
        ),
        source_fallback=_graph.PackageMetadata("2.27.0", ()),
    )


def _fake_source_package(
    tmp_path: Path, *additional_paths: Path
) -> tuple[Path, object]:
    package_root = tmp_path / "checkout" / "epistemic_graph"
    package_root.mkdir(parents=True)
    package = type("Package", (), {})()
    package.__file__ = str(package_root / "__init__.py")
    package.__path__ = [
        str(package_root),
        *(str(path) for path in additional_paths),
    ]
    return package_root, package


@pytest.mark.spec("SDK-QUALITY-RELEASE-R005")
def test_unknown_source_package_path_overlay_is_rejected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    package_root, package = _fake_source_package(
        tmp_path, tmp_path / "unexpected-overlay" / "epistemic_graph"
    )
    monkeypatch.setattr(_graph.importlib, "import_module", lambda _: package)
    monkeypatch.setattr(_graph, "_find_sdk_imports", lambda: [])
    with pytest.raises(_graph.ImportGraphError, match="unverified package overlay"):
        _graph._verify_import_origins(package_root.parent, None)


@pytest.mark.spec("SDK-QUALITY-RELEASE-R005")
@pytest.mark.parametrize(
    "module_name",
    [
        "epistemic_graph.generated.source_ingestion",
        "epistemic_graph.generated.query",
        "epistemic_graph.generated.coordination",
    ],
)
def test_consumed_contract_module_from_wheel_overlay_is_rejected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, module_name: str
) -> None:
    package_root, package = _fake_source_package(tmp_path)
    spec = type("ModuleSpec", (), {})()
    spec.origin = str(
        tmp_path
        / "site-packages"
        / "epistemic_graph"
        / "generated"
        / "source_ingestion.py"
    )
    monkeypatch.setattr(_graph.importlib, "import_module", lambda _: package)
    monkeypatch.setattr(
        _graph,
        "_find_sdk_imports",
        lambda: [module_name],
    )
    monkeypatch.setattr(_graph.importlib.util, "find_spec", lambda _: spec)
    with pytest.raises(
        _graph.ImportGraphError, match="outside the pinned source checkout"
    ):
        _graph._verify_import_origins(package_root.parent, None)


@pytest.mark.spec("SDK-QUALITY-RELEASE-R005")
def test_installed_metadata_with_pinned_source_path_and_verified_release_wheel(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source_root = _graph.SOURCE_ROOT.resolve()
    source_package = source_root / "epistemic_graph"
    overlay_package = tmp_path / "site-packages" / "epistemic_graph"
    overlay_package.mkdir(parents=True)
    (overlay_package / "numeric.abi3.so").write_bytes(b"wheel native member")
    manifest = _wheel.EXPECTED
    direct_url = {
        "url": f"file:///tmp/{manifest['wheel_filename']}",
        "archive_info": {"hashes": {"sha256": manifest["wheel_sha256"]}},
    }
    installed = type(
        "Distribution",
        (),
        {
            "version": manifest["version"],
            "read_text": lambda self, _: json.dumps(direct_url),
            "locate_file": lambda self, path: (
                overlay_package
                if path == "epistemic_graph"
                else overlay_package / "numeric.abi3.so"
            ),
        },
    )()
    package = type("Package", (), {})()
    package.__file__ = str(source_package / "__init__.py")
    package.__path__ = [str(source_package), str(overlay_package)]
    spec = type("ModuleSpec", (), {})()
    spec.origin = str(source_package / "generated" / "query.py")
    monkeypatch.setattr(_graph.importlib, "import_module", lambda _: package)
    monkeypatch.setattr(
        _graph, "_find_sdk_imports", lambda: ["epistemic_graph.generated.query"]
    )
    monkeypatch.setattr(_graph.importlib.util, "find_spec", lambda _: spec)

    package_file, consumed = _graph._verify_import_origins(source_root, installed)
    assert package_file == (source_package / "__init__.py").resolve()
    assert consumed["epistemic_graph.generated.query"].startswith(
        ".ci/epistemic-graph/"
    )


@pytest.mark.spec("SDK-QUALITY-RELEASE-R005")
def test_installed_eg_overlay_without_release_wheel_receipt_is_rejected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source_root = _graph.SOURCE_ROOT.resolve()
    source_package = source_root / "epistemic_graph"
    overlay_package = tmp_path / "site-packages" / "epistemic_graph"
    overlay_package.mkdir(parents=True)
    package = type("Package", (), {})()
    package.__file__ = str(source_package / "__init__.py")
    package.__path__ = [str(source_package), str(overlay_package)]
    installed = type(
        "Distribution",
        (),
        {
            "version": "2.27.0",
            "read_text": lambda self, _: None,
            "locate_file": lambda self, _: overlay_package,
        },
    )()
    monkeypatch.setattr(_graph.importlib, "import_module", lambda _: package)
    monkeypatch.setattr(_graph, "_find_sdk_imports", lambda: [])

    with pytest.raises(_wheel.ProvenanceError, match="no valid PEP 610 wheel receipt"):
        _graph._verify_import_origins(source_root, installed)


@pytest.mark.spec("SDK-QUALITY-RELEASE-R005")
def test_release_source_pin_rejects_a_different_commit() -> None:
    with pytest.raises(_wheel.ProvenanceError, match="does not match"):
        _wheel.require_source_revision(
            "f17f47ab300f7f1ddd972d4e0214283a28547e36",
            _graph.RELEASE_MANIFEST,
        )


@pytest.mark.spec("SDK-QUALITY-RELEASE-R005")
def test_release_wheel_receipt_rejects_a_different_artifact_hash() -> None:
    manifest = _wheel.EXPECTED
    direct_url = {
        "url": f"file:///tmp/{manifest['wheel_filename']}",
        "archive_info": {"hashes": {"sha256": "0" * 64}},
    }
    installed = type(
        "Distribution",
        (),
        {
            "version": manifest["version"],
            "read_text": lambda self, _: json.dumps(direct_url),
            "locate_file": lambda self, _: Path("/tmp/missing-native.so"),
        },
    )()
    with pytest.raises(_wheel.ProvenanceError, match="mismatched SHA-256"):
        _wheel.verify_installed_distribution(installed, _graph.RELEASE_MANIFEST)


@pytest.mark.spec("SDK-QUALITY-RELEASE-R005")
def test_installed_eg_metadata_is_checked_against_source_declarations() -> None:
    source = _graph.SourceDeclaration(
        name="epistemic-graph",
        version="2.27.0",
        revision="a5b4a1f1f638baed374897578cc061f473e9687b",
        remote=_graph.SOURCE_REMOTE,
        import_origin=".ci/epistemic-graph/epistemic_graph/__init__.py",
        metadata_sha256={},
        declared_dependencies=(
            "httpx>=0.24.0",
            "msgpack>=1.2.1",
            "pydantic>=2,<3",
            "pyoxigraph>=0.3.22",
        ),
        locked_dependencies=(),
        consumed_modules={},
    )
    environment = _graph.default_environment()
    _graph._validate_installed_source_metadata(
        _graph.PackageMetadata("2.27.0", source.declared_dependencies),
        source,
        environment,
    )
    with pytest.raises(_graph.ImportGraphError, match="installed EG version"):
        _graph._validate_installed_source_metadata(
            _graph.PackageMetadata("2.23.0", source.declared_dependencies),
            source,
            environment,
        )
    with pytest.raises(_graph.ImportGraphError, match="dependency metadata"):
        _graph._validate_installed_source_metadata(
            _graph.PackageMetadata("2.27.0", ("httpx>=0.24.0",)),
            source,
            environment,
        )
