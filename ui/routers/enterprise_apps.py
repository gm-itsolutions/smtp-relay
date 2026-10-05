"""Enterprise apps and sender-domain routing.

    /config/tenant                — list of enterprise apps + add
    /config/tenant/{id}           — one app: credentials, certificate, test
    /config/domains               — sender domain → app mapping, default app

An enterprise app is one Entra ID app registration (`TenantConfig` row),
possibly in a different Microsoft 365 tenant from the others. Mail is
routed to an app by its sender's domain; the default app handles every
domain without a mapping (see `common.routing`).

All state-changing endpoints depend on `require_csrf` and `require_user`.
"""

from __future__ import annotations

import asyncio
import datetime as _dt
import logging

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import PlainTextResponse, RedirectResponse, Response
from pydantic import ValidationError
from sqlalchemy import func, select

from common.audit import record as audit_record
from common.certs import (
    ALLOWED_VALIDITY_YEARS,
    DEFAULT_VALIDITY_YEARS,
    generate_self_signed,
)
from common.crypto import encrypt_str
from common.db import session_scope
from common.graph_client import GraphClient, GraphError
from common.models import (
    AuditEventType,
    AuditOutcome,
    AuthorisedSender,
    MailQueue,
    MailStatus,
    SenderDomain,
    Settings,
    SmtpAccountApp,
    TenantConfig,
)
from common.routing import sender_domain

from ..forms import AppNameIn, DomainIn, tenant_form
from .helpers import audit_config_change
from ..security import SessionPayload, require_csrf, require_user
from ..templating import render

router = APIRouter(prefix="/config")
_log = logging.getLogger("ui.enterprise_apps")


def _utcnow() -> _dt.datetime:
    return _dt.datetime.now(_dt.timezone.utc).replace(tzinfo=None)


def _first_error(exc: ValidationError) -> str:
    try:
        err = exc.errors()[0]
        loc = ".".join(str(p) for p in err.get("loc", ())) or "field"
        return f"{loc}: {err.get('msg', 'invalid')}"
    except Exception:
        return "Invalid input."


def _app_url(app_id: int, flag: str | None = None) -> str:
    """Path of an app's page, optionally with a `?<flag>=1` notice.

    app_id is already an int (FastAPI path converter), but the explicit
    cast makes the integer type visible to static analysers so they don't
    flag the redirect as an open-redirect risk.
    """
    path = f"/config/tenant/{int(app_id)}"
    return f"{path}?{flag}=1" if flag else path


async def _load_app(app_id: int) -> TenantConfig:
    async with session_scope() as s:
        cfg = await s.get(TenantConfig, app_id)
    if cfg is None:
        raise HTTPException(status_code=404)
    return cfg


async def _name_taken(s, name: str, *, except_id: int | None = None) -> bool:
    stmt = select(TenantConfig.id).where(func.lower(TenantConfig.name) == name.lower())
    if except_id is not None:
        stmt = stmt.where(TenantConfig.id != except_id)
    return await s.scalar(stmt) is not None


# =============================================================================
# App list
# =============================================================================

async def _apps_context(session: SessionPayload, *, error: str | None = None) -> dict:
    async with session_scope() as s:
        apps = (
            await s.scalars(select(TenantConfig).order_by(TenantConfig.name))
        ).all()
        domain_counts = dict(
            (
                await s.execute(
                    select(SenderDomain.tenant_config_id, func.count(SenderDomain.id))
                    .group_by(SenderDomain.tenant_config_id)
                )
            ).all()
        )
    return {
        "session": session,
        "apps": apps,
        "domain_counts": domain_counts,
        "today": _utcnow().date(),
        "error": error,
    }


@router.get("/tenant", include_in_schema=False)
async def apps_view(
    request: Request,
    session: SessionPayload = Depends(require_user),
):
    return render(request, "config_apps.html", await _apps_context(session))


