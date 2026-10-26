# `agent-connector-sdk` compatibility release

This metadata-only distribution forwards existing `agent-connector-sdk`
installations to the renamed [`scion-sdk`](https://pypi.org/project/scion-sdk/)
distribution at the same version. It contains no Python modules, resources,
native binaries, or console scripts. New installations should use
`scion-sdk` directly.

## Upgrading an existing installation

The old `agent-connector-sdk` distribution owned the `agent_connector_sdk/`
implementation package. The compatibility distribution is metadata-only, while
`scion-sdk` owns that package. A normal in-place upgrade is unsafe. Pip may
install the new payload, then remove it while uninstalling the old distribution.
`pip check` may still pass because both distributions' metadata remains.

Do not use `python -m pip install --upgrade agent-connector-sdk` alone for an
existing payload-owning installation.

Set `VERSION` to the target release. For an environment that still has the old
payload, remove that owner before installing the target and its forwarder:

```bash
VERSION=0.5.7
python -m pip uninstall -y agent-connector-sdk
python -m pip install "scion-sdk==$VERSION" "agent-connector-sdk==$VERSION"
```

If the alias upgrade already removed the package, repair the environment.
Install the alias, then force-reinstall the target payload:

```bash
VERSION=0.5.7
python -m pip install --upgrade "agent-connector-sdk==$VERSION"
python -m pip install --force-reinstall --no-deps "scion-sdk==$VERSION"
```

After either procedure, run the checks below. They prove that Scion owns the
payload and that the alias owns no files. They also confirm the ontology
resource, console entry points, and dependency metadata.

```bash
python - <<'PY'
from importlib import metadata, resources
import shutil
import agent_connector_sdk

target = metadata.distribution("scion-sdk")
alias = metadata.distribution("agent-connector-sdk")
target_files = {str(path) for path in target.files or ()}
alias_files = {str(path) for path in alias.files or ()}
assert any(path.startswith("agent_connector_sdk/") for path in target_files)
assert not any(path.startswith("agent_connector_sdk/") for path in alias_files)
assert resources.files("agent_connector_sdk").joinpath(
    "ontology/access_contract.ttl"
).is_file()
entry_points = {
    (entry_point.group, entry_point.name)
    for entry_point in metadata.entry_points()
    if entry_point.dist and entry_point.dist.metadata["Name"] == "scion-sdk"
}
assert ("console_scripts", "connector-sync") in entry_points
assert ("console_scripts", "connector-certify") in entry_points
assert shutil.which("connector-sync")
assert shutil.which("connector-certify")
PY
python -m pip check
```
