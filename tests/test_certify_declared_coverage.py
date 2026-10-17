import pytest

from agent_connector_sdk.certify.declared_coverage import (
    REQUIRED_PROVENANCE_PATHS,
    DeclaredSemanticCoverage,
    DeclaredSemanticCoverageError,
)


def _shapes(paths=REQUIRED_PROVENANCE_PATHS, classes=("Document",)):
    body = "".join(f"sh:targetClass :{c} ;\n" for c in classes)
    return body + "".join(f"sh:property [ sh:path :{p} ] ;\n" for p in sorted(paths))


@pytest.mark.spec("SDK-CONNECTOR-CONTROL-R700")
@pytest.mark.parametrize(
    ("paths", "declared", "ok"),
    [
        (REQUIRED_PROVENANCE_PATHS, {"Document"}, True),
        (REQUIRED_PROVENANCE_PATHS, {"Document", "Event"}, False),
        (REQUIRED_PROVENANCE_PATHS - {"tenantReference"}, {"Document"}, False),
    ],
)
def test_require_covers(paths, declared, ok):
    coverage = DeclaredSemanticCoverage.from_shapes_text(_shapes(paths))
    assert "Document" in coverage.target_classes
    if ok:
        coverage.require_covers(frozenset(declared))
    else:
        with pytest.raises(DeclaredSemanticCoverageError):
            coverage.require_covers(frozenset(declared))