@router.post(
    "/tenant/new",
    include_in_schema=False,
    dependencies=[Depends(require_csrf), Depends(require_user)],
)
async def app_create(
    request: Request,
    name: str = Form(""),
    session: SessionPayload = Depends(require_user),
):
    try:
        data = AppNameIn(name=name)
    except ValidationError as exc:
        return render(
            request,
            "config_apps.html",
            await _apps_context(session, error=_first_error(exc)),
            status_code=400,
        )
    async with session_scope() as s:
        if await _name_taken(s, data.name):
            error = f"An enterprise app named {data.name!r} already exists."
        else:
            error = None
            cfg = TenantConfig(name=data.name, is_default=False)
            s.add(cfg)
            await s.flush()
            app_id = cfg.id
            await audit_config_change(
                s, session, request,
                details={
                    "section": "tenant",
                    "action": "app_create",
                    "app_id": app_id,
                    "name": data.name,
                },
            )
    if error:
        return render(
            request,
            "config_apps.html",
            await _apps_context(session, error=error),
            status_code=400,
        )
    return RedirectResponse(_app_url(app_id, "created"), status_code=303)


# =============================================================================
# One app
# =============================================================================

async def _app_context(
    session: SessionPayload,
    cfg: TenantConfig,
    *,
    error: str | None = None,
) -> dict:
    async with session_scope() as s:
        domains = (
            await s.scalars(
                select(SenderDomain.domain)
                .where(SenderDomain.tenant_config_id == cfg.id)
                .order_by(SenderDomain.domain)
            )
        ).all()
    return {
        "session": session,
        "cfg": cfg,
        "domains": domains,
        "has_secret": bool(cfg.client_secret_enc),
        "has_active_cert": bool(cfg.cert_thumbprint),
        "has_pending_cert": bool(cfg.cert_pending_thumbprint),
        "cert_years": list(ALLOWED_VALIDITY_YEARS),
        "cert_default_years": DEFAULT_VALIDITY_YEARS,
        "today": _utcnow().date(),
        "error": error,
    }


async def _render_app_error(request, session, app_id: int, error: str):
    return render(
        request,
        "config_tenant.html",
        await _app_context(session, await _load_app(app_id), error=error),
        status_code=400,
    )


@router.get("/tenant/{app_id}", include_in_schema=False)
async def app_view(
    app_id: int,
    request: Request,
    session: SessionPayload = Depends(require_user),
):
    cfg = await _load_app(app_id)
    return render(request, "config_tenant.html", await _app_context(session, cfg))


@router.post(
    "/tenant/{app_id}",
    include_in_schema=False,
    dependencies=[Depends(require_csrf), Depends(require_user)],
)
async def app_save(
    app_id: int,
    request: Request,
    name: str = Form(""),
    tenant_id: str = Form(""),
    client_id: str = Form(""),
    auth_method: str = Form("secret"),
    client_secret: str = Form(""),
    secret_expires_at: str = Form(""),
    clear_secret_expires_at: bool = Form(False),
    expiry_verified: bool = Form(False),
    session: SessionPayload = Depends(require_user),
):
    cfg = await _load_app(app_id)
    try:
        data = tenant_form(
            name=name,
            tenant_id=tenant_id,
            client_id=client_id,
            auth_method=auth_method,
            client_secret=client_secret,
            secret_expires_at=secret_expires_at,
            clear_secret_expires_at=clear_secret_expires_at,
            expiry_verified=expiry_verified,
        )
    except (ValidationError, ValueError) as exc:
        msg = _first_error(exc) if isinstance(exc, ValidationError) else str(exc)
        return await _render_app_error(request, session, app_id, msg)

    # When a new client_secret is being submitted, the operator must
    # explicitly confirm the expiry date is up-to-date. This guards
    # against the common "I rotated but forgot to update the date"
    # mistake.
    if data.client_secret and not data.expiry_verified:
        return await _render_app_error(
            request, session, app_id,
            "When updating the client secret you must tick "
            "'I have verified the secret expiry date' to confirm "
            "the date below reflects the new secret.",
        )

    # Certificate can only be made the live method once an active certificate
    # actually exists — otherwise outbound mail would immediately break.
    if data.auth_method == "certificate" and not cfg.cert_thumbprint:
        return await _render_app_error(
            request, session, app_id,
            "Certificate authentication needs an active certificate. "
            "Generate one below, upload its .cer to Entra, then "
            "activate it before selecting this method.",
        )

    async with session_scope() as s:
        if await _name_taken(s, data.name, except_id=app_id):
            error = f"An enterprise app named {data.name!r} already exists."
        else:
            error = None
            cfg = await s.get(TenantConfig, app_id)
            if cfg is None:
                raise HTTPException(status_code=404)
            cfg.name = data.name
            cfg.tenant_id = data.tenant_id
            cfg.client_id = data.client_id
            cfg.auth_method = data.auth_method
            if data.client_secret:
                cfg.client_secret_enc = encrypt_str(data.client_secret)
            if data.clear_secret_expires_at:
                cfg.secret_expires_at = None
            elif data.secret_expires_at is not None:
                cfg.secret_expires_at = data.secret_expires_at
            # Invalidate cached test status — the operator must re-run it.
            cfg.last_test_at = None
            cfg.last_test_ok = None
            cfg.last_test_error = None

            await audit_config_change(
                s, session, request,
                details={
                    "section": "tenant",
                    "app_id": app_id,
                    "name": data.name,
                    "tenant_id": data.tenant_id,
                    "client_id": data.client_id,
                    "auth_method": data.auth_method,
                    "secret_updated": bool(data.client_secret),
                    "secret_expires_at": (
                        cfg.secret_expires_at.isoformat()
                        if cfg.secret_expires_at else None
                    ),
                },
            )
    if error:
        return await _render_app_error(request, session, app_id, error)
    return RedirectResponse(_app_url(app_id, "saved"), status_code=303)


