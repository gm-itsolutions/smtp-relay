"""Shared helpers for UI routers.

Keeping per-router code lean:

- `audit_config_change` — used by every config mutation endpoint to
  write a uniform audit record without repeating the same boilerplate.
- `recipients_by_field` — splits a message's recipients into To/Cc/Bcc
  for the queue and archive detail pages.
"""

from __future__ import annotations

from email.parser import BytesHeaderParser
from email.policy import compat32
from email.utils import getaddresses
from typing import Any

from fastapi import Request
from sqlalchemy.ext.asyncio import AsyncSession

from common.audit import record as audit_record
from common.models import AuditEventType, AuditOutcome

from ..security import SessionPayload


async def audit_config_change(
    s: AsyncSession,
    session: SessionPayload,
    request: Request,
    details: dict[str, Any],
) -> None:
    await audit_record(
        s,
        event_type=AuditEventType.CONFIG_CHANGE,
        outcome=AuditOutcome.SUCCESS,
        username=session.username,
        source_ip=request.client.host if request.client else None,
        details=details,
    )


def recipients_by_field(
    raw_mime: bytes, envelope: list[str] | None = None
) -> dict[str, list[str]] | None:
    """Group a message's recipients as {"to": [...], "cc": [...], "bcc": [...]}.

    To and Cc come from the headers. Bcc is the Bcc header plus every
    envelope (RCPT TO) recipient not named in To/Cc/Bcc — the blind copies
    the relay adds as a Bcc header when it hands the message to Graph.
    Returns None if the headers cannot be parsed, so the caller can fall
    back to the flat envelope list.
    """
    try:
        msg = BytesHeaderParser(policy=compat32).parsebytes(raw_mime or b"")

        def field(name: str) -> list[str]:
            values = [str(v) for v in (msg.get_all(name) or [])]
            return [addr for _, addr in getaddresses(values) if addr]

        grouped = {"to": field("To"), "cc": field("Cc"), "bcc": field("Bcc")}
    except Exception:
        return None

    seen: set[str] = set()
    for key in ("to", "cc", "bcc"):
        unique = []
        for addr in grouped[key]:
            if addr.casefold() not in seen:
                seen.add(addr.casefold())
                unique.append(addr)
        grouped[key] = unique
    for addr in envelope or []:
        if addr.casefold() not in seen:
            seen.add(addr.casefold())
            grouped["bcc"].append(addr)
    return grouped
