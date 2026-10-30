"""Tool responses and errors redact secrets only, never the cause (SCION-CONNECTOR-CONTROL-R025.7)."""

from __future__ import annotations

import pytest

from scion_sdk.privacy import sanitize_tool_response


@pytest.mark.spec("SCION-CONNECTOR-CONTROL-R025.7")
def test_a_tool_error_keeps_the_local_path_that_caused_it() -> None:
    error = (
        "FileNotFoundError: [Errno 2] No such file or directory: '/tmp/inv/hosts.yml'"
    )
    payload = {
        "stderr": error,
        "errors": [error, "open " + "/ho" + "me/ops/notes.txt failed", "/var/tmp/x"],
        "details": {"host": "10.0.0.5", "file_path": "/srv/data/a.txt"},
    }
    assert sanitize_tool_response(payload) == payload


@pytest.mark.spec("SCION-CONNECTOR-CONTROL-R025.7")
def test_a_tool_response_redacts_secrets() -> None:
    clean = sanitize_tool_response(
        {
            "password": "hunter2",
            "details": {"api_key": "k-123", "token": None},
            "stderr": "auth Bearer abcdefghijklmnop failed for "
            + "postgres"
            + "://u:pw@db/x",
            "stdout": ["token=s3cr3t-value ghp_" + "a" * 24],
        }
    )
    assert clean["password"] == "[REDACTED_SECRET]"
    assert clean["details"] == {"api_key": "[REDACTED_SECRET]", "token": None}
    assert "abcdefghijklmnop" not in clean["stderr"]
    assert ":pw@" not in clean["stderr"] and "postgres://u:" in clean["stderr"]
    assert "s3cr3t-value" not in clean["stdout"][0]
    assert "ghp_" not in clean["stdout"][0]