@router.post(
    "/tenant/{app_id}/test",
    include_in_schema=False,
    dependencies=[Depends(require_csrf), Depends(require_user)],
)
async def app_test(
    app_id: int,
    request: Request,
    session: SessionPayload = Depends(require_user),
):
    """Try to acquire a Graph token with the app's stored credentials."""
    now = _utcnow()
    ok = False
    err: str | None = None
    expires_at: _dt.datetime | None = None

    async with session_scope() as s:
        cfg = await s.get(TenantConfig, app_id)
        if cfg is None:
            raise HTTPException(status_code=404)
        if not cfg.tenant_id or not cfg.client_id or not cfg.has_active_credential:
            err = "Enterprise app configuration is incomplete."
        else:
            try:
                client = GraphClient.from_tenant_config(cfg)
                info = await asyncio.to_thread(client.acquire_token)
                ok = True
                expires_at = info.expires_at.replace(tzinfo=None)
            except GraphError as exc:
                err = str(exc)
            except Exception as exc:
                err = f"Unexpected error: {exc}"

        cfg.last_test_at = now
        cfg.last_test_ok = ok
        cfg.last_test_error = None if ok else (err or "Unknown error")[:2000]
        if ok:
            cfg.last_token_acquired_at = now
            cfg.last_token_expires_at = expires_at

        # NB: kept as raw audit_record because the outcome is conditional
        # on the Graph test result (SUCCESS vs FAILURE), while
        # audit_config_change() is hard-coded to SUCCESS.
        await audit_record(
            s,
            event_type=AuditEventType.CONFIG_CHANGE,
            outcome=AuditOutcome.SUCCESS if ok else AuditOutcome.FAILURE,
            username=session.username,
            source_ip=request.client.host if request.client else None,
            details={
                "section": "tenant",
                "action": "test_connection",
                "app_id": app_id,
                "ok": ok,
                "error": None if ok else err,
            },
        )
    return RedirectResponse(_app_url(app_id, "tested"), status_code=303)


@router.post(
    "/tenant/{app_id}/delete",
    include_in_schema=False,
    dependencies=[Depends(require_csrf), Depends(require_user)],
)
async def app_delete(
    app_id: int,
    request: Request,
    session: SessionPayload = Depends(require_user),
):
    """Delete an app nothing depends on any more.

    Refused while the app is the default, has domains mapped to it, is in
    an SMTP account's allowed list (dropping it would silently widen that
    account), or still has mail waiting to be sent through it.
    """
    async with session_scope() as s:
        cfg = await s.get(TenantConfig, app_id)
        if cfg is None:
            raise HTTPException(status_code=404)
        blockers: list[str] = []
        if cfg.is_default:
            blockers.append("it is the default app (choose another default on the Domains page)")
        n_domains = await s.scalar(
            select(func.count(SenderDomain.id)).where(
                SenderDomain.tenant_config_id == app_id
            )
        )
        if n_domains:
            blockers.append(f"{n_domains} domain(s) are mapped to it")
        n_accounts = await s.scalar(
            select(func.count()).select_from(SmtpAccountApp).where(
                SmtpAccountApp.tenant_config_id == app_id
            )
        )
        if n_accounts:
            blockers.append(f"{n_accounts} SMTP account(s) are limited to it")
        n_queued = await s.scalar(
            select(func.count(MailQueue.id)).where(
                MailQueue.tenant_config_id == app_id,
                MailQueue.status.in_([MailStatus.PENDING, MailStatus.SENDING]),
            )
        )
        if n_queued:
            blockers.append(f"{n_queued} queued mail(s) are waiting to be sent through it")
        if not blockers:
            name = cfg.name
            await s.delete(cfg)
            await audit_config_change(
                s, session, request,
                details={
                    "section": "tenant",
                    "action": "app_delete",
                    "app_id": app_id,
                    "name": name,
                },
            )
    if blockers:
        return await _render_app_error(
            request, session, app_id,
            "This enterprise app cannot be deleted: " + "; ".join(blockers) + ".",
        )
    return RedirectResponse("/config/tenant?deleted=1", status_code=303)


