"""Crash-safe replacement of the two files carrying connector tool pins."""

from __future__ import annotations

import base64
import json
import os
from pathlib import Path

from agent_connector_sdk.certify.pin_journal import (
    _JOURNAL_NAME,
    _PinTransactionError,
    _recover_pin_transaction,
    _stage,
    _sync_directory,
    _write_journal,
)


def _commit_staged_pair(
    staged: tuple[Path, Path], *, manifest: Path, fingerprints: Path, journal: Path
) -> None:
    os.replace(staged[0], fingerprints)
    _sync_directory(fingerprints.parent)
    os.replace(staged[1], manifest)
    _sync_directory(manifest.parent)
    journal.unlink()
    _sync_directory(journal.parent)


def _stage_pair(
    manifest: Path, fingerprints: Path, *, manifest_text: str, fingerprints_text: str
) -> tuple[Path, Path]:
    fingerprints_stage = _stage(fingerprints, fingerprints_text.encode("utf-8"))
    try:
        manifest_stage = _stage(manifest, manifest_text.encode("utf-8"))
    except BaseException:
        fingerprints_stage.unlink(missing_ok=True)
        raise
    return fingerprints_stage, manifest_stage


def _prepare_pair(
    manifest: Path, fingerprints: Path, *, manifest_text: str, fingerprints_text: str
) -> tuple[Path, Path]:
    try:
        return _stage_pair(
            manifest,
            fingerprints,
            manifest_text=manifest_text,
            fingerprints_text=fingerprints_text,
        )
    except OSError as exc:
        raise _PinTransactionError("pin transaction preparation failed") from exc


def _rollback_failed_commit(
    manifest: Path, fingerprints: Path, failure: OSError
) -> None:
    try:
        _recover_pin_transaction(manifest, fingerprints)
    except _PinTransactionError as recovery:
        raise _PinTransactionError(
            "pin transaction failed and requires recovery"
        ) from recovery
    raise _PinTransactionError(
        "pin transaction failed and was rolled back"
    ) from failure


def _replace_pin_pair(
    manifest: Path,
    fingerprints: Path,
    *,
    manifest_text: str,
    fingerprints_text: str,
) -> None:
    """Replace both files, rolling back or journaling any interrupted commit."""
    _recover_pin_transaction(manifest, fingerprints)
    journal = manifest.with_name(_JOURNAL_NAME)
    document = {
        "version": 1,
        "manifest": base64.b64encode(manifest.read_bytes()).decode("ascii"),
        "fingerprints": base64.b64encode(fingerprints.read_bytes()).decode("ascii")
        if fingerprints.exists()
        else None,
    }
    journal_payload = (json.dumps(document, sort_keys=True) + "\n").encode("utf-8")
    staged = _prepare_pair(
        manifest,
        fingerprints,
        manifest_text=manifest_text,
        fingerprints_text=fingerprints_text,
    )
    try:
        _write_journal(journal, journal_payload)
        _commit_staged_pair(
            staged,
            manifest=manifest,
            fingerprints=fingerprints,
            journal=journal,
        )
    except OSError as exc:
        _rollback_failed_commit(manifest, fingerprints, exc)
    finally:
        for path in staged:
            path.unlink(missing_ok=True)
