"""Fail-closed checks for the pinned EG source and official release wheel."""

from __future__ import annotations

import hashlib
import json
import zipfile
from email.parser import Parser
from pathlib import Path
from urllib.parse import unquote, urlsplit

EXPECTED = {
    "distribution": "medulla",
    "version": "2.27.10",
    "source_remote": "https://github.com/Knuckles-Team/medulla.git",
    "source_revision": "31d612a2c80f4dc28767c9ba5072239bea3c070a",
    "release_tag": "v2.27.10",
    "wheel_filename": "medulla-2.27.10-cp39-abi3-manylinux_2_28_x86_64.whl",
    "wheel_asset_id": "pypi:medulla==2.27.10",
    "wheel_url": "https://files.pythonhosted.org/packages/f1/12/38d3ee0babbc94cdd18b90db6a7f6fc0e54b360317fb3bbf14f2bde8b4dd/medulla-2.27.10-cp39-abi3-manylinux_2_28_x86_64.whl",
    "wheel_sha256": "d6b82ad4d94a4813d24c34cb312408a1587d484fafc35e5665f36c26a5d82090",
    "native_member": "epistemic_graph/numeric.abi3.so",
}


class ProvenanceError(RuntimeError):
    """The release artifact cannot be tied to the pinned EG source."""


def read_manifest(path: Path) -> dict[str, str]:
    try:
        manifest = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ProvenanceError(f"cannot read EG release manifest: {exc}") from exc
    if manifest != EXPECTED:
        raise ProvenanceError(
            "EG release manifest differs from the reviewed release pin"
        )
    return manifest


def require_source_revision(revision: str, manifest_path: Path) -> dict[str, str]:
    manifest = read_manifest(manifest_path)
    if revision != manifest["source_revision"]:
        raise ProvenanceError(
            "EG source revision does not match the release wheel commit"
        )
    return manifest


def verify_wheel_archive(wheel: Path, manifest_path: Path) -> dict[str, str]:
    manifest = read_manifest(manifest_path)
    if wheel.name != manifest["wheel_filename"]:
        raise ProvenanceError(
            "EG wheel filename does not match the pinned release asset"
        )
    digest = hashlib.sha256(wheel.read_bytes()).hexdigest()
    if digest != manifest["wheel_sha256"]:
        raise ProvenanceError(
            "EG wheel SHA-256 does not match the pinned release asset"
        )
    try:
        with zipfile.ZipFile(wheel) as archive:
            names = set(archive.namelist())
            metadata_names = [
                name
                for name in names
                if name.endswith(".dist-info/METADATA") and name.startswith("medulla-")
            ]
            wheel_names = [
                name
                for name in names
                if name.endswith(".dist-info/WHEEL") and name.startswith("medulla-")
            ]
            if len(metadata_names) != 1 or len(wheel_names) != 1:
                raise ProvenanceError("EG wheel has ambiguous distribution metadata")
            metadata = Parser().parsestr(
                archive.read(metadata_names[0]).decode("utf-8")
            )
            wheel_tags = [
                line.partition(":")[2].strip()
                for line in archive.read(wheel_names[0]).decode("utf-8").splitlines()
                if line.startswith("Tag:")
            ]
    except (OSError, zipfile.BadZipFile, UnicodeError) as exc:
        raise ProvenanceError(f"cannot inspect EG release wheel: {exc}") from exc
    if metadata.get("Name", "").lower().replace("_", "-") != manifest["distribution"]:
        raise ProvenanceError("EG wheel metadata has the wrong distribution name")
    if metadata.get("Version") != manifest["version"]:
        raise ProvenanceError(
            "EG wheel metadata version differs from the source release"
        )
    if wheel_tags != ["cp39-abi3-manylinux_2_28_x86_64"]:
        raise ProvenanceError("EG wheel tag differs from the pinned release asset")
    if manifest["native_member"] not in names:
        raise ProvenanceError("EG wheel is missing its bundled native engine")
    return manifest


def verify_installed_distribution(
    distribution: object, manifest_path: Path
) -> dict[str, str]:
    manifest = read_manifest(manifest_path)
    if getattr(distribution, "version", None) != manifest["version"]:
        raise ProvenanceError(
            "installed EG version differs from the pinned release wheel"
        )
    direct_text = distribution.read_text("direct_url.json")
    try:
        direct = json.loads(direct_text or "")
    except json.JSONDecodeError as exc:
        raise ProvenanceError(
            "installed EG has no valid PEP 610 wheel receipt"
        ) from exc
    url = str(direct.get("url", ""))
    filename = Path(unquote(urlsplit(url).path)).name
    if filename != manifest["wheel_filename"]:
        raise ProvenanceError(
            "installed EG wheel filename differs from the pinned asset"
        )
    archive_info = direct.get("archive_info", {})
    hashes = archive_info.get("hashes", {}) if isinstance(archive_info, dict) else {}
    receipt_hash = hashes.get("sha256")
    if receipt_hash and receipt_hash != manifest["wheel_sha256"]:
        raise ProvenanceError("installed EG wheel receipt has a mismatched SHA-256")
    parsed_url = urlsplit(url)
    if parsed_url.scheme != "file":
        raise ProvenanceError(
            "installed EG wheel has no verifiable local artifact receipt"
        )
    wheel = Path(unquote(parsed_url.path))
    verify_wheel_archive(wheel, manifest_path)
    _verify_installed_wheel_files(distribution, wheel, manifest)
    native = Path(str(distribution.locate_file(manifest["native_member"])))
    if not native.is_file():
        raise ProvenanceError(
            "installed EG release wheel lacks its bundled native engine"
        )
    return manifest


def _verify_installed_wheel_files(
    distribution: object, wheel: Path, manifest: dict[str, str]
) -> None:
    try:
        with zipfile.ZipFile(wheel) as archive:
            members = [
                name
                for name in archive.namelist()
                if name.startswith("epistemic_graph/")
                or (
                    name.startswith(f"medulla-{manifest['version']}.dist-info/")
                    and not name.endswith("/RECORD")
                )
            ]
            for name in members:
                installed = Path(str(distribution.locate_file(name)))
                if not installed.is_file() or installed.read_bytes() != archive.read(
                    name
                ):
                    raise ProvenanceError(
                        "installed EG file differs from the hash-verified release wheel"
                    )
    except (OSError, zipfile.BadZipFile) as exc:
        raise ProvenanceError(f"cannot verify installed EG wheel files: {exc}") from exc
