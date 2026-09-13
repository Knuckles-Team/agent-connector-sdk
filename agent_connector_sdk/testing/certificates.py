"""Throwaway certificates for TLS tests: a CA and a server certificate it signs."""

from __future__ import annotations

import datetime
import ipaddress
import ssl
from dataclasses import dataclass, field
from pathlib import Path

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import NameOID

__all__ = ["CertificateSet", "issue_test_certificates"]

_CA_NAME = "agent-connector-sdk test CA"
_CA_USAGE = x509.KeyUsage(
    digital_signature=True,
    content_commitment=False,
    key_encipherment=False,
    data_encipherment=False,
    key_agreement=False,
    key_cert_sign=True,
    crl_sign=True,
    encipher_only=False,
    decipher_only=False,
)


@dataclass(frozen=True)
class CertificateSet:
    """PEM material for a test CA and a ``localhost``/``127.0.0.1`` server."""

    ca_pem: str
    server_cert_pem: str
    server_key_pem: str = field(repr=False)

    def server_context(self, directory: Path) -> ssl.SSLContext:
        """A server-side context; the PEM files are written under ``directory``."""
        cert_file, key_file = directory / "server.pem", directory / "server.key"
        cert_file.write_text(self.server_cert_pem, encoding="utf-8")
        key_file.write_text(self.server_key_pem, encoding="utf-8")
        key_file.chmod(0o600)
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        context.load_cert_chain(str(cert_file), str(key_file))
        return context


def _name(common_name: str) -> x509.Name:
    return x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, common_name)])


def _pem(value: x509.Certificate | ec.EllipticCurvePrivateKey) -> str:
    if isinstance(value, x509.Certificate):
        return value.public_bytes(serialization.Encoding.PEM).decode("ascii")
    return value.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    ).decode("ascii")


def _builder(subject: str, key: ec.EllipticCurvePrivateKey) -> x509.CertificateBuilder:
    now = datetime.datetime.now(datetime.UTC)
    return (
        x509.CertificateBuilder()
        .subject_name(_name(subject))
        .issuer_name(_name(_CA_NAME))
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - datetime.timedelta(minutes=5))
        .not_valid_after(now + datetime.timedelta(days=1))
    )


def _issue_ca(ca_key: ec.EllipticCurvePrivateKey) -> x509.Certificate:
    identifier = x509.SubjectKeyIdentifier.from_public_key(ca_key.public_key())
    return (
        _builder(_CA_NAME, ca_key)
        .add_extension(x509.BasicConstraints(ca=True, path_length=None), critical=True)
        .add_extension(_CA_USAGE, critical=True)
        .add_extension(identifier, critical=False)
        .sign(ca_key, hashes.SHA256())
    )


def _issue_server(
    server_key: ec.EllipticCurvePrivateKey, ca_key: ec.EllipticCurvePrivateKey
) -> x509.Certificate:
    names = [
        x509.DNSName("localhost"),
        x509.IPAddress(ipaddress.ip_address("127.0.0.1")),
    ]
    authority = x509.AuthorityKeyIdentifier.from_issuer_public_key(ca_key.public_key())
    return (
        _builder("localhost", server_key)
        .add_extension(x509.SubjectAlternativeName(names), critical=False)
        .add_extension(authority, critical=False)
        .sign(ca_key, hashes.SHA256())
    )


def issue_test_certificates() -> CertificateSet:
    """A fresh CA and a server certificate for ``localhost`` and ``127.0.0.1``."""
    ca_key = ec.generate_private_key(ec.SECP256R1())
    server_key = ec.generate_private_key(ec.SECP256R1())
    return CertificateSet(
        ca_pem=_pem(_issue_ca(ca_key)),
        server_cert_pem=_pem(_issue_server(server_key, ca_key)),
        server_key_pem=_pem(server_key),
    )
