"""Driver resolution and bounded connections for the database connector."""

from __future__ import annotations

import importlib
from collections.abc import Callable
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlparse

from scion_sdk.credentials.resolver import CredentialResolver
from scion_sdk.privacy_reference import persistence_reference
from scion_sdk.source_connectors._universal_cells import _CellChecks
from scion_sdk.tls.errors import TransportSecurityError
from scion_sdk.tls.resolve import resolve_tls_profile

_DRIVER_MODULES = {
    "sqlite": "sqlite3",
    "postgresql": "psycopg",
    "mysql": "pymysql",
    "mssql": "pyodbc",
    "oracle": "oracledb",
    "mongodb": "pymongo",
}


class _Connections(_CellChecks):
    """Lazy driver import and bounded, TLS-governed connections."""

    dsn: str
    kind: str
    source_ref: str
    _tls_service: str | None
    _tls_profile: str | None
    _tls_profile_ref: str | None
    _tls_resolver: CredentialResolver | None

    def _object_id(self, object_kind: str, *parts: object) -> str:
        framed = "\x00".join(str(part) for part in parts)
        reference = persistence_reference(
            "schema_object",
            framed,
            namespace=self.source_ref,
        )
        return f"{object_kind}:{reference}"

    def _driver(self) -> Any:
        """Lazily import and return the client module for this ``kind``.

        Each import is guarded so importing this module never requires any
        database driver. A missing driver yields a clear ``RuntimeError``.
        """
        module = _DRIVER_MODULES.get(self.kind)
        if module is None:
            raise RuntimeError("database driver is unavailable")
        try:
            return importlib.import_module(module)
        except ImportError as exc:
            raise RuntimeError("database driver is unavailable") from exc

    def _sqlite_path(self) -> str:
        """Resolve the on-disk sqlite path from the DSN."""
        if self.dsn in {":memory:", "sqlite:///:memory:"}:
            return ":memory:"
        if self.dsn.startswith("sqlite:///"):
            path = unquote(self.dsn.removeprefix("sqlite:///"))
            if not path:
                raise ValueError("sqlite connection value is invalid")
            return path
        parsed = urlparse(self.dsn)
        if parsed.scheme == "file":
            path = unquote(parsed.path or parsed.netloc)
            if not path:
                raise ValueError("sqlite connection value is invalid")
            return path
        return self.dsn

    def _connect(self) -> Any:
        """Open a bounded connection appropriate for ``kind``."""
        if self.kind == "sqlite":
            return self._connect_sqlite()
        return self._connect_networked()

    def _connect_sqlite(self) -> Any:
        """Open a bounded sqlite connection (read-only, symlink-refusing)."""
        driver = self._driver()
        path = self._sqlite_path()
        if path == ":memory:":
            connection = driver.connect(path, timeout=10.0)
        else:
            connection = driver.connect(
                f"{self._sqlite_resolved_uri(path)}?mode=ro",
                uri=True,
                timeout=10.0,
            )
        connection.execute("PRAGMA query_only=ON")
        connection.execute("PRAGMA busy_timeout=10000")
        return connection

    @staticmethod
    def _sqlite_resolved_uri(path: str) -> str:
        """Resolve ``path`` to a file URI, refusing symlinks and non-files."""
        candidate = Path(path)
        if candidate.is_symlink():
            raise RuntimeError("sqlite source is unavailable")
        try:
            resolved = candidate.resolve(strict=True)
        except (OSError, RuntimeError) as exc:
            raise RuntimeError("sqlite source is unavailable") from exc
        if not resolved.is_file():
            raise RuntimeError("sqlite source is unavailable")
        return resolved.as_uri()

    def _connect_networked(self) -> Any:
        """Open a TLS-governed connection for every non-sqlite ``kind``."""
        driver = self._driver()

        service = self._tls_service or {
            "postgresql": "postgres",
            "mongodb": "mongodb",
        }.get(self.kind, f"database-{self.kind}")
        trust = resolve_tls_profile(
            service,
            profile_name=self._tls_profile,
            profile_ref=self._tls_profile_ref,
            resolver=self._tls_resolver,
        )
        connectors: dict[str, Callable[[Any, Any], Any]] = {
            "postgresql": lambda d, t: d.connect(self.dsn, **t.psycopg_kwargs()),
            "mysql": self._connect_mysql,
            "mssql": self._connect_mssql,
            "oracle": self._connect_oracle,
            "mongodb": lambda d, t: d.MongoClient(
                self.dsn,
                serverSelectionTimeoutMS=10_000,
                connectTimeoutMS=10_000,
                socketTimeoutMS=30_000,
                **t.pymongo_kwargs(),
            ),
        }
        connector = connectors.get(self.kind)
        try:
            if connector is None:
                raise RuntimeError("database connection kind is unsupported")
            return connector(driver, trust)
        finally:
            trust.cleanup()

    def _connect_mysql(self, driver: Any, trust: Any) -> Any:
        if trust.proxy_url:
            raise TransportSecurityError("mysql_tls_proxy_unsupported")
        parsed = urlparse(self.dsn)
        if not parsed.hostname:
            raise ValueError("MySQL connection host is required")
        return driver.connect(
            host=parsed.hostname,
            port=parsed.port or 3306,
            user=parsed.username,
            password=parsed.password,
            database=(parsed.path or "").lstrip("/") or None,
            ssl=trust.ssl_context,
        )

    def _connect_mssql(self, driver: Any, trust: Any) -> Any:
        if (
            trust.proxy_url
            or trust.ca_bundle_path is not None
            or trust.ca_directory is not None
            or trust.client_cert_path is not None
        ):
            raise TransportSecurityError("mssql_tls_profile_unsupported")
        connection = self.dsn.rstrip(";")
        return driver.connect(f"{connection};Encrypt=yes;TrustServerCertificate=no")

    def _connect_oracle(self, driver: Any, trust: Any) -> Any:
        if trust.proxy_url:
            raise TransportSecurityError("oracle_tls_proxy_unsupported")
        return driver.connect(self.dsn, ssl_context=trust.ssl_context)
