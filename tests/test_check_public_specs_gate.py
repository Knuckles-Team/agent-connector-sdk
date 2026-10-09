"""The public-specs privacy gate accepts the gitlab-api connector by name.

``scripts/check_public_specs.py`` forbids a bare ``gitlab`` mention so a
public spec never leaks the internal, self-hosted GitLab instance. The
fleet also ships a real public connector repository literally named
``gitlab-api`` (a GitLab REST API client), which a batch migration table
must be able to name. The forbidden-reference pattern excludes exactly
that token while still catching a genuine internal mention.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest


def _load_check_public_specs():
    module_path = (
        Path(__file__).resolve().parents[1] / "scripts" / "check_public_specs.py"
    )
    spec = importlib.util.spec_from_file_location(
        "check_public_specs_under_test", module_path
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def check_public_specs():
    return _load_check_public_specs()


@pytest.mark.spec("SDK-CONNECTOR-CONTROL-R009", "SDK-CONNECTOR-CONTROL-R010", "SDK-CONNECTOR-CONTROL-R011", "SDK-CONNECTOR-CONTROL-R012", "SDK-CONNECTOR-CONTROL-R013")
def test_gitlab_api_connector_name_is_not_forbidden(check_public_specs):
    content = "Migrated `gitlab-api` in pull request https://github.com/Knuckles-Team/gitlab-api/pull/13."
    assert not any(pattern.search(content) for pattern in check_public_specs.FORBIDDEN)


@pytest.mark.spec("SDK-CONNECTOR-CONTROL-R009", "SDK-CONNECTOR-CONTROL-R010", "SDK-CONNECTOR-CONTROL-R011", "SDK-CONNECTOR-CONTROL-R012", "SDK-CONNECTOR-CONTROL-R013")
def test_bare_gitlab_mention_is_still_forbidden(check_public_specs):
    content = "Configure the outbound token against our internal gitlab server."
    assert any(pattern.search(content) for pattern in check_public_specs.FORBIDDEN)


@pytest.mark.spec("SDK-CONNECTOR-CONTROL-R009", "SDK-CONNECTOR-CONTROL-R010", "SDK-CONNECTOR-CONTROL-R011", "SDK-CONNECTOR-CONTROL-R012", "SDK-CONNECTOR-CONTROL-R013")
def test_homelab_mention_is_still_forbidden(check_public_specs):
    content = "This runs on the homelab control plane."
    assert any(pattern.search(content) for pattern in check_public_specs.FORBIDDEN)
