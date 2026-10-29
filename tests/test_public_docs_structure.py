"""The public documentation keeps the task-first README and site structure.

``README.md`` leads with the one-file connector quick start and keeps a fixed
top-level section order; the published site (``mkdocs.yml``) presents the
task-first tutorial before the architecture guide.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
README = ROOT / "README.md"
MKDOCS = ROOT / "mkdocs.yml"


@pytest.mark.spec("SCION-QUALITY-RELEASE-R004")
def test_readme_follows_the_task_first_section_order() -> None:
    text = README.read_text(encoding="utf-8")
    headings = re.findall(r"^## (.+)$", text, re.MULTILINE)

    assert headings == [
        "Quick Start",
        "Overview",
        "Key Capabilities",
        "Documentation",
        "Architecture",
        "Contributing",
        "License",
    ]
    quick_start = text.split("## Quick Start", 1)[1].split("\n## ", 1)[0]
    # The quick start leads with the one-file connector example.
    assert "```" in quick_start


@pytest.mark.spec("SCION-QUALITY-RELEASE-R004")
def test_site_nav_presents_the_task_first_tutorial_and_architecture() -> None:
    nav = yaml.safe_load(MKDOCS.read_text(encoding="utf-8"))["nav"]

    assert nav[0] == {"Home": "index.md"}
    tutorial_index = nav.index({"Build your first connector": "tutorial.md"})
    architecture = next(
        entry for entry in nav if isinstance(entry, dict) and "Architecture" in entry
    )
    assert tutorial_index < nav.index(architecture)
    assert {"Overview": "architecture.md"} in architecture["Architecture"]
