"""Validate the capability index against SDK paths and owning spec rows."""

from __future__ import annotations

import re
import tomllib
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
INDEX = ROOT / "specs/centralized-capabilities/plan.md"
PACKAGE = ROOT / "agent_connector_sdk"
ROW_ID = re.compile(r"SDK-CENTRALIZED-CAPABILITIES-R\d{3}")
OWNER_ID = re.compile(r"SDK-[A-Z-]+-R\d+(?:\.\d+)?\Z")


def _index_rows(text: str) -> dict[str, tuple[str, str]]:
    rows = {}
    for line in text.splitlines():
        parts = line.split("|")
        if len(parts) < 6:
            continue
        row = parts[1].strip().strip("`")
        if ROW_ID.fullmatch(row):
            if len(parts) < 7 or not parts[2].strip() or not parts[5].strip():
                raise ValueError(f"capability or conformance method missing: {row}")
            if row in rows:
                raise ValueError(f"duplicate capability row: {row}")
            rows[row] = (parts[3], parts[4])
    return rows


def _owner_ids() -> set[str]:
    owners: set[str] = set()
    for path in (ROOT / "specs").glob("*/requirements.md"):
        owners.update(re.findall(r"(?m)^\| `([^`]+)`", path.read_text()))
    return owners


def _validate_row(owner_cell: str, module_cell: str, owners: set[str]) -> None:
    references = re.findall(r"`([^`]+)`", owner_cell)
    for owner in references:
        if not OWNER_ID.fullmatch(owner) or owner not in owners:
            raise ValueError(f"unknown owner row: {owner}")
    if not references and "this spec" not in owner_cell:
        raise ValueError("owner row missing")

    project = tomllib.loads((ROOT / "pyproject.toml").read_text())
    extras = project["project"]["optional-dependencies"]
    scripts = project["project"]["scripts"]
    parent = ""
    for item in re.findall(r"`([^`]+)`", module_cell):
        if item in {"pyproject.toml", "[project.optional-dependencies]", "next_url"}:
            continue
        if item in extras or item in scripts:
            continue
        if not (item.endswith((".py", "/")) or "*" in item):
            raise ValueError(f"unknown extra, script, or module: {item}")
        candidate = item
        if "/" not in item and parent and not list(PACKAGE.glob(item)):
            candidate = parent + item
        if "/" in candidate:
            parent = candidate.rsplit("/", 1)[0] + "/"
        if not list(PACKAGE.glob(candidate)):
            raise ValueError(f"missing module: {candidate}")


# spec: SDK-CENTRALIZED-CAPABILITIES-R001
# spec: SDK-CENTRALIZED-CAPABILITIES-R002
# spec: SDK-CENTRALIZED-CAPABILITIES-R003
# spec: SDK-CENTRALIZED-CAPABILITIES-R004
# spec: SDK-CENTRALIZED-CAPABILITIES-R005
# spec: SDK-CENTRALIZED-CAPABILITIES-R006
# spec: SDK-CENTRALIZED-CAPABILITIES-R007
# spec: SDK-CENTRALIZED-CAPABILITIES-R008
# spec: SDK-CENTRALIZED-CAPABILITIES-R009
# spec: SDK-CENTRALIZED-CAPABILITIES-R010
# spec: SDK-CENTRALIZED-CAPABILITIES-R011
# spec: SDK-CENTRALIZED-CAPABILITIES-R012
# spec: SDK-CENTRALIZED-CAPABILITIES-R013
# spec: SDK-CENTRALIZED-CAPABILITIES-R014
# spec: SDK-CENTRALIZED-CAPABILITIES-R015
# spec: SDK-CENTRALIZED-CAPABILITIES-R016
# spec: SDK-CENTRALIZED-CAPABILITIES-R017
# spec: SDK-CENTRALIZED-CAPABILITIES-R018
# spec: SDK-CENTRALIZED-CAPABILITIES-R019
# spec: SDK-CENTRALIZED-CAPABILITIES-R020
# spec: SDK-CENTRALIZED-CAPABILITIES-R021
# spec: SDK-CENTRALIZED-CAPABILITIES-R022
# spec: SDK-CENTRALIZED-CAPABILITIES-R023
# spec: SDK-CENTRALIZED-CAPABILITIES-R024
# spec: SDK-CENTRALIZED-CAPABILITIES-R025
# spec: SDK-CENTRALIZED-CAPABILITIES-R026
# spec: SDK-CENTRALIZED-CAPABILITIES-R027
# spec: SDK-CENTRALIZED-CAPABILITIES-R028
# spec: SDK-CENTRALIZED-CAPABILITIES-R029
# spec: SDK-CENTRALIZED-CAPABILITIES-R030
# spec: SDK-CENTRALIZED-CAPABILITIES-R031
# spec: SDK-CENTRALIZED-CAPABILITIES-R032
# spec: SDK-CENTRALIZED-CAPABILITIES-R033
# spec: SDK-CENTRALIZED-CAPABILITIES-R034
# spec: SDK-CENTRALIZED-CAPABILITIES-R035
# spec: SDK-CENTRALIZED-CAPABILITIES-R036
# spec: SDK-CENTRALIZED-CAPABILITIES-R037
# spec: SDK-CENTRALIZED-CAPABILITIES-R038
# spec: SDK-CENTRALIZED-CAPABILITIES-R039
# spec: SDK-CENTRALIZED-CAPABILITIES-R040
@pytest.mark.parametrize("number", range(1, 41), ids=lambda number: f"R{number:03d}")
def test_index_row_modules_and_owners_exist(number: int) -> None:
    rows = _index_rows(INDEX.read_text())
    expected = {f"SDK-CENTRALIZED-CAPABILITIES-R{i:03d}" for i in range(1, 41)}
    assert set(rows) == expected
    _validate_row(*rows[f"SDK-CENTRALIZED-CAPABILITIES-R{number:03d}"], _owner_ids())


def test_index_rejects_missing_module_and_unknown_owner() -> None:
    with pytest.raises(ValueError, match="missing module"):
        _validate_row("`SDK-CONNECTOR-CONTROL-R028`", "`absent.py`", _owner_ids())
    with pytest.raises(ValueError, match="unknown owner row"):
        _validate_row(
            "`SDK-CONNECTOR-CONTROL-R999999`", "`http/client.py`", _owner_ids()
        )


def test_index_rejects_missing_capability_or_conformance() -> None:
    row = "SDK-CENTRALIZED-CAPABILITIES-R001"
    for capability, method in (("", "unchecked"), ("HTTP", "")):
        with pytest.raises(
            ValueError, match="capability or conformance method missing"
        ):
            _index_rows(f"| `{row}` | {capability} | owner | module | {method} |")
