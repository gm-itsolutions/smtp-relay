"""TLS for the SMTP listeners (always on).

Certificate source, in order:
  1. SMTP_TLS_CERT / SMTP_TLS_KEY (PEM paths) — your own certificate.
  2. <SMTP_TLS_DIR>/cert.pem + key.pem — generated on first start
     (self-signed, RSA 2048, CN/SAN = SMTP_TLS_HOSTNAME or the host name).

SMTP_TLS_MIN_VERSION: "1.2" (default) or "1.0"/"1.1" for legacy devices
that cannot do TLS 1.2 — lowers the OpenSSL security level, use only when a
device needs it.
"""

from __future__ import annotations

import datetime as _dt
import logging
import os
import socket
import ssl
from pathlib import Path

_log = logging.getLogger("relay.tls")

_MIN_VERSIONS = {
    "1.0": ssl.TLSVersion.TLSv1,
    "1.1": ssl.TLSVersion.TLSv1_1,
    "1.2": ssl.TLSVersion.TLSv1_2,
    "1.3": ssl.TLSVersion.TLSv1_3,
}


def _generate(cert_path: Path, key_path: Path, hostname: str) -> None:
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID

    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    now = _dt.datetime.now(_dt.timezone.utc)
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, hostname)])
    cert = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - _dt.timedelta(minutes=5))
        .not_valid_after(now + _dt.timedelta(days=5 * 365))
        .add_extension(x509.SubjectAlternativeName([x509.DNSName(hostname)]), critical=False)
        .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
        .add_extension(x509.ExtendedKeyUsage([ExtendedKeyUsageOID.SERVER_AUTH]), critical=False)
        .sign(key, hashes.SHA256())
    )
    cert_path.parent.mkdir(parents=True, exist_ok=True)
    key_path.write_bytes(
        key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        )
    )
    os.chmod(key_path, 0o600)
    cert_path.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    _log.info("Generated self-signed SMTP TLS certificate for %s at %s", hostname, cert_path)


def server_context() -> ssl.SSLContext:
    cert = os.environ.get("SMTP_TLS_CERT", "").strip()
    key = os.environ.get("SMTP_TLS_KEY", "").strip()
    if bool(cert) != bool(key):
        raise RuntimeError("Set both SMTP_TLS_CERT and SMTP_TLS_KEY, or neither.")
    if not cert:
        tls_dir = Path(os.environ.get("SMTP_TLS_DIR", "/data/smtp-tls"))
        cert_path, key_path = tls_dir / "cert.pem", tls_dir / "key.pem"
        if not (cert_path.exists() and key_path.exists()):
            hostname = os.environ.get("SMTP_TLS_HOSTNAME", "").strip() or socket.gethostname()
            _generate(cert_path, key_path, hostname)
        cert, key = str(cert_path), str(key_path)

    ctx = ssl.create_default_context(ssl.Purpose.CLIENT_AUTH)
    min_version = os.environ.get("SMTP_TLS_MIN_VERSION", "1.2").strip()
    if min_version not in _MIN_VERSIONS:
        raise RuntimeError(f"SMTP_TLS_MIN_VERSION must be one of {sorted(_MIN_VERSIONS)}")
    if min_version in ("1.0", "1.1"):
        from common.netutils import public_mode

        if public_mode():
            raise RuntimeError("SMTP_TLS_MIN_VERSION below 1.2 is not allowed with SMTP_PUBLIC_MODE=1.")
        # ponytail: legacy knob for old printers/UPS cards; per-listener, not per-device.
        ctx.set_ciphers("DEFAULT:@SECLEVEL=0")
    ctx.minimum_version = _MIN_VERSIONS[min_version]
    ctx.load_cert_chain(cert, key)
    return ctx
