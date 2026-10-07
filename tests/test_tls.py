"""TLS listeners: certificate bootstrap, STARTTLS + SMTPS, AUTH only over TLS."""

from __future__ import annotations

import smtplib
import socket
import ssl

import pytest

from common.db import session_scope
from common.models import AuthorisedSender, IpWhitelistEntry, Settings, SmtpAccount
from common.passwords import hash_password
from conftest import run


def test_certificate_generated_once(tmp_path, monkeypatch):
    from relay.tls import server_context

    monkeypatch.setenv("SMTP_TLS_DIR", str(tmp_path / "tls"))
    monkeypatch.setenv("SMTP_TLS_HOSTNAME", "relay.kunde.local")
    server_context()
    first = (tmp_path / "tls" / "cert.pem").read_bytes()
    server_context()
    assert (tmp_path / "tls" / "cert.pem").read_bytes() == first
    assert oct((tmp_path / "tls" / "key.pem").stat().st_mode & 0o777) == "0o600"


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture()
def listeners(tmp_path, monkeypatch):
    from relay.main import build_listeners
    from relay.smtp_handler import RelayAuthenticator, RelayHandler
    from relay.tls import server_context

    monkeypatch.setenv("SMTP_TLS_DIR", str(tmp_path / "tls"))
    monkeypatch.setenv("SMTP_TLS_HOSTNAME", "relay.kunde.de")

    async def _seed():
        async with session_scope() as s:
            st = await s.get(Settings, 1)
            st.smtp_whitelist_enabled = True
            s.add_all([
                AuthorisedSender(address="printer-a@kunde.de"),
                SmtpAccount(username="printer-a", password_hash=hash_password("pw-123456789012"),
                            allowed_senders="printer-a@kunde.de"),
                IpWhitelistEntry(cidr="127.0.0.1/32", allowed_senders="printer-a@kunde.de"),
            ])

    run(_seed())
    ports = {"hostname": "127.0.0.1", "port": _free_port(), "smtps_port": _free_port(), "max_size": 100000}
    plain, smtps = build_listeners(RelayHandler(max_message_size=100000), RelayAuthenticator(), ports, server_context())
    plain.start()
    smtps.start()
    yield ports
    plain.stop()
    smtps.stop()


def _client_ctx():
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    return ctx


def test_auth_refused_without_tls(listeners):
    with smtplib.SMTP("127.0.0.1", listeners["port"]) as c:
        c.ehlo()
        assert "starttls" in c.esmtp_features
        assert "auth" not in c.esmtp_features
        code, _ = c.docmd("AUTH", "PLAIN AHByaW50ZXItYQBwdy0xMjM0NTY3ODkwMTI=")
        assert code == 538


def test_auth_after_starttls(listeners):
    with smtplib.SMTP("127.0.0.1", listeners["port"]) as c:
        c.starttls(context=_client_ctx())
        c.login("printer-a", "pw-123456789012")
        assert c.mail("printer-a@kunde.de")[0] == 250


def test_auth_over_smtps(listeners):
    with smtplib.SMTP_SSL("127.0.0.1", listeners["smtps_port"], context=_client_ctx()) as c:
        c.login("printer-a", "pw-123456789012")
        assert c.mail("printer-a@kunde.de")[0] == 250


def test_whitelist_plain_refused_tls_accepted(listeners):
    with smtplib.SMTP("127.0.0.1", listeners["port"]) as c:
        c.ehlo()
        assert c.mail("printer-a@kunde.de")[0] == 530
    with smtplib.SMTP("127.0.0.1", listeners["port"]) as c:
        c.starttls(context=_client_ctx())
        c.ehlo()
        assert c.mail("printer-a@kunde.de")[0] == 250


def test_greeting_has_no_software_banner(listeners):
    with smtplib.SMTP("127.0.0.1", listeners["port"]) as c:
        code, msg = c.ehlo()
        assert code == 250
    sock = socket.create_connection(("127.0.0.1", listeners["port"]))
    greeting = sock.recv(200).decode()
    sock.close()
    assert greeting.startswith("220 relay.kunde.de ESMTP")
    assert "Python" not in greeting


def test_connection_limit_per_ip(listeners, monkeypatch):
    from relay.smtp_handler import CaseInsensitiveAuthSMTP

    monkeypatch.setattr(CaseInsensitiveAuthSMTP, "max_connections_per_ip", 2)
    held = [smtplib.SMTP("127.0.0.1", listeners["port"]) for _ in range(2)]
    with pytest.raises(smtplib.SMTPConnectError) as exc:
        smtplib.SMTP("127.0.0.1", listeners["port"])
    assert exc.value.smtp_code == 421
    held.pop().quit()
    import time
    time.sleep(0.3)  # let the server register the closed connection
    with smtplib.SMTP("127.0.0.1", listeners["port"]) as c:
        assert c.noop()[0] == 250
    for c in held:
        c.quit()
