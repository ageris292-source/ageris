"""Web-app features: admin user management (invite, roles, deactivation,
password reset, forced password change, token revocation) and the per-user
watchlist."""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.routes.stocks import get_daily_provider, get_now
from app.main import app
from app.models import AuditLog, User
from tests.conftest import PASSWORD, auth_header
from tests.market_helpers import NOW, load, provider_for

NEW_PASSWORD = "a-much-better-passphrase"


def _login(client: TestClient, email: str, password: str) -> dict[str, str]:
    r = client.post("/auth/token", data={"username": email, "password": password})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


# --------------------------------------------------------------------------- users


def test_invite_forces_password_change_before_anything_else(
    client: TestClient, admin: User, db: Session
) -> None:
    ah = auth_header(client, admin.email)
    r = client.post("/users", headers=ah, json={"email": "Priya@Example.in", "role": "analyst"})
    assert r.status_code == 201, r.text
    body = r.json()
    temp = body["temporary_password"]
    assert body["user"]["email"] == "priya@example.in"
    assert body["user"]["must_change_password"] is True
    assert len(temp.replace("-", "")) == 16

    # duplicate invite is refused
    assert client.post("/users", headers=ah, json={"email": "priya@example.in"}).status_code == 409

    h = _login(client, "priya@example.in", temp)
    me = client.get("/auth/me", headers=h).json()
    assert me["must_change_password"] is True and me["role"] == "analyst"
    # every other endpoint is closed until the temporary password is replaced
    blocked = client.get("/stocks", headers=h)
    assert blocked.status_code == 403 and "password change required" in blocked.json()["detail"]

    bad = client.post(
        "/auth/change-password",
        headers=h,
        json={"current_password": "wrong", "new_password": NEW_PASSWORD},
    )
    assert bad.status_code == 400
    short = client.post(
        "/auth/change-password", headers=h, json={"current_password": temp, "new_password": "x"}
    )
    assert short.status_code == 400

    ok = client.post(
        "/auth/change-password",
        headers=h,
        json={"current_password": temp, "new_password": NEW_PASSWORD},
    )
    assert ok.status_code == 200
    fresh = {"Authorization": f"Bearer {ok.json()['access_token']}"}
    # the old token is revoked; the fresh one works everywhere
    assert client.get("/auth/me", headers=h).status_code == 401
    assert client.get("/stocks", headers=fresh).status_code == 200
    assert client.get("/auth/me", headers=fresh).json()["must_change_password"] is False
    # the temporary password no longer works
    assert (
        client.post(
            "/auth/token", data={"username": "priya@example.in", "password": temp}
        ).status_code
        == 401
    )
    actions = db.scalars(select(AuditLog.action)).all()
    assert "user.create" in actions and "user.change_password" in actions


def test_user_admin_endpoints_are_admin_only(
    client: TestClient, analyst: User, admin: User
) -> None:
    h = auth_header(client, analyst.email)
    assert client.get("/users", headers=h).status_code == 403
    assert client.post("/users", headers=h, json={"email": "x@y.in"}).status_code == 403
    assert (
        client.patch(f"/users/{admin.id}", headers=h, json={"role": "analyst"}).status_code == 403
    )
    assert client.post(f"/users/{admin.id}/reset-password", headers=h).status_code == 403
    assert client.get("/users").status_code == 401


def test_role_change_and_deactivation_revoke_sessions(
    client: TestClient, admin: User, analyst: User
) -> None:
    ah = auth_header(client, admin.email)
    uh = auth_header(client, analyst.email)
    listed = client.get("/users", headers=ah).json()
    assert {u["email"] for u in listed} == {admin.email, analyst.email}
    assert all(u["last_login_at"] for u in listed)

    r = client.patch(f"/users/{analyst.id}", headers=ah, json={"role": "admin"})
    assert r.status_code == 200 and r.json()["role"] == "admin"
    assert client.get("/auth/me", headers=uh).status_code == 401  # old token revoked
    uh = auth_header(client, analyst.email)
    assert client.get("/auth/me", headers=uh).json()["role"] == "admin"

    r = client.patch(f"/users/{analyst.id}", headers=ah, json={"is_active": False})
    assert r.status_code == 200 and r.json()["is_active"] is False
    assert client.get("/auth/me", headers=uh).status_code == 401
    assert (
        client.post(
            "/auth/token", data={"username": analyst.email, "password": PASSWORD}
        ).status_code
        == 401
    )
    r = client.patch(f"/users/{analyst.id}", headers=ah, json={"is_active": True})
    assert r.json()["is_active"] is True
    assert (
        client.patch("/users/not-a-uuid", headers=ah, json={"is_active": True}).status_code == 404
    )


