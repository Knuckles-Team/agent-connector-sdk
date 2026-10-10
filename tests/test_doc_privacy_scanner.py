"""SDK-QUALITY-RELEASE-R002: the public-docs privacy scanner catches leaks.

A planted private IPv4 address and an environment-only (``.arpa``) hostname
in a published Markdown page must fail ``scripts/check_documentation_privacy.py``;
a clean doc tree must pass.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[1]
_SCRIPT = _REPO_ROOT / "scripts" / "check_documentation_privacy.py"


def _run(root: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(_SCRIPT), "--root", str(root)],
        capture_output=True,
        text=True,
    )


@pytest.mark.spec("SDK-QUALITY-RELEASE-R002")
def test_planted_private_ip_and_environment_hostname_fail_then_clean_tree_passes(
    tmp_path: Path,
) -> None:
    docs = tmp_path / "docs"
    docs.mkdir()
    violating = docs / "guide.md"
    violating.write_text(
        "# Guide\n\n"
        "Connect to 192.168.1.42 for the internal service.\n"
        "Resolve host via r510.arpa for diagnostics.\n"
    )
    result = _run(tmp_path)
    assert result.returncode == 1, result.stderr
    assert "PRIVATE_IPV4" in result.stderr
    assert "ENVIRONMENT_DNS" in result.stderr

    violating.write_text("# Guide\n\nConnect to the public documented endpoint.\n")
    clean = _run(tmp_path)
    assert clean.returncode == 0, clean.stderr