# -----------------------------------------------------------------------------
# Certificate credential lifecycle
#
# Generate -> a new key pair lands in the *pending* slot only; it never
# touches the live signing key, so generating never disrupts sending.
# The operator downloads its .cer, uploads it to Entra, then Activates it
# (pending -> active). Discard drops a pending certificate.
# -----------------------------------------------------------------------------

@router.post(
    "/tenant/{app_id}/cert/generate",
    include_in_schema=False,
    dependencies=[Depends(require_csrf), Depends(require_user)],
)
async def app_cert_generate(
    app_id: int,
    request: Request,
    cert_valid_years: int = Form(DEFAULT_VALIDITY_YEARS),
    session: SessionPayload = Depends(require_user),
):
    await _load_app(app_id)
    if cert_valid_years not in ALLOWED_VALIDITY_YEARS:
        return await _render_app_error(
            request, session, app_id,
            "Invalid certificate validity. Choose one of: "
            + ", ".join(f"{y}" for y in ALLOWED_VALIDITY_YEARS)
            + " year(s).",
        )

    # Generation (RSA keygen) is CPU-bound; keep the event loop responsive.
    gen = await asyncio.to_thread(
        generate_self_signed, "smtp-relay", cert_valid_years
    )

    async with session_scope() as s:
        cfg = await s.get(TenantConfig, app_id)
        if cfg is None:
            raise HTTPException(status_code=404)
        cfg.cert_pending_private_key_enc = encrypt_str(gen.private_key_pem)
        cfg.cert_pending_public_pem = gen.public_cert_pem
        cfg.cert_pending_thumbprint = gen.thumbprint_sha1
        cfg.cert_pending_not_after = gen.not_after.date()
        cfg.cert_pending_created_at = _utcnow()

        await audit_config_change(
            s, session, request,
            details={
                "section": "tenant",
                "action": "cert_generate",
                "app_id": app_id,
                "thumbprint": gen.thumbprint_sha1,
                "not_after": gen.not_after.date().isoformat(),
                "valid_years": cert_valid_years,
            },
        )
    return RedirectResponse(
        _app_url(app_id, "cert_generated"), status_code=303
    )


@router.post(
    "/tenant/{app_id}/cert/activate",
    include_in_schema=False,
    dependencies=[Depends(require_csrf), Depends(require_user)],
)
async def app_cert_activate(
    app_id: int,
    request: Request,
    session: SessionPayload = Depends(require_user),
):
    """Promote the pending certificate to active and make it the live method.

    Do this only after uploading the pending .cer to the Entra app
    registration, or token acquisition will fail.
    """
    async with session_scope() as s:
        cfg = await s.get(TenantConfig, app_id)
        if cfg is None:
            raise HTTPException(status_code=404)
        thumbprint = cfg.cert_pending_thumbprint
        if thumbprint:
            cfg.cert_private_key_enc = cfg.cert_pending_private_key_enc
            cfg.cert_public_pem = cfg.cert_pending_public_pem
            cfg.cert_thumbprint = cfg.cert_pending_thumbprint
            cfg.cert_not_after = cfg.cert_pending_not_after
            cfg.cert_created_at = cfg.cert_pending_created_at or _utcnow()
            cfg.cert_subject = "smtp-relay"
            # Clear the staging slot.
            cfg.cert_pending_private_key_enc = None
            cfg.cert_pending_public_pem = None
            cfg.cert_pending_thumbprint = None
            cfg.cert_pending_not_after = None
            cfg.cert_pending_created_at = None
            # Switch the live method and force a re-test.
            cfg.auth_method = "certificate"
            cfg.last_test_at = None
            cfg.last_test_ok = None
            cfg.last_test_error = None

            await audit_config_change(
                s, session, request,
                details={
                    "section": "tenant",
                    "action": "cert_activate",
                    "app_id": app_id,
                    "thumbprint": thumbprint,
                },
            )
    if not thumbprint:
        return await _render_app_error(
            request, session, app_id, "There is no pending certificate to activate."
        )
    return RedirectResponse(
        _app_url(app_id, "cert_activated"), status_code=303
    )


