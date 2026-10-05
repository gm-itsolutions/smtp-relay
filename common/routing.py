"""Sender → enterprise app routing.

A Graph app registration can only send as mailboxes of its own Microsoft
365 tenant, so the sender's domain decides which enterprise app a mail
goes through:

    1. the app the domain is mapped to (`SenderDomain`), else
    2. the default app — unless `Settings.reject_unmapped_domains` is on,
       in which case the mail is refused.

The relay resolves the route at MAIL FROM (so the SMTP client gets a
clear error), stores it on the queue row, and the queue worker sends
through that app. Rows queued without a route (admin alerts, rows from
before multi-app support) are resolved here at send time.
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .models import SenderDomain, Settings, SmtpAccount, SmtpAccountApp, TenantConfig


def sender_domain(address: str | None) -> str:
    """Lowercase domain part of `address` ('' when there is none)."""
    if not address or "@" not in address:
        return ""
    return address.rsplit("@", 1)[1].strip().lower().rstrip(".")


@dataclass(slots=True)
class Route:
    app: TenantConfig | None
    # How the app was chosen: "domain" | "default"; or why there is none:
    # "unmapped" (strict mode) | "no_default".
    via: str

    @property
    def ok(self) -> bool:
        return self.app is not None


async def default_app(session: AsyncSession) -> TenantConfig | None:
    return await session.scalar(
        select(TenantConfig)
        .where(TenantConfig.is_default.is_(True))
        .order_by(TenantConfig.id)
        .limit(1)
    )


async def resolve_route(session: AsyncSession, sender: str | None) -> Route:
    domain = sender_domain(sender)
    if domain:
        app = await session.scalar(
            select(TenantConfig)
            .join(SenderDomain, SenderDomain.tenant_config_id == TenantConfig.id)
            .where(SenderDomain.domain == domain)
        )
        if app is not None:
            return Route(app, "domain")

    settings = await session.get(Settings, 1)
    if settings is not None and settings.reject_unmapped_domains:
        return Route(None, "unmapped")
    app = await default_app(session)
    return Route(app, "default") if app is not None else Route(None, "no_default")


async def account_may_use_app(
    session: AsyncSession, username: str | None, app_id: int
) -> bool:
    """Whether the SMTP account `username` may send through app `app_id`.

    Clients let in by the IP whitelist have no account and are not limited.
    An account limited to apps (`restrict_apps`) with none listed may use
    none: the check fails closed.
    """
    if not username:
        return True
    account = await session.scalar(
        select(SmtpAccount).where(SmtpAccount.username == username)
    )
    if account is None:
        # Authenticated moments ago but gone now (deleted mid-session).
        return False
    if not account.restrict_apps:
        return True
    allowed = await session.scalar(
        select(SmtpAccountApp).where(
            SmtpAccountApp.smtp_account_id == account.id,
            SmtpAccountApp.tenant_config_id == app_id,
        )
    )
    return allowed is not None


async def ensure_default_app(session: AsyncSession) -> None:
    """Guarantee at least one app exists and exactly one is the default.

    Run at startup by both the UI and the relay; it only writes when the
    invariant is broken (fresh database, or a hand-edited one).
    """
    apps = (await session.scalars(select(TenantConfig).order_by(TenantConfig.id))).all()
    if not apps:
        # Fixed id: the UI and the relay both run this on a fresh database,
        # and the primary key lets only one of them create the app.
        session.add(TenantConfig(id=1, name="Default", is_default=True))
        return
    defaults = [a for a in apps if a.is_default]
    if len(defaults) == 1:
        return
    keep = defaults[0] if defaults else apps[0]
    for app in apps:
        app.is_default = app is keep
