"""Local SMTP account management.

CRUD for the `smtp_accounts` table. Passwords are bcrypt-hashed and
never returned to the UI; on edit the password field is empty and the
operator leaves it blank to keep the existing one.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import RedirectResponse
from pydantic import ValidationError
from sqlalchemy import delete as sa_delete, select

from common.db import session_scope
from common.models import SmtpAccount, SmtpAccountApp, TenantConfig
from common.passwords import hash_password

from ..forms import SmtpAccountIn, smtp_account_form
from .helpers import audit_config_change
from ..security import SessionPayload, require_csrf, require_user
from ..templating import render

router = APIRouter(prefix="/smtp-accounts")


def _first_error(exc: ValidationError) -> str:
    try:
        err = exc.errors()[0]
        loc = ".".join(str(p) for p in err.get("loc", ())) or "field"
        return f"{loc}: {err.get('msg', 'invalid')}"
    except Exception:
        return "Invalid input."


# -----------------------------------------------------------------------------
# Enterprise-app restriction
# -----------------------------------------------------------------------------

async def _apps(s) -> list[TenantConfig]:
    return list(
        (await s.scalars(select(TenantConfig).order_by(TenantConfig.name))).all()
    )


async def _allowed_app_ids(s) -> dict[int, set[int]]:
    """account id -> ids of the apps it is limited to."""
    out: dict[int, set[int]] = {}
    for acc_id, app_id in (
        await s.execute(
            select(SmtpAccountApp.smtp_account_id, SmtpAccountApp.tenant_config_id)
        )
    ).all():
        out.setdefault(acc_id, set()).add(app_id)
    return out


async def _parse_app_scope(
    s, app_scope: str, app_ids: list[int]
) -> tuple[bool, set[int], str | None]:
    """Validate the form's app restriction -> (restrict, app ids, error)."""
    if app_scope != "selected":
        return False, set(), None
    known = {a.id for a in await _apps(s)}
    chosen = set(app_ids)
    if not chosen:
        return True, set(), "Select at least one enterprise app, or allow all apps."
    if not chosen <= known:
        return True, set(), "Unknown enterprise app."
    return True, chosen, None


async def _set_app_scope(s, account: SmtpAccount, restrict: bool, app_ids: set[int]) -> None:
    account.restrict_apps = restrict
    await s.execute(
        sa_delete(SmtpAccountApp).where(SmtpAccountApp.smtp_account_id == account.id)
    )
    for app_id in sorted(app_ids if restrict else ()):
        s.add(SmtpAccountApp(smtp_account_id=account.id, tenant_config_id=app_id))


async def _list_context(session: SessionPayload, *, error: str | None = None) -> dict:
    async with session_scope() as s:
        rows = (
            await s.scalars(select(SmtpAccount).order_by(SmtpAccount.username))
        ).all()
        apps = await _apps(s)
        allowed = await _allowed_app_ids(s)
    return {
        "session": session,
        "rows": rows,
        "apps": apps,
        "app_names": {a.id: a.name for a in apps},
        "allowed": allowed,
        "error": error,
    }


# -----------------------------------------------------------------------------
# List + create
# -----------------------------------------------------------------------------

@router.get("", include_in_schema=False)
async def list_view(
    request: Request,
    session: SessionPayload = Depends(require_user),
):
    return render(request, "smtp_accounts.html", await _list_context(session))


@router.post(
    "",
    include_in_schema=False,
    dependencies=[Depends(require_csrf), Depends(require_user)],
)
async def create(
    request: Request,
    username: str = Form(""),
    password: str = Form(""),
    allowed_cidrs: str = Form(""),
    allowed_senders: str = Form(""),
    description: str = Form(""),
    app_scope: str = Form("all"),
    app_ids: list[int] = Form([]),
    session: SessionPayload = Depends(require_user),
):
    async def _fail(error: str):
        return render(
            request,
            "smtp_accounts.html",
            await _list_context(session, error=error),
            status_code=400,
        )

    try:
        data: SmtpAccountIn = smtp_account_form(
            username=username,
            password=password,
            allowed_cidrs=allowed_cidrs,
            allowed_senders=allowed_senders,
            description=description,
        )
    except ValidationError as exc:
        return await _fail(_first_error(exc))

    if len(data.password) < 12:
        return await _fail("Password must be at least 12 characters.")

    async with session_scope() as s:
        restrict, chosen, error = await _parse_app_scope(s, app_scope, app_ids)
        if error is None:
            existing = await s.scalar(
                select(SmtpAccount).where(SmtpAccount.username == data.username)
            )
            if existing is not None:
                error = "Username already in use."
        if error is None:
            account = SmtpAccount(
                username=data.username,
                password_hash=hash_password(data.password),
                allowed_cidrs=data.allowed_cidrs,
                allowed_senders=data.allowed_senders,
                description=data.description or None,
                is_enabled=True,
            )
            s.add(account)
            await s.flush()
            await _set_app_scope(s, account, restrict, chosen)
            await audit_config_change(
                s, session, request,
                details={
                    "section": "smtp_accounts",
                    "action": "create",
                    "username": data.username,
                    "allowed_cidrs_count": len(data.allowed_cidrs.splitlines()) if data.allowed_cidrs else 0,
                    "allowed_senders": data.allowed_senders.splitlines(),
                    "restrict_apps": restrict,
                    "app_ids": sorted(chosen),
                },
            )
    if error:
        return await _fail(error)
    return RedirectResponse("/smtp-accounts", status_code=303)