@router.post(
    "/tenant/{app_id}/cert/discard",
    include_in_schema=False,
    dependencies=[Depends(require_csrf), Depends(require_user)],
)
async def app_cert_discard(
    app_id: int,
    request: Request,
    session: SessionPayload = Depends(require_user),
):
    async with session_scope() as s:
        cfg = await s.get(TenantConfig, app_id)
        if cfg is None:
            raise HTTPException(status_code=404)
        if not cfg.cert_pending_thumbprint:
            return RedirectResponse(_app_url(app_id), status_code=303)
        thumbprint = cfg.cert_pending_thumbprint
        cfg.cert_pending_private_key_enc = None
        cfg.cert_pending_public_pem = None
        cfg.cert_pending_thumbprint = None
        cfg.cert_pending_not_after = None
        cfg.cert_pending_created_at = None

        await audit_config_change(
            s, session, request,
            details={
                "section": "tenant",
                "action": "cert_discard",
                "app_id": app_id,
                "thumbprint": thumbprint,
            },
        )
    return RedirectResponse(
        _app_url(app_id, "cert_discarded"), status_code=303
    )


def _cer_response(pem: str, thumbprint: str | None) -> Response:
    """Serve a PEM public certificate as a downloadable .cer attachment."""
    tag = (thumbprint or "cert")[:8]
    return PlainTextResponse(
        pem,
        media_type="application/x-pem-file",
        headers={
            "Content-Disposition": f'attachment; filename="smtp-relay-{tag}.cer"'
        },
    )


@router.get("/tenant/{app_id}/cert/active.cer", include_in_schema=False)
async def app_cert_download_active(
    app_id: int,
    request: Request,
    session: SessionPayload = Depends(require_user),
):
    cfg = await _load_app(app_id)
    if not cfg.cert_public_pem:
        raise HTTPException(status_code=404)
    return _cer_response(cfg.cert_public_pem, cfg.cert_thumbprint)


@router.get("/tenant/{app_id}/cert/pending.cer", include_in_schema=False)
async def app_cert_download_pending(
    app_id: int,
    request: Request,
    session: SessionPayload = Depends(require_user),
):
    cfg = await _load_app(app_id)
    if not cfg.cert_pending_public_pem:
        raise HTTPException(status_code=404)
    return _cer_response(cfg.cert_pending_public_pem, cfg.cert_pending_thumbprint)


# =============================================================================
# Domains
# =============================================================================

async def _domains_context(session: SessionPayload, *, error: str | None = None) -> dict:
    async with session_scope() as s:
        apps = (
            await s.scalars(select(TenantConfig).order_by(TenantConfig.name))
        ).all()
        rows = (
            await s.scalars(select(SenderDomain).order_by(SenderDomain.domain))
        ).all()
        settings = await s.get(Settings, 1)
        sender_addrs = (
            await s.scalars(
                select(AuthorisedSender.address).where(
                    AuthorisedSender.is_enabled.is_(True)
                )
            )
        ).all()
    mapped = {r.domain for r in rows}
    in_use = set(filter(None, (sender_domain(a) for a in sender_addrs)))
    if settings is not None and settings.admin_email_from:
        in_use.add(sender_domain(settings.admin_email_from))
    default = next((a for a in apps if a.is_default), None)
    return {
        "session": session,
        "apps": apps,
        "app_names": {a.id: a.name for a in apps},
        "default_app": default,
        "rows": rows,
        "reject_unmapped": bool(settings and settings.reject_unmapped_domains),
        "unmapped_in_use": sorted(d for d in in_use if d and d not in mapped),
        "error": error,
    }


async def _domains_error(request, session, error: str):
    return render(
        request,
        "config_domains.html",
        await _domains_context(session, error=error),
        status_code=400,
    )


@router.get("/domains", include_in_schema=False)
async def domains_view(
    request: Request,
    session: SessionPayload = Depends(require_user),
):
    return render(request, "config_domains.html", await _domains_context(session))


