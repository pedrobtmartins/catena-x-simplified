"""Trusts a company's private CA certificates next to the public ones.

``requests`` (and the Tractus-X SDK on top of it) only trusts certifi's public CAs, so an EDC,
DTR or IdP whose HTTPS certificate is signed by an internal root fails with
CERTIFICATE_VERIFY_FAILED. Drop the root (PEM or DER, ``*.crt``/``*.pem``/``*.cer``) into the
directory of ``CXS_EXTRA_CA_DIR``: at startup the app writes certifi's bundle plus those
certificates to one file and points ``REQUESTS_CA_BUNDLE`` and ``SSL_CERT_FILE`` at it.
"""

from __future__ import annotations

import logging
import os
import tempfile
from pathlib import Path

import certifi
from cryptography import x509
from cryptography.hazmat.primitives import serialization

log = logging.getLogger(__name__)

CERTIFICATE_SUFFIXES = (".crt", ".pem", ".cer")
BUNDLE_VARIABLES = ("REQUESTS_CA_BUNDLE", "SSL_CERT_FILE")
PEM_MARKER = "-----BEGIN CERTIFICATE-----"


def _read_certificate(path: Path) -> str | None:
    """The certificates in ``path`` (one or a PEM chain, or one DER) as PEM; None if invalid."""
    data = path.read_bytes()
    try:
        if PEM_MARKER.encode() in data:
            certificates = x509.load_pem_x509_certificates(data)
        else:
            certificates = [x509.load_der_x509_certificate(data)]
    except ValueError:
        return None
    return "".join(c.public_bytes(serialization.Encoding.PEM).decode("ascii") for c in certificates)


def extra_certificates(directory: Path) -> list[tuple[Path, str]]:
    """The certificates in ``directory`` (sorted by name), as PEM. Hidden entries (a mounted
    ConfigMap's ``..data``) and other files are ignored."""
    found = []
    for path in sorted(directory.iterdir()):
        if path.name.startswith(".") or not path.is_file():
            continue
        if path.suffix.lower() not in CERTIFICATE_SUFFIXES:
            continue
        pem = _read_certificate(path)
        if pem is None:
            log.warning("Ignoring %s: neither a PEM nor a DER certificate", path)
            continue
        found.append((path, pem))
    return found


def install_extra_ca_certificates(
    directory: str | None, bundle_dir: str | None = None
) -> Path | None:
    """Writes certifi's bundle plus the certificates in ``directory`` to one file and sets
    ``REQUESTS_CA_BUNDLE`` and ``SSL_CERT_FILE`` to it. Returns the bundle, or None when there
    is nothing to add or the variables are already set (an explicit bundle wins)."""
    if not directory or not Path(directory).is_dir():
        return None
    certificates = extra_certificates(Path(directory))
    if not certificates:
        return None
    explicit = [name for name in BUNDLE_VARIABLES if os.environ.get(name)]
    if explicit:
        log.warning(
            "Not adding the certificates in %s: %s already set",
            directory,
            " and ".join(explicit),
        )
        return None
    bundle = Path(bundle_dir or tempfile.gettempdir()) / "catenax-simplified-ca-bundle.pem"
    parts = [Path(certifi.where()).read_text(encoding="ascii").rstrip() + "\n"]
    parts += [f"# {path.name}\n{pem}" for path, pem in certificates]
    bundle.write_text("\n".join(parts), encoding="ascii")
    for name in BUNDLE_VARIABLES:
        os.environ[name] = str(bundle)
    log.info(
        "Trusting %d extra CA certificate(s) from %s: %s",
        len(certificates),
        directory,
        ", ".join(path.name for path, _ in certificates),
    )
    return bundle


CERTIFICATE_HINT = (
    "The server's certificate is not signed by a trusted CA. If your company's own CA issued it, "
    "put that root certificate into the directory of CXS_EXTRA_CA_DIR and restart the app "
    "(see 'Private CA certificates' in backend/README.md)."
)


def certificate_hint(error: str) -> str:
    """How to trust a private CA, when ``error`` is a certificate verification failure; else ""."""
    return CERTIFICATE_HINT if "certificate_verify_failed" in error.lower() else ""