# -----------------------------------------------------------------------------
# Edit / toggle / delete
# -----------------------------------------------------------------------------

@router.get("/{row_id}/edit", include_in_schema=False)
async def edit_view(
    row_id: int,
    request: Request,
    session: SessionPayload = Depends(require_user),
):
    return render(
        request, "smtp_account_edit.html", await _edit_context(session, row_id)
    )


async def _edit_context(
    session: SessionPayload, row_id: int, *, error: str | None = None
) -> dict:
    async with session_scope() as s:
        row = await s.get(SmtpAccount, row_id)
        if row is None:
            raise HTTPException(status_code=404)
        apps = await _apps(s)
        allowed = (await _allowed_app_ids(s)).get(row_id, set())
    return {
        "session": session,
        "row": row,
        "apps": apps,
        "allowed_ids": allowed,
        "error": error,
    }


@router.post(
    "/{row_id}/edit",
    include_in_schema=False,
    dependencies=[Depends(require_csrf), Depends(require_user)],
)
async def edit_save(
    row_id: int,
    request: Request,
    password: str = Form(""),
    allowed_cidrs: str = Form(""),
    allowed_senders: str = Form(""),
    description: str = Form(""),
    app_scope: str = Form("all"),
    app_ids: list[int] = Form([]),
    session: SessionPayload = Depends(require_user),
):
    async with session_scope() as s:
        row = await s.get(SmtpAccount, row_id)
        if row is None:
            raise HTTPException(status_code=404)
        restrict, chosen, scope_error = await _parse_app_scope(s, app_scope, app_ids)

        # Validate the CIDR list shape via the shared pydantic model
        # (we only care about the side-effect of its validator).
        try:
            data: SmtpAccountIn = smtp_account_form(
                username=row.username,
                password=password,
                allowed_cidrs=allowed_cidrs,
                allowed_senders=allowed_senders,
                description=description,
            )
        except ValidationError as exc:
            error = _first_error(exc)
        else:
            error = scope_error
            if error is None and password and len(password) < 12:
                error = "Password must be at least 12 characters."
        if error is None:
            if password:
                row.password_hash = hash_password(password)
            row.allowed_cidrs = data.allowed_cidrs
            row.allowed_senders = data.allowed_senders
            row.description = description.strip() or None
            await _set_app_scope(s, row, restrict, chosen)
            await audit_config_change(
                s, session, request,
                details={
                    "section": "smtp_accounts",
                    "action": "edit",
                    "username": row.username,
                    "password_changed": bool(password),
                    "allowed_cidrs_count": len(data.allowed_cidrs.splitlines()) if data.allowed_cidrs else 0,
                    "allowed_senders": data.allowed_senders.splitlines(),
                    "restrict_apps": restrict,
                    "app_ids": sorted(chosen),
                },
            )
    if error:
        return render(
            request,
            "smtp_account_edit.html",
            await _edit_context(session, row_id, error=error),
            status_code=400,
        )
    return RedirectResponse("/smtp-accounts", status_code=303)


@router.post(
    "/{row_id}/toggle",
    include_in_schema=False,
    dependencies=[Depends(require_csrf), Depends(require_user)],
)
async def toggle(
    row_id: int,
    request: Request,
    session: SessionPayload = Depends(require_user),
):
    async with session_scope() as s:
        row = await s.get(SmtpAccount, row_id)
        if row is None:
            raise HTTPException(status_code=404)
        row.is_enabled = not row.is_enabled
        await audit_config_change(
            s, session, request,
            details={
                "section": "smtp_accounts",
                "action": "toggle",
                "username": row.username,
                "enabled": row.is_enabled,
            },
        )
    return RedirectResponse("/smtp-accounts", status_code=303)


@router.post(
    "/{row_id}/delete",
    include_in_schema=False,
    dependencies=[Depends(require_csrf), Depends(require_user)],
)
async def delete(
    row_id: int,
    request: Request,
    session: SessionPayload = Depends(require_user),
):
    async with session_scope() as s:
        row = await s.get(SmtpAccount, row_id)
        if row is None:
            raise HTTPException(status_code=404)
        username = row.username
        await s.delete(row)
        await audit_config_change(
            s, session, request,
            details={
                "section": "smtp_accounts",
                "action": "delete",
                "username": username,
            },
        )
    return RedirectResponse("/smtp-accounts", status_code=303)
