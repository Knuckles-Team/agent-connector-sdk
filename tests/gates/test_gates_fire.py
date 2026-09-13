"""The repository's own wiring gates fail on planted violations and pass once fixed.

The shared hooks (complexity, KISS, clones, security, hygiene, code shape) are
proven to fire by their own test suite in the pipelines hook repository.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

WIRING = Path(__file__).resolve().parents[2] / "scripts" / "check_wiring.py"


def _git(root: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(root), *args], check=True, capture_output=True)


def _repository(tmp_path: Path, files: dict[str, str]) -> Path:
    for rel, text in files.items():
        (tmp_path / rel).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / rel).write_text(text)
    _git(tmp_path, "init", "-q")
    _git(tmp_path, "add", "--", *files)
    return tmp_path


def _run(check: str, root: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(WIRING), check, "--root", str(root)],
        capture_output=True,
        text=True,
        check=False,
    )


PYPROJECT = """
[project]
name = "fixture"
[project.entry-points."agent_connector_sdk.sinks"]
fixture = "agent_connector_sdk.plugin:Plugin"
[tool.agent_connector_sdk.wiring]
public_modules = ["agent_connector_sdk.api"]
"""


def test_orphan_module_gate_fires_on_a_planted_orphan(tmp_path: Path) -> None:
    root = _repository(
        tmp_path,
        {
            "pyproject.toml": PYPROJECT,
            "agent_connector_sdk/__init__.py": "",
            "agent_connector_sdk/api.py": "from agent_connector_sdk import helper\n",
            "agent_connector_sdk/helper.py": "VALUE = 1\n",
            "agent_connector_sdk/plugin.py": "class Plugin: ...\n",
            "agent_connector_sdk/orphan.py": "UNUSED = 1\n",
        },
    )
    planted = _run("orphans", root)
    assert planted.returncode == 1 and "agent_connector_sdk.orphan" in planted.stdout
    (root / "agent_connector_sdk/api.py").write_text("from . import helper, orphan\n")
    _git(root, "add", "--", "agent_connector_sdk/api.py")
    assert _run("orphans", root).returncode == 0


def test_public_api_gate_fires_on_an_untested_name(tmp_path: Path) -> None:
    root = _repository(
        tmp_path,
        {
            "agent_connector_sdk/__init__.py": "",
            "agent_connector_sdk/api.py": '__all__ = ["tested", "untested"]\ndef tested(): ...\ndef untested(): ...\n',
            "tests/test_api.py": "from agent_connector_sdk.api import tested, untested\n\ndef test_it():\n    tested()\n",
        },
    )
    planted = _run("public-api", root)
    assert (
        planted.returncode == 1 and "agent_connector_sdk.api:untested" in planted.stdout
    )
    (root / "tests/test_api.py").write_text(
        "from agent_connector_sdk.api import tested, untested\n\ndef test_it():\n    tested()\n    untested()\n"
    )
    _git(root, "add", "--", "tests/test_api.py")
    assert _run("public-api", root).returncode == 0
