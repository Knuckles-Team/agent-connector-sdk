"""Durable journal primitives for connector pin transactions."""

from __future__ import annotations

import base64
import json
import os
import tempfile
from pathlib import Path

_JOURNAL_NAME = ".connector-certify-transaction.json"


class _PinTransactionError(RuntimeError):
    """A pin transaction could not prepare, commit or recover safely."""


def _sync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _stage(path: Path, payload: bytes) -> Path:
    mode = path.stat().st_mode & 0o777 if path.exists() else 0o644
    with tempfile.NamedTemporaryFile(
        dir=path.parent, prefix=f".{path.name}.certify-", delete=False
    ) as stream:
        stream.write(payload)
        stream.flush()
        os.fsync(stream.fileno())
        staging = Path(stream.name)
    staging.chmod(mode)
    return staging


def _write_journal(path: Path, payload: bytes) -> None:
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    stream = os.fdopen(descriptor, "wb")
    try:
        stream.write(payload)
        stream.flush()
        os.fsync(stream.fileno())
    except BaseException:
        path.unlink(missing_ok=True)
        raise
    finally:
        stream.close()
    _sync_directory(path.parent)


def _decoded_old(document: object, key: str) -> bytes | None:
    if not isinstance(document, dict) or document.get("version") != 1:
        raise _PinTransactionError("pin transaction journal is malformed")
    encoded = document.get(key)
    if encoded is None:
        return None
    if not isinstance(encoded, str):
        raise _PinTransactionError("pin transaction journal is malformed")
    try:
        return base64.b64decode(encoded, validate=True)
    except ValueError as exc:
        raise _PinTransactionError("pin transaction journal is malformed") from exc


def _restore_target(target: Path, payload: bytes | None) -> None:
    if payload is None:
        target.unlink(missing_ok=True)
        return
    staging = _stage(target, payload)
    try:
        os.replace(staging, target)
    finally:
        staging.unlink(missing_ok=True)


def _restore_pair(
    document: object, *, manifest: Path, fingerprints: Path, journal: Path
) -> None:
    old = (
        (fingerprints, _decoded_old(document, "fingerprints")),
        (manifest, _decoded_old(document, "manifest")),
    )
    for target, payload in old:
        _restore_target(target, payload)
        _sync_directory(target.parent)
    journal.unlink()
    _sync_directory(journal.parent)


def _recover_pin_transaction(manifest: Path, fingerprints: Path) -> bool:
    """Restore the old consistent pair when an interrupted journal exists."""
    journal = manifest.with_name(_JOURNAL_NAME)
    if not journal.exists():
        return False
    try:
        document = json.loads(journal.read_bytes())
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise _PinTransactionError("pin transaction recovery failed") from exc
    try:
        _restore_pair(
            document,
            manifest=manifest,
            fingerprints=fingerprints,
            journal=journal,
        )
    except OSError as exc:
        raise _PinTransactionError("pin transaction recovery failed") from exc
    return True