@router.post(
    "/domains/routing",
    include_in_schema=False,
    dependencies=[Depends(require_csrf), Depends(require_user)],
)
async def domains_routing(
    request: Request,
    default_app_id: int = Form(...),
    reject_unmapped: bool = Form(False),
    session: SessionPayload = Depends(require_user),
):
    """Set the default app and the policy for unmapped domains."""
    async with session_scope() as s:
        target = await s.get(TenantConfig, default_app_id)
        if target is None:
            error = "Unknown enterprise app."
        else:
            error = None
            # Flip every row in one transaction so there is always exactly
            # one default.
            for app in (await s.scalars(select(TenantConfig))).all():
                app.is_default = app.id == default_app_id
            settings = await s.get(Settings, 1)
            if settings is None:
                settings = Settings(id=1)
                s.add(settings)
            settings.reject_unmapped_domains = reject_unmapped
            await audit_config_change(
                s, session, request,
                details={
                    "section": "domains",
                    "action": "routing",
                    "default_app_id": default_app_id,
                    "default_app": target.name,
                    "reject_unmapped_domains": reject_unmapped,
                },
            )
    if error:
        return await _domains_error(request, session, error)
    return RedirectResponse("/config/domains?saved=1", status_code=303)


@router.post(
    "/domains",
    include_in_schema=False,
    dependencies=[Depends(require_csrf), Depends(require_user)],
)
async def domains_add(
    request: Request,
    domain: str = Form(""),
    app_id: int = Form(...),
    description: str = Form(""),
    session: SessionPayload = Depends(require_user),
):
    try:
        data = DomainIn(domain=domain, app_id=app_id, description=description)
    except ValidationError as exc:
        return await _domains_error(request, session, _first_error(exc))

    async with session_scope() as s:
        app = await s.get(TenantConfig, data.app_id)
        exists = await s.scalar(
            select(SenderDomain.id).where(SenderDomain.domain == data.domain)
        )
        if app is None:
            error = "Unknown enterprise app."
        elif exists is not None:
            error = f"{data.domain} is already mapped; change its app in the table below."
        else:
            error = None
            s.add(
                SenderDomain(
                    domain=data.domain,
                    tenant_config_id=app.id,
                    description=data.description or None,
                )
            )
            await audit_config_change(
                s, session, request,
                details={
                    "section": "domains",
                    "action": "add",
                    "domain": data.domain,
                    "app_id": app.id,
                    "app": app.name,
                },
            )
    if error:
        return await _domains_error(request, session, error)
    return RedirectResponse("/config/domains", status_code=303)


@router.post(
    "/domains/{row_id}",
    include_in_schema=False,
    dependencies=[Depends(require_csrf), Depends(require_user)],
)
async def domains_update(
    row_id: int,
    request: Request,
    app_id: int = Form(...),
    description: str = Form(""),
    session: SessionPayload = Depends(require_user),
):
    async with session_scope() as s:
        row = await s.get(SenderDomain, row_id)
        if row is None:
            raise HTTPException(status_code=404)
        try:
            data = DomainIn(domain=row.domain, app_id=app_id, description=description)
        except ValidationError as exc:
            error = _first_error(exc)
        else:
            app = await s.get(TenantConfig, data.app_id)
            if app is None:
                error = "Unknown enterprise app."
            else:
                error = None
                old_app_id = row.tenant_config_id
                row.tenant_config_id = app.id
                row.description = data.description or None
                await audit_config_change(
                    s, session, request,
                    details={
                        "section": "domains",
                        "action": "update",
                        "domain": row.domain,
                        "old_app_id": old_app_id,
                        "app_id": app.id,
                        "app": app.name,
                    },
                )
    if error:
        return await _domains_error(request, session, error)
    return RedirectResponse("/config/domains", status_code=303)


@router.post(
    "/domains/{row_id}/delete",
    include_in_schema=False,
    dependencies=[Depends(require_csrf), Depends(require_user)],
)
async def domains_delete(
    row_id: int,
    request: Request,
    session: SessionPayload = Depends(require_user),
):
    async with session_scope() as s:
        row = await s.get(SenderDomain, row_id)
        if row is None:
            raise HTTPException(status_code=404)
        domain, app_id = row.domain, row.tenant_config_id
        await s.delete(row)
        await audit_config_change(
            s, session, request,
            details={
                "section": "domains",
                "action": "delete",
                "domain": domain,
                "app_id": app_id,
            },
        )
    return RedirectResponse("/config/domains", status_code=303)
