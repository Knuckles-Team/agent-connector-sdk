"""Tests for the R001 isolated-consumer plan and R005 import-graph reproducibility helpers.

SDK-QUALITY-RELEASE-R001 and -R005 (see specs/SDK-QUALITY-RELEASE/requirements.md).
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import sys
import zipfile
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
    assert requirement.startswith("medulla")
    assert any(op in requirement for op in (">=", "==", "~="))


@pytest.mark.spec("SDK-QUALITY-RELEASE-R001")
def test_pinned_graph_client_requirement_fails_closed_without_a_dependency() -> None:
    with pytest.raises(CompatibilityGateError):
        pinned_graph_client_requirement('[project]\nname = "x"\ndependencies = []\n')


@pytest.mark.spec("SDK-QUALITY-RELEASE-R001")
def test_isolated_install_plan_never_installs_from_the_source_overlay() -> None:
    plan = isolated_install_plan(
        Path("dist/scion_sdk-1.0.0-py3-none-any.whl"),
        "medulla>=2.27.0,<3",
        Path("dist-consumer-venv"),
    )
    flat = [" ".join(command) for command in plan]
    assert any(cmd.startswith("uv venv") for cmd in flat)
    install_commands = [cmd for cmd in flat if "pip install" in cmd]
    assert install_commands, "plan must install the built wheel into the isolated venv"
    for command in install_commands:
        assert "-e ." not in command
        assert "scion_sdk-1.0.0-py3-none-any.whl" in command
        assert "medulla>=2.27.0,<3" in command
        assert "--python dist-consumer-venv" in command


@pytest.mark.spec("SDK-QUALITY-RELEASE-R001")
def test_isolated_install_plan_rejects_a_non_wheel_path() -> None:
    with pytest.raises(CompatibilityGateError):
        isolated_install_plan(
            Path("dist/not-a-wheel.tar.gz"), "medulla>=2.27.0,<3", Path("venv")
        )


@pytest.mark.spec("SDK-QUALITY-RELEASE-R005")
def test_local_pinned_install_reproduces_hosted_import_graph() -> None:
    """The exact import graph computed under this pinned environment must
    equal the recorded graph committed from an equivalently pinned
    PyPI resolve, proving local verification never drifts
    from the hosted release check without a visible, reviewable diff."""
    assert FIXTURE.exists(), "tests/fixtures/pinned_import_graph.txt must be committed"
    recorded = read_recorded_graph()
    evidence = compute_import_graph_evidence()
    live = list(evidence.graph)
    assert live == recorded, (
        "local import graph drifted from the recorded hosted result; "
        "re-run uv run --frozen --no-sync "
        "python scripts/check_import_graph_reproducibility.py --record"
    )


@pytest.mark.spec("SDK-QUALITY-RELEASE-R005")
def test_recorded_import_graph_is_sorted_and_deduplicated() -> None:
    recorded = read_recorded_graph()
    assert recorded == sorted(set(recorded))
    assert all("==" in entry for entry in recorded)


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
    )


@pytest.mark.spec("SDK-QUALITY-RELEASE-R005")
def test_tampered_installed_native_file_fails_with_matching_pep610_hash(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    manifest = dict(_wheel.EXPECTED)
    wheel = tmp_path / manifest["wheel_filename"]
    native = manifest["native_member"]
    members = {
        "epistemic_graph/__init__.py": b"__version__ = '2.27.10'\n",
        native: b"trusted native engine",
        "medulla-2.27.10.dist-info/METADATA": (
            b"Metadata-Version: 2.3\nName: medulla\nVersion: 2.27.10\n"
        ),
        "medulla-2.27.10.dist-info/WHEEL": (
            b"Wheel-Version: 1.0\nRoot-Is-Purelib: false\n"
            b"Tag: cp39-abi3-manylinux_2_28_x86_64\n"
        ),
    }
    with zipfile.ZipFile(wheel, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, data in members.items():
            archive.writestr(name, data)
    manifest["wheel_sha256"] = hashlib.sha256(wheel.read_bytes()).hexdigest()
    manifest_path = tmp_path / "release.json"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    monkeypatch.setattr(_wheel, "EXPECTED", manifest)

    site_packages = tmp_path / "site-packages"
    with zipfile.ZipFile(wheel) as archive:
        archive.extractall(site_packages)
    installed_native = site_packages / native
    installed_native.write_bytes(b"tampered native engine")
    receipt_text = json.dumps(
        {
            "url": wheel.as_uri(),
            "archive_info": {"hashes": {"sha256": manifest["wheel_sha256"]}},
        }
    )

    class Distribution:
        version = manifest["version"]

        def read_text(self, name: str) -> str | None:
            assert name == "direct_url.json"
            return receipt_text

        def locate_file(self, name: str) -> Path:
            return site_packages / name

    with pytest.raises(_wheel.ProvenanceError, match="installed EG file differs"):
        _wheel.verify_installed_distribution(Distribution(), manifest_path)
    assert Distribution().read_text("direct_url.json") == receipt_text


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


def _eg_lock_package(**over: object) -> dict[str, object]:
    package: dict[str, object] = {
        "name": "medulla",
        "version": "2.27.1",
        "source": {"registry": _graph.REGISTRY},
        "wheels": [
            {
                "url": "https://files.pythonhosted.org/x/epistemic_graph-2.27.1-cp39-abi3-manylinux_2_28_x86_64.whl",
                "hash": "sha256:" + "a" * 64,
            }
        ],
    }
    package.update(over)
    return package


@pytest.mark.spec("SDK-QUALITY-RELEASE-R005")
def test_locked_eg_is_a_pypi_wheel_and_never_a_source_build() -> None:
    assert _graph._locked_wheels(_eg_lock_package()) == {
        "epistemic_graph-2.27.1-cp39-abi3-manylinux_2_28_x86_64.whl": "a" * 64
    }


@pytest.mark.spec("SDK-QUALITY-RELEASE-R005")
@pytest.mark.parametrize(
    ("over", "message"),
    [
        (
            {"source": {"git": "https://github.com/Knuckles-Team/medulla.git"}},
            "must pin medulla to",
        ),
        ({"wheels": []}, "pins no medulla wheel"),
        ({"wheels": [{"url": "https://x/eg.whl", "hash": "md5:0"}]}, "unverifiable"),
    ],
)
def test_locked_eg_rejects_git_or_unhashed_sources(
    over: dict[str, object], message: str
) -> None:
    with pytest.raises(_graph.ImportGraphError, match=message):
        _graph._locked_wheels(_eg_lock_package(**over))


@pytest.mark.spec("SDK-QUALITY-RELEASE-R005")
def test_locked_eg_sdist_beside_wheels_still_installs_the_wheel() -> None:
    package = _eg_lock_package(sdist={"url": "https://x/eg.tar.gz"})
    assert _graph._locked_wheels(package) == {
        "epistemic_graph-2.27.1-cp39-abi3-manylinux_2_28_x86_64.whl": "a" * 64
    }


@pytest.mark.spec("SDK-QUALITY-RELEASE-R005")
def test_pyproject_must_forbid_an_eg_source_build() -> None:
    _graph._no_build_configured(_graph._read_toml(_graph.ROOT_PYPROJECT))
    with pytest.raises(_graph.ImportGraphError, match="no-build-package"):
        _graph._no_build_configured({"tool": {"uv": {}}})
    with pytest.raises(_graph.ImportGraphError, match="override"):
        _graph._no_build_configured(
            {
                "tool": {
                    "uv": {
                        "no-build-package": ["medulla"],
                        "sources": {"medulla": {"git": "x"}},
                    }
                }
            }
        )


@pytest.mark.spec("SDK-QUALITY-RELEASE-R005")
def test_recorded_graph_provenance_binds_the_installed_pypi_wheel() -> None:
    evidence = compute_import_graph_evidence()
    graph_bytes = _graph._graph_bytes(evidence.graph)
    _graph._validate_recorded_provenance(evidence, graph_bytes)
    provenance = json.loads(_graph.PROVENANCE_FIXTURE.read_text(encoding="utf-8"))
    assert (
        hashlib.sha256(FIXTURE.read_bytes()).hexdigest() == provenance["graph_sha256"]
    )
    (declaration,) = evidence.registry_declarations
    assert (declaration.name, declaration.registry) == (
        "medulla",
        "https://pypi.org/simple",
    )
    manifest = _wheel.read_manifest(_graph.RELEASE_MANIFEST)
    assert declaration.version == manifest["version"]
    assert (
        declaration.locked_wheels[manifest["wheel_filename"]]
        == manifest["wheel_sha256"]
    )
    assert any(
        item.startswith("pyoxigraph==") for item in declaration.locked_dependencies
    )
    assert {
        "epistemic_graph.generated.query",
        "epistemic_graph.generated.coordination",
        "epistemic_graph.generated.source_ingestion",
    } <= set(declaration.consumed_modules)
    assert all(
        path.startswith("epistemic_graph/")
        for path in declaration.consumed_modules.values()
    )
    graph_names = {item.split("==", 1)[0] for item in evidence.graph}
    installed_names = {
        item.split("==", 1)[0] for item in evidence.installed_distributions
    }
    assert graph_names == installed_names
    assert {
        "medulla",
        "pyoxigraph",
        "mcp-types",
        "httpx2",
        "cryptography",
    } <= graph_names
    assert provenance["installed_evidence_kind"] == (
        "importlib.metadata distribution metadata"
    )


class _Package:
    def __init__(self, *paths: Path) -> None:
        self.__path__ = [str(path) for path in paths]


class _Distribution:
    def __init__(self, package: Path) -> None:
        self._package = package

    def locate_file(self, name: str) -> Path:
        return self._package.parent / name


@pytest.mark.spec("SDK-QUALITY-RELEASE-R005")
def test_package_overlay_beyond_the_installed_wheel_is_rejected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    wheel = tmp_path / "site-packages" / "epistemic_graph"
    wheel.mkdir(parents=True)
    overlay = tmp_path / "checkout" / "epistemic_graph"
    monkeypatch.setattr(
        _graph.importlib, "import_module", lambda _: _Package(overlay, wheel)
    )
    with pytest.raises(_graph.ImportGraphError, match="package overlay"):
        _graph._verify_import_origins(_Distribution(wheel))


@pytest.mark.spec("SDK-QUALITY-RELEASE-R005")
def test_consumed_module_outside_the_installed_wheel_is_rejected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    wheel = tmp_path / "site-packages" / "epistemic_graph"
    wheel.mkdir(parents=True)
    spec = type("ModuleSpec", (), {})()
    spec.origin = str(tmp_path / "checkout" / "epistemic_graph" / "generated" / "q.py")
    monkeypatch.setattr(_graph.importlib, "import_module", lambda _: _Package(wheel))
    monkeypatch.setattr(
        _graph, "_find_sdk_imports", lambda: ["epistemic_graph.generated.query"]
    )
    monkeypatch.setattr(_graph.importlib.util, "find_spec", lambda _: spec)
    with pytest.raises(_graph.ImportGraphError, match="outside the installed PyPI"):
        _graph._verify_import_origins(_Distribution(wheel))

    spec.origin = str(wheel / "generated" / "query.py")
    assert _graph._verify_import_origins(_Distribution(wheel)) == {
        "epistemic_graph.generated.query": "epistemic_graph/generated/query.py"
    }
