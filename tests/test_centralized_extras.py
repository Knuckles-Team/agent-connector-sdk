"""Every SDK extra is indexed by a centralized-capability row (SC-002)."""

from __future__ import annotations

import re
import tomllib
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
REQUIREMENTS = ROOT / "specs" / "centralized-capabilities" / "requirements.md"


def _extras() -> dict[str, list[str]]:
    data = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    return data["project"]["optional-dependencies"]


def _row(row_id: str) -> str:
    for line in REQUIREMENTS.read_text(encoding="utf-8").splitlines():
        if line.startswith(f"| `{row_id}`"):
            return line
    raise AssertionError(f"row {row_id} missing")


@pytest.mark.spec("SCION-CENTRALIZED-CAPABILITIES-R040")
def test_every_extra_has_a_row() -> None:
    listed = set(
        re.findall(r"`([a-z0-9-]+)`", _row("SCION-CENTRALIZED-CAPABILITIES-R040"))
    )
    missing = sorted(set(_extras()) - listed)
    assert missing == []


@pytest.mark.spec("SCION-CENTRALIZED-CAPABILITIES-R025")
@pytest.mark.spec("SCION-CENTRALIZED-CAPABILITIES-R040")
def test_vector_extras_share_db_floors() -> None:
    extras = _extras()
    names = {
        extra: {re.split(r"[\[<>=]", req, maxsplit=1)[0].lower() for req in reqs}
        for extra, reqs in extras.items()
    }
    assert {"qdrant-client", "psycopg", "pymongo"} <= names["vector"]
    assert {"chromadb", "llama-index-vector-stores-chroma"} <= names["vector-chroma"]

    def floor(extra: str, name: str) -> str:
        for req in extras[extra]:
            if req.lower().startswith(name):
                return req.split(">=", 1)[1]
        raise AssertionError(f"{name} missing from {extra}")

    for shared in ("psycopg", "pymongo"):
        assert floor("vector", shared) == floor("db", shared)
