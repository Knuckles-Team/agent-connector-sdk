"""The repository's own gates fail on planted violations and pass once fixed."""

from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path
from types import ModuleType

SCRIPTS = Path(__file__).resolve().parents[2] / "scripts"


def _script_module(name: str) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, SCRIPTS / f"{name}.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


KISS_SCOPE = _script_module("kiss_diff_scope")
attributable_violations = KISS_SCOPE.attributable_violations
item_spans = KISS_SCOPE.item_spans


def _git(root: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(root), *args], check=True, capture_output=True)


def _repository(tmp_path: Path, files: dict[str, str]) -> Path:
    for rel, text in files.items():
        (tmp_path / rel).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / rel).write_text(text)
    _git(tmp_path, "init", "-q")
    _git(tmp_path, "add", "--", *files)
    return tmp_path


def _run(script: str, root: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SCRIPTS / script), "--root", str(root)],
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
    planted = _run("check_orphan_modules.py", root)
    assert planted.returncode == 1 and "agent_connector_sdk.orphan" in planted.stdout
    (root / "agent_connector_sdk/api.py").write_text("from . import helper, orphan\n")
    _git(root, "add", "--", "agent_connector_sdk/api.py")
    assert _run("check_orphan_modules.py", root).returncode == 0


def test_public_api_gate_fires_on_an_untested_name(tmp_path: Path) -> None:
    root = _repository(
        tmp_path,
        {
            "agent_connector_sdk/__init__.py": "",
            "agent_connector_sdk/api.py": '__all__ = ["tested", "untested"]\ndef tested(): ...\ndef untested(): ...\n',
            "tests/test_api.py": "from agent_connector_sdk.api import tested, untested\n\ndef test_it():\n    tested()\n",
        },
    )
    planted = _run("check_public_api_tested.py", root)
    assert (
        planted.returncode == 1 and "agent_connector_sdk.api:untested" in planted.stdout
    )
    (root / "tests/test_api.py").write_text(
        "from agent_connector_sdk.api import tested, untested\n\ndef test_it():\n    tested()\n    untested()\n"
    )
    _git(root, "add", "--", "tests/test_api.py")
    assert _run("check_public_api_tested.py", root).returncode == 0


def test_kiss_diff_scope_attributes_only_changed_items() -> None:
    head = "def untouched():\n    return 1\n\n\ndef changed():\n    return 1\n"
    staged = "def untouched():\n    return 1\n\n\ndef changed():\n    return 2\n\n\ndef added():\n    return 3\n"
    report = "\n".join(
        [
            "VIOLATION:returns_per_function:m.py:1:untouched: too many returns",
            "VIOLATION:returns_per_function:m.py:5:changed: too many returns",
            "VIOLATION:returns_per_function:m.py:9:added: too many returns",
            "VIOLATION:functions_per_file:m.py:1:m.py: File has 3 functions",
        ]
    )
    head_report = "VIOLATION:functions_per_file:m.py:1:m.py: File has 2 functions"
    names = [
        v["name"] for v in attributable_violations(staged, report, head, head_report)
    ]
    assert names == ["changed", "added", "m.py"]
    assert [v["name"] for v in attributable_violations(staged, report, None, None)] == [
        "untouched",
        "changed",
        "added",
        "m.py",
    ]
    assert item_spans("not python (", "x") == []
