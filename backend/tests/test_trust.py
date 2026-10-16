import datetime
import ipaddress
import os
import ssl
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import certifi
import pytest
import requests
import scenario
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import NameOID

from catenax_simplified.config import Settings
from catenax_simplified.dataspace.connections import ConnectionTester
from catenax_simplified.trust import (
    BUNDLE_VARIABLES,
    CERTIFICATE_HINT,
    certificate_hint,
    extra_certificates,
    install_extra_ca_certificates,
)


def _certificate(subject, issuer, public_key, signing_key, *, ca, san=None):
    now = datetime.datetime.now(datetime.UTC)
    builder = (
        x509.CertificateBuilder()
        .subject_name(x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, subject)]))
        .issuer_name(x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, issuer)]))
        .public_key(public_key)
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - datetime.timedelta(minutes=5))
        .not_valid_after(now + datetime.timedelta(days=1))
        .add_extension(x509.BasicConstraints(ca=ca, path_length=None), critical=True)
    )
    if ca:
        builder = builder.add_extension(
            x509.KeyUsage(
                digital_signature=True,
                key_cert_sign=True,
                crl_sign=True,
                content_commitment=False,
                key_encipherment=False,
                data_encipherment=False,
                key_agreement=False,
                encipher_only=False,
                decipher_only=False,
            ),
            critical=True,
        )
    if san:
        builder = builder.add_extension(x509.SubjectAlternativeName(san), critical=False)
    return builder.sign(signing_key, hashes.SHA256())


@pytest.fixture(scope="module")
def company_pki(tmp_path_factory):
    """A private root CA and a server certificate for 127.0.0.1 signed by it."""
    root = tmp_path_factory.mktemp("pki")
    ca_key = ec.generate_private_key(ec.SECP256R1())
    ca = _certificate("Company Root CA", "Company Root CA", ca_key.public_key(), ca_key, ca=True)
    server_key = ec.generate_private_key(ec.SECP256R1())
    server = _certificate(
        "127.0.0.1",
        "Company Root CA",
        server_key.public_key(),
        ca_key,
        ca=False,
        san=[x509.IPAddress(ipaddress.ip_address("127.0.0.1"))],
    )
    chain = root / "server.pem"
    chain.write_bytes(
        server.public_bytes(serialization.Encoding.PEM)
        + ca.public_bytes(serialization.Encoding.PEM)
    )
    key = root / "server.key"
    key.write_bytes(
        server_key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        )
    )
    return {"ca": ca, "chain": chain, "key": key}


@pytest.fixture(scope="module")
def https_server(company_pki):
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            body = b'{"result": []}'
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.load_cert_chain(company_pki["chain"], company_pki["key"])
    server.socket = context.wrap_socket(server.socket, server_side=True)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"https://127.0.0.1:{server.server_address[1]}"
    server.shutdown()


@pytest.fixture(autouse=True)
def _no_bundle_variables(monkeypatch):
    """install_extra_ca_certificates sets os.environ; restore it after each test."""
    for name in BUNDLE_VARIABLES:
        monkeypatch.setenv(name, "")
        monkeypatch.delenv(name)


def _ca_dir(tmp_path, company_pki, encoding=serialization.Encoding.PEM, name="company-root.crt"):
    directory = tmp_path / "ca-certificates"
    directory.mkdir()
    (directory / name).write_bytes(company_pki["ca"].public_bytes(encoding))
    return directory


def test_a_private_ca_is_trusted_after_installing_it(tmp_path, company_pki, https_server):
    with pytest.raises(requests.exceptions.SSLError):
        requests.get(https_server, timeout=5)

    bundle = install_extra_ca_certificates(
        str(_ca_dir(tmp_path, company_pki)), bundle_dir=str(tmp_path)
    )

    assert bundle is not None
    assert {os.environ[name] for name in BUNDLE_VARIABLES} == {str(bundle)}
    assert requests.get(https_server, timeout=5).json() == {"result": []}
    # The public CAs are still trusted: the bundle starts with certifi's.
    assert bundle.read_text().startswith(Path(certifi.where()).read_text().rstrip())


def test_der_certificates_are_converted(tmp_path, company_pki):
    directory = _ca_dir(tmp_path, company_pki, serialization.Encoding.DER, "root.cer")
    [(path, pem)] = extra_certificates(directory)
    assert path.name == "root.cer"
    assert pem.startswith("-----BEGIN CERTIFICATE-----")


def test_other_and_hidden_files_are_ignored(tmp_path, company_pki):
    directory = _ca_dir(tmp_path, company_pki)
    (directory / "README.md").write_text("drop certificates here")
    (directory / "broken.pem").write_text("not a certificate")
    (directory / "..data").mkdir()  # as in a mounted ConfigMap
    (directory / ".hidden.crt").write_text("ignored")
    assert [p.name for p, _ in extra_certificates(directory)] == ["company-root.crt"]


@pytest.mark.parametrize("make_dir", [False, True])
def test_nothing_happens_without_certificates(tmp_path, make_dir):
    directory = tmp_path / "ca-certificates"
    if make_dir:
        directory.mkdir()
    assert install_extra_ca_certificates(str(directory), bundle_dir=str(tmp_path)) is None
    assert install_extra_ca_certificates(None) is None
    assert not any(name in os.environ for name in BUNDLE_VARIABLES)


def test_an_explicit_bundle_wins(tmp_path, company_pki, monkeypatch):
    monkeypatch.setenv("REQUESTS_CA_BUNDLE", "/etc/ssl/my-bundle.pem")
    directory = _ca_dir(tmp_path, company_pki)
    assert install_extra_ca_certificates(str(directory), bundle_dir=str(tmp_path)) is None
    assert os.environ["REQUESTS_CA_BUNDLE"] == "/etc/ssl/my-bundle.pem"
    assert "SSL_CERT_FILE" not in os.environ


def test_the_connection_test_explains_an_untrusted_certificate(https_server):
    settings = Settings(own_bpnl=scenario.TIER1, dtr_base_url=https_server)
    [dtr] = [c for c in ConnectionTester(settings, timeout=5).run() if c.key == "dtr"]
    assert dtr.status == "failed"
    assert "is not reachable" in dtr.detail
    assert dtr.detail.endswith(CERTIFICATE_HINT)


def test_the_hint_is_only_for_certificate_failures():
    assert certificate_hint("[SSL: CERTIFICATE_VERIFY_FAILED] certificate verify failed") == (
        CERTIFICATE_HINT
    )
    assert certificate_hint("Connection refused") == ""
