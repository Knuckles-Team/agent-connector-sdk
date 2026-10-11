"""Git subprocess environment helper split out of :mod:`agent_connector_sdk.config`."""

from __future__ import annotations

import os


def _repository_git_environment() -> dict[str, str]:
    """Copy the subprocess environment without inherited repository selectors."""
    selectors = {
        "GIT_DIR",
        "GIT_COMMON_DIR",
        "GIT_WORK_TREE",
        "GIT_INDEX_FILE",
        "GIT_OBJECT_DIRECTORY",
        "GIT_ALTERNATE_OBJECT_DIRECTORIES",
        "GIT_NAMESPACE",
        "GIT_PREFIX",
    }
    return {key: value for key, value in os.environ.items() if key not in selectors}