def test_admins_cannot_lock_themselves_or_the_system_out(
    client: TestClient, admin: User, analyst: User
) -> None:
    ah = auth_header(client, admin.email)
    for body in ({"role": "analyst"}, {"is_active": False}):
        r = client.patch(f"/users/{admin.id}", headers=ah, json=body)
        assert r.status_code == 409
    assert client.post(f"/users/{admin.id}/reset-password", headers=ah).status_code == 409
    # promote the analyst, who then cannot demote the last *other* admin away
    client.patch(f"/users/{analyst.id}", headers=ah, json={"role": "admin"})
    second = auth_header(client, analyst.email)
    assert (
        client.patch(f"/users/{admin.id}", headers=second, json={"role": "analyst"}).status_code
        == 200
    )
    # the demoted admin's token is revoked, and the only remaining admin cannot
    # demote or deactivate itself
    assert client.get("/users", headers=ah).status_code == 401
    for body in ({"role": "analyst"}, {"is_active": False}):
        assert client.patch(f"/users/{analyst.id}", headers=second, json=body).status_code == 409


def test_reset_password_issues_a_new_temporary_password(
    client: TestClient, admin: User, analyst: User
) -> None:
    ah = auth_header(client, admin.email)
    uh = auth_header(client, analyst.email)
    r = client.post(f"/users/{analyst.id}/reset-password", headers=ah)
    assert r.status_code == 200
    temp = r.json()["temporary_password"]
    assert client.get("/auth/me", headers=uh).status_code == 401
    assert (
        client.post(
            "/auth/token", data={"username": analyst.email, "password": PASSWORD}
        ).status_code
        == 401
    )
    h = _login(client, analyst.email, temp)
    assert client.get("/stocks", headers=h).status_code == 403


# ----------------------------------------------------------------------- watchlist


@pytest.fixture
def api(client: TestClient) -> Iterator[TestClient]:
    app.dependency_overrides[get_now] = lambda: NOW
    app.dependency_overrides[get_daily_provider] = lambda: provider_for(
        load("yahoo_tcs_ns_2018.json")
    )
    yield client
    app.dependency_overrides.clear()


def test_watchlist_is_per_user_and_shows_prices(
    api: TestClient, admin: User, analyst: User
) -> None:
    ah = auth_header(api, admin.email)
    uh = auth_header(api, analyst.email)
    assert api.post("/stocks", headers=ah, json={"ticker": "TCS.NS"}).status_code == 201
    run = api.post(
        "/stocks/TCS.NS/ingest", headers=ah, json={"start": "2018-01-01", "end": "2018-12-31"}
    )
    assert run.status_code == 200, run.text

    assert api.get("/watchlist", headers=uh).json() == []
    assert api.post("/watchlist", headers=uh, json={"ticker": "INFY.NS"}).status_code == 404
    r = api.post("/watchlist", headers=uh, json={"ticker": "tcs.ns", "note": "IT bellwether"})
    assert r.status_code == 201, r.text
    row = r.json()
    assert row["ticker"] == "TCS.NS" and row["note"] == "IT bellwether"
    assert row["last_close"] is not None and row["prev_close"] is not None
    assert row["change_pct"] == pytest.approx(row["last_close"] / row["prev_close"] - 1)
    assert 1 < len(row["sparkline"]) <= 30
    assert row["sparkline"][-1] == row["last_close"]
    assert row["stance"] is None  # no research report yet: never invented

    assert api.post("/watchlist", headers=uh, json={"ticker": "TCS.NS"}).status_code == 409
    # another user's watchlist is separate
    assert api.get("/watchlist", headers=ah).json() == []
    assert [x["ticker"] for x in api.get("/watchlist", headers=uh).json()] == ["TCS.NS"]

    # the stocks list carries the same snapshot
    stocks = api.get("/stocks", headers=uh).json()
    assert stocks[0]["last_close"] == row["last_close"]
    assert len(stocks[0]["sparkline"]) == len(row["sparkline"])

    assert api.delete("/watchlist/TCS.NS", headers=uh).status_code == 204
    assert api.delete("/watchlist/TCS.NS", headers=uh).status_code == 404
    assert api.get("/watchlist", headers=uh).json() == []
    assert api.get("/watchlist").status_code == 401
