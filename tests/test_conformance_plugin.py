"""SCION-QUALITY-RELEASE-R005.1: the pytest plugin generates connector conformance tests."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
from connector_dist import ORPHAN, build

from scion_sdk.connector import resolve_connector
from scion_sdk.testing.conformance import (
    CHECKS,
    REMOVED_PROVIDER_GROUPS,
    run_check,
)
from scion_sdk.testing.ontology_rollup import orphan_classes
from scion_sdk.testing.plugin import declared_package

pytest_plugins = ["pytester"]


def _install(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, **kwargs):
    build(tmp_path, **kwargs)
    monkeypatch.syspath_prepend(str(tmp_path))
    for name in [m for m in sys.modules if m.split(".")[0] == "democonn"]:
        monkeypatch.delitem(sys.modules, name)
    return resolve_connector("democonn")


@pytest.mark.spec("SCION-QUALITY-RELEASE-R005.1")
def test_every_check_passes_for_a_conforming_connector(tmp_path, monkeypatch) -> None:
    resolved = _install(tmp_path, monkeypatch)
    for check in CHECKS:
        run_check(check.name, resolved)
    for name in [m for m in sys.modules if m.split(".")[0] == "democonn"]:
        sys.modules.pop(name)


@pytest.mark.spec("SCION-QUALITY-RELEASE-R005.1")
@pytest.mark.parametrize(
    ("check", "kwargs", "message"),
    [
        ("ontology_rollup", {"ontology": ORPHAN}, "orphan classes"),
        (
            "version_from_metadata",
            {"extra_files": {"legacy.py": '__version__ = "9.9.9"\n'}},
            "spells __version__",
        ),
        (
            "fleet_name",
            {
                "extra_files": {
                    "legacy.py": 'IngestBinding(connector="other-mcp", stream="s")\n'
                }
            },
            "spells connector",
        ),
        (
            "one_entry_point",
            {"extra_group": "scion_sdk.skill_providers"},
            "remove entry-point groups",
        ),
        (
            "connector_sources",
            {
                "extra_files": {"connector_sources.py": "SCHEMA_VERSION = 9\n"},
                "sources": None,
            },
            "SCHEMA_VERSION",
        ),
        (
            "connector_sources",
            {"sources": "def declaration():\n    return None\n"},
            "declaration() belongs to the SDK",
        ),
    ],
)
def test_breaking_one_property_fails_its_named_check(
    tmp_path, monkeypatch, check, kwargs, message
) -> None:
    resolved = _install(tmp_path, monkeypatch, **kwargs)
    with pytest.raises((AssertionError, ValueError)) as failure:
        run_check(check, resolved)
    assert message in str(failure.value)
    for name in [m for m in sys.modules if m.split(".")[0] == "democonn"]:
        sys.modules.pop(name)


@pytest.mark.spec("SCION-QUALITY-RELEASE-R005.1")
def test_removed_groups_are_the_three_provider_groups() -> None:
    assert len(REMOVED_PROVIDER_GROUPS) == 3


@pytest.mark.spec("SCION-QUALITY-RELEASE-R005.1")
def test_orphan_classes_reads_transitive_parents(tmp_path) -> None:
    path = tmp_path / "o.ttl"
    path.write_text(ORPHAN)
    assert orphan_classes(path) == {"https://example.invalid/ontology/demo#Lonely"}


@pytest.mark.spec("SCION-QUALITY-RELEASE-R005.1")
def test_declared_package_reads_the_pyproject(tmp_path) -> None:
    assert declared_package(tmp_path) is None
    build(tmp_path)
    assert declared_package(tmp_path) == "democonn"


@pytest.mark.spec("SCION-QUALITY-RELEASE-R005.1")
def test_plugin_generates_one_test_per_check_in_a_connector_repository(
    pytester, monkeypatch
) -> None:
    build(pytester.path)
    monkeypatch.setenv("PYTHONPATH", str(pytester.path))
    result = pytester.runpytest_subprocess("-q", "-p", "no:cacheprovider")
    result.assert_outcomes(passed=len(CHECKS))


@pytest.mark.spec("SCION-QUALITY-RELEASE-R005.1")
def test_plugin_is_inert_without_a_declaration_and_for_explicit_node_ids(
    pytester, monkeypatch
) -> None:
    pytester.makepyfile(test_one="def test_one():\n    pass\n")
    result = pytester.runpytest_subprocess("-q", "-p", "no:cacheprovider")
    result.assert_outcomes(passed=1)
    build(pytester.path)
    monkeypatch.setenv("PYTHONPATH", str(pytester.path))
    result = pytester.runpytest_subprocess(
        "-q", "-p", "no:cacheprovider", "test_one.py::test_one"
    )
    result.assert_outcomes(passed=1)


@pytest.mark.spec("SCION-QUALITY-RELEASE-R005.1")
def test_ontology_parser_and_namespace(tmp_path) -> None:
    from scion_sdk.testing.ontology_rollup import (
        CORE_NAMESPACE,
        parse_triples,
    )

    triples = parse_triples(ORPHAN)
    assert any(o == CORE_NAMESPACE + "Document" for _, _, o in triples)


@pytest.mark.spec("SCION-QUALITY-RELEASE-R005.1")
def test_generated_items_carry_the_check_and_spec_marker(tmp_path, monkeypatch) -> None:
    from scion_sdk.testing.conformance import Check
    from scion_sdk.testing.plugin import ConformanceItem

    assert all(isinstance(check, Check) for check in CHECKS)
    assert ConformanceItem.__mro__[1] is pytest.Item


@pytest.mark.spec("SCION-QUALITY-RELEASE-R005.1")
def test_startup_check_requires_the_health_route_to_answer(
    tmp_path, monkeypatch
) -> None:
    from scion_sdk.testing import conformance

    resolved = _install(tmp_path, monkeypatch)
    assert conformance._health_status(conformance._server(resolved)) == 200
    monkeypatch.setattr(conformance, "_health_status", lambda mcp: 503)
    with pytest.raises(conformance.ConformanceFailure, match="/health"):
        run_check("startup", resolved)
    for name in [m for m in sys.modules if m.split(".")[0] == "democonn"]:
        sys.modules.pop(name)
