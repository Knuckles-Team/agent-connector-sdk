"""SCION-CONNECTOR-CONTROL-R014.17: the base install imports without fastmcp or mcp."""

from __future__ import annotations

import subprocess
import sys
import textwrap

import pytest

_PRELUDE = textwrap.dedent(
    """
    import sys

    class _Block:
        def find_spec(self, name, path=None, target=None):
            if name.split(".")[0] in ("fastmcp", "mcp"):
                raise ModuleNotFoundError(f"No module named {name!r}", name=name)

    sys.meta_path.insert(0, _Block())
    """
)


def _run(body: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-I", "-c", _PRELUDE + textwrap.dedent(body)],
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )


@pytest.mark.spec("SCION-CONNECTOR-CONTROL-R014.17")
def test_base_modules_import_without_the_mcp_extra() -> None:
    result = _run(
        """
        import importlib
        for name in (
            "scion_sdk.http.client",
            "scion_sdk.exposure",
            "scion_sdk.auth.delegation",
            "scion_sdk.artifacts.pack",
            "scion_sdk.artifacts.prompts",
            "scion_sdk.ports.sink",
            "scion_sdk.runner.provisioning",
            "scion_sdk.runner.worker",
            "scion_sdk.certify.cli",
            "scion_sdk.sinks.epistemic_graph",
        ):
            importlib.import_module(name)
        """
    )
    assert result.returncode == 0, result.stderr


@pytest.mark.spec("SCION-CONNECTOR-CONTROL-R014.17")
def test_mcp_surface_names_the_extra_when_missing() -> None:
    result = _run(
        """
        import importlib
        for name in ("scion_sdk.mcp", "scion_sdk.transports.mcp"):
            try:
                importlib.import_module(name)
            except ImportError as exc:
                assert "scion-sdk[mcp]" in str(exc), exc
            else:
                raise SystemExit(name + " imported without the extra")
        """
    )
    assert result.returncode == 0, result.stderr


@pytest.mark.spec("SCION-CONNECTOR-CONTROL-R014.17")
def test_current_user_token_needs_the_extra() -> None:
    result = _run(
        """
        from scion_sdk.auth.delegation import current_user_token
        try:
            current_user_token()
        except ImportError as exc:
            assert "[mcp]" in str(exc)
        else:
            raise SystemExit("no error")
        """
    )
    assert result.returncode == 0, result.stderr


def test_mcp_extra_present_in_this_environment() -> None:
    import scion_sdk.mcp  # noqa: F401
    from scion_sdk.mcp.exposure import is_loopback_host

    assert is_loopback_host("localhost")
