"""Relay-side hardening: sender binding, header From, whitelist width, archive, pruning."""

from __future__ import annotations

import datetime as dt

import pytest
from pydantic import ValidationError

from common.db import session_scope
from common.models import (
    AuthorisedSender,
    IpWhitelistEntry,
    MailQueue,
    MailStatus,
    SmtpAccount,
)
from conftest import run


def _add(*rows):
    async def _go():
        async with session_scope() as s:
            s.add_all(rows)

    run(_go())


def test_account_bound_to_its_senders():
    from relay.auth import client_may_use_sender

    _add(
        SmtpAccount(username="printer-a", password_hash="x", allowed_senders="printer-a@kunde.de"),
        SmtpAccount(username="legacy", password_hash="x", allowed_senders=""),
    )
    assert run(client_may_use_sender("printer-a", "10.0.0.21", "Printer-A@kunde.de"))
    assert not run(client_may_use_sender("printer-a", "10.0.0.21", "nas@kunde.de"))
    assert run(client_may_use_sender("legacy", "10.0.0.9", "nas@kunde.de"))
    assert not run(client_may_use_sender("ghost", "10.0.0.9", "nas@kunde.de"))


def test_whitelist_entry_bound_to_its_senders():
    from relay.auth import client_may_use_sender

    _add(
        IpWhitelistEntry(cidr="192.168.20.5/32", allowed_senders="usv@kunde.de"),
        IpWhitelistEntry(cidr="192.168.20.6/32", allowed_senders="", is_enabled=False),
    )
    assert run(client_may_use_sender(None, "192.168.20.5", "usv@kunde.de"))
    assert not run(client_may_use_sender(None, "192.168.20.5", "printer-a@kunde.de"))
    assert not run(client_may_use_sender(None, "192.168.20.6", "usv@kunde.de"))


def test_handle_mail_refuses_foreign_sender():
    from types import SimpleNamespace

    from aiosmtpd.smtp import Envelope

    from relay.smtp_handler import RelayHandler

    _add(
        AuthorisedSender(address="printer-a@kunde.de"),
        AuthorisedSender(address="nas@kunde.de"),
        SmtpAccount(username="printer-a", password_hash="x", allowed_senders="printer-a@kunde.de"),
    )
    session = SimpleNamespace(peer=("10.0.0.21", 1234), auth_data="printer-a")
    reply = run(RelayHandler(max_message_size=1000).handle_MAIL(None, session, Envelope(), "nas@kunde.de", []))
    assert reply.startswith("550")


@pytest.mark.parametrize(
    "headers,ok",
    [
        ("From: Scanner <printer-a@kunde.de>", True),
        ("From: PRINTER-A@kunde.de", True),
        ("From: Chef <chef@kunde.de>", False),
        ("From: a@kunde.de, printer-a@kunde.de", False),
        ("Subject: no from", False),
    ],
)
def test_header_from_must_match_envelope(headers, ok):
    from relay.smtp_handler import header_from_matches

    raw = f"{headers}\r\nTo: x@y.de\r\n\r\nbody\r\n".encode()
    assert header_from_matches(raw, "printer-a@kunde.de") is ok


@pytest.mark.parametrize("cidr,ok", [("192.168.10.21", True), ("192.168.10.0/24", True), ("192.168.0.0/16", False), ("0.0.0.0/0", False), ("fd00::/48", False)])
def test_whitelist_rejects_wide_networks(cidr, ok):
    from ui.forms import CidrIn

    if ok:
        CidrIn(cidr=cidr)
    else:
        with pytest.raises(ValidationError):
            CidrIn(cidr=cidr)


def test_archive_can_be_disabled(monkeypatch):
    from common import archive

    monkeypatch.setenv("ARCHIVE_ENABLED", "0")
    assert archive.write_eml(message_id=1, subject="x", raw_mime=b"x") is None
    monkeypatch.setenv("ARCHIVE_ENABLED", "1")
    assert archive.write_eml(message_id=1, subject="x", raw_mime=b"x").exists()


def test_prune_removes_old_dead_rows():
    from relay.queue_manager import prune_sent

    old = dt.datetime.utcnow() - dt.timedelta(days=40)

    def row(status, when):
        return MailQueue(
            sender="a@kunde.de", recipients_json='["b@kunde.de"]', raw_mime_b64="eA==",
            status=status, timestamp_received=when,
        )

    _add(row(MailStatus.DEAD, old), row(MailStatus.SENT, old), row(MailStatus.DEAD, dt.datetime.utcnow()))
    assert run(prune_sent(30)) == 2
