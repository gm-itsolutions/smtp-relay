"""Login / TOTP / session regression tests (security findings #1, #4, #5)."""

from __future__ import annotations

import datetime as dt
import re

import pyotp
import pytest
from fastapi.testclient import TestClient

from common.crypto import encrypt_str
from common.db import session_scope
from common.models import User
from common.passwords import hash_password
from conftest import run

PASSWORD = "correct-horse-battery-staple"
SECRET = pyotp.random_base32()


def _make_user(*, enrolled: bool, must_change: bool = False) -> None:
    async def _go():
        async with session_scope() as s:
            s.add(
                User(
                    username="admin",
                    password_hash=hash_password(PASSWORD),
                    totp_secret=encrypt_str(SECRET) if enrolled else None,
                    totp_enrolled_at=dt.datetime.utcnow() if enrolled else None,
                    must_change_password=must_change,
                    is_active=True,
                )
            )

    run(_go())


@pytest.fixture()
def client():
    from ui.main import create_app

    with TestClient(create_app(), base_url="https://testserver") as c:
        yield c


def _csrf(client: TestClient) -> str:
    client.get("/login")
    return client.cookies.get("smtprelay_csrf")


def _login_password(client: TestClient):
    return client.post(
        "/login",
        data={"username": "admin", "password": PASSWORD, "csrf_token": _csrf(client)},
        follow_redirects=False,
    )


def _login_full(client: TestClient):
    _login_password(client)
    code = pyotp.TOTP(SECRET).now()
    return client.post(
        "/login/totp",
        data={"code": code, "csrf_token": client.cookies.get("smtprelay_csrf")},
        follow_redirects=False,
    )


def test_enrol_page_never_reveals_existing_secret(client):
    # Finding #1: password alone must not yield the stored TOTP secret.
    _make_user(enrolled=True)
    r = _login_password(client)
    assert r.headers["location"] == "/login/totp"
    r = client.get("/login/totp/enrol", follow_redirects=False)
    assert r.status_code == 303
    assert r.headers["location"] == "/login/totp"
    assert SECRET not in r.text


def test_enrol_post_rejected_when_already_enrolled(client):
    _make_user(enrolled=True)
    _login_password(client)
    r = client.post(
        "/login/totp/enrol",
        data={"code": pyotp.TOTP(SECRET).now(), "csrf_token": client.cookies.get("smtprelay_csrf")},
        follow_redirects=False,
    )
    assert r.headers["location"] == "/login/totp"
    assert client.get("/dashboard", follow_redirects=False).headers["location"] == "/login"


def test_first_enrolment_still_works(client):
    _make_user(enrolled=False)
    r = _login_password(client)
    assert r.headers["location"] == "/login/totp/enrol"
    page = client.get("/login/totp/enrol")
    secret = re.search(r"\b([A-Z2-7]{32})\b", page.text).group(1)
    r = client.post(
        "/login/totp/enrol",
        data={"code": pyotp.TOTP(secret).now(), "csrf_token": client.cookies.get("smtprelay_csrf")},
        follow_redirects=False,
    )
    assert r.headers["location"] == "/dashboard"
    assert client.get("/dashboard", follow_redirects=False).status_code == 200


def test_totp_brute_force_is_banned(client):
    # Finding #5: wrong codes count towards the IP ban, and the ban is enforced.
    _make_user(enrolled=True)
    _login_password(client)
    for _ in range(5):
        client.post(
            "/login/totp",
            data={"code": "000000", "csrf_token": client.cookies.get("smtprelay_csrf")},
        )
    r = client.post(
        "/login/totp",
        data={"code": pyotp.TOTP(SECRET).now(), "csrf_token": client.cookies.get("smtprelay_csrf")},
        follow_redirects=False,
    )
    assert r.status_code == 429


def test_logout_revokes_copied_cookie(client):
    # Finding #4: a stolen cookie must die with logout.
    _make_user(enrolled=True)
    _login_full(client)
    stolen = client.cookies.get("smtprelay_session")
    assert client.get("/dashboard", follow_redirects=False).status_code == 200
    client.post("/logout", data={"csrf_token": client.cookies.get("smtprelay_csrf")})
    client.cookies.set("smtprelay_session", stolen)
    assert client.get("/dashboard", follow_redirects=False).headers["location"] == "/login"


def test_disabled_user_loses_session(client):
    _make_user(enrolled=True)
    _login_full(client)

    async def _disable():
        async with session_scope() as s:
            u = (await s.get(User, 1))
            u.is_active = False

    run(_disable())
    assert client.get("/dashboard", follow_redirects=False).headers["location"] == "/login"


def test_must_change_password_is_enforced(client):
    _make_user(enrolled=True, must_change=True)
    _login_full(client)
    r = client.get("/dashboard", follow_redirects=False)
    assert r.headers["location"] == "/account/password"
    assert client.get("/account/password", follow_redirects=False).status_code == 200
