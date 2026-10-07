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
    from relay.auth import client_policy_refusal as policy

    _add(
        SmtpAccount(username="printer-a", password_hash="x", allowed_senders="printer-a@kunde.de"),
        SmtpAccount(username="legacy", password_hash="x", allowed_senders=""),
    )
    assert run(policy("printer-a", "10.0.0.21", "Printer-A@kunde.de", True)) is None
    assert run(policy("printer-a", "10.0.0.21", "nas@kunde.de", True)) == "sender"
    assert run(policy("legacy", "10.0.0.9", "nas@kunde.de", True)) is None
    assert run(policy("ghost", "10.0.0.9", "nas@kunde.de", True)) == "sender"


def test_whitelist_entry_bound_to_senders_and_tls():
    from relay.auth import client_policy_refusal as policy

    _add(
        IpWhitelistEntry(cidr="192.168.20.5/32", allowed_senders="usv@kunde.de"),
        IpWhitelistEntry(cidr="192.168.20.7/32", allowed_senders="cam@kunde.de", tls_required=False),
        IpWhitelistEntry(cidr="192.168.20.6/32", allowed_senders="", is_enabled=False),
    )
    assert run(policy(None, "192.168.20.5", "usv@kunde.de", True)) is None
    assert run(policy(None, "192.168.20.5", "usv@kunde.de", False)) == "tls"
    assert run(policy(None, "192.168.20.5", "printer-a@kunde.de", True)) == "sender"
    assert run(policy(None, "192.168.20.7", "cam@kunde.de", False)) is None
    assert run(policy(None, "192.168.20.6", "usv@kunde.de", True)) == "sender"


def _mail_from(server, auth_data, ip, address):
    from types import SimpleNamespace

    from aiosmtpd.smtp import Envelope

    from relay.smtp_handler import RelayHandler

    session = SimpleNamespace(peer=(ip, 1234), auth_data=auth_data)
    return run(RelayHandler(max_message_size=1000).handle_MAIL(server, session, Envelope(), address, []))


def test_handle_mail_refuses_foreign_sender():
    _add(
        AuthorisedSender(address="printer-a@kunde.de"),
        AuthorisedSender(address="nas@kunde.de"),
        SmtpAccount(username="printer-a", password_hash="x", allowed_senders="printer-a@kunde.de"),
    )
    assert _mail_from(None, "printer-a", "10.0.0.21", "nas@kunde.de").startswith("550")


def test_handle_mail_requires_tls_for_whitelist():
    from types import SimpleNamespace

    _add(
        AuthorisedSender(address="usv@kunde.de"),
        IpWhitelistEntry(cidr="192.168.20.5/32", allowed_senders="usv@kunde.de"),
    )
    plain = SimpleNamespace(_tls_protocol=None)
    smtps = SimpleNamespace(_tls_protocol=None, implicit_tls=True)
    assert _mail_from(plain, None, "192.168.20.5", "usv@kunde.de").startswith("530")
    assert _mail_from(smtps, None, "192.168.20.5", "usv@kunde.de") == "250 OK"


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

    monkeypatch.delenv("ARCHIVE_ENABLED", raising=False)  # default: off
    assert archive.write_eml(message_id=1, subject="x", raw_mime=b"x") is None
    monkeypatch.setenv("ARCHIVE_ENABLED", "0")
    assert archive.write_eml(message_id=1, subject="x", raw_mime=b"x") is None
    monkeypatch.setenv("ARCHIVE_ENABLED", "1")
    assert archive.write_eml(message_id=1, subject="x", raw_mime=b"x").exists()


def test_retry_with_cleared_content_marks_dead_instead_of_sending_empty():
    # A SENT row with the archive disabled has its raw_mime_b64 cleared
    # (see QueueWorker._process). Requeuing such a row (e.g. a stale
    # "Retry" click) must not resend an empty message.
    from relay.queue_manager import QueueWorker

    async def _add_row():
        async with session_scope() as s:
            row = MailQueue(
                sender="a@kunde.de", recipients_json='["b@kunde.de"]',
                raw_mime_b64="", status=MailStatus.PENDING,
                timestamp_received=dt.datetime.utcnow(),
            )
            s.add(row)
            await s.flush()
            return row.id

    row_id = run(_add_row())
    run(QueueWorker()._process(row_id))

    async def _get():
        async with session_scope() as s:
            return await s.get(MailQueue, row_id)

    row = run(_get())
    assert row.status == MailStatus.DEAD
    assert "no longer available" in row.last_error


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
