"""API behaviour: auth, kill switch, risk status, audit trail."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from app.models import AuditLog, RiskEvent, User
from tests.conftest import PASSWORD, auth_header


def test_health_reports_components(client: TestClient) -> None:
    body = client.get("/health").json()
    assert body["status"] == "ok"
    assert body["system_mode"] == "research"
    assert {c["name"]: c["healthy"] for c in body["components"]} == {
        "database": True,
        "redis": True,
    }


@pytest.mark.parametrize("path", ["/risk/status", "/auth/me"])
def test_protected_endpoints_require_auth(client: TestClient, path: str) -> None:
    assert client.get(path).status_code == 401
    bad = {"Authorization": "Bearer not-a-jwt"}
    assert client.get(path, headers=bad).status_code == 401


def test_kill_switch_requires_auth(client: TestClient) -> None:
    r = client.post("/trading/kill-switch", json={"active": True, "reason": "anonymous halt"})
    assert r.status_code == 401


def test_login_success_and_failure_are_audited(
    client: TestClient, analyst: User, db: Session
) -> None:
    ok = client.post("/auth/token", data={"username": analyst.email, "password": PASSWORD})
    assert ok.status_code == 200
    bad = client.post("/auth/token", data={"username": analyst.email, "password": "wrong-pass"})
    assert bad.status_code == 401
    unknown = client.post("/auth/token", data={"username": "ghost@x.io", "password": "whatever1"})
    assert unknown.status_code == 401
    actions = db.scalars(select(AuditLog.action)).all()
    assert actions.count("auth.login") == 1
    assert actions.count("auth.login_failed") == 2


def test_login_is_rate_limited(client: TestClient, analyst: User) -> None:
    codes = [
        client.post(
            "/auth/token", data={"username": analyst.email, "password": "nope-nope"}
        ).status_code
        for _ in range(12)
    ]
    assert codes[:10] == [401] * 10
    assert codes[10:] == [429, 429]


def test_me(client: TestClient, admin: User) -> None:
    r = client.get("/auth/me", headers=auth_header(client, admin.email))
    assert r.json() == {"email": "admin@aegis.test", "role": "admin"}


def test_risk_status_blocks_all_orders_in_default_build(client: TestClient, analyst: User) -> None:
    body = client.get("/risk/status", headers=auth_header(client, analyst.email)).json()
    assert body["system_mode"] == "research"
    assert body["live_orders_permitted"] is False
    assert body["paper_orders_permitted"] is False
    assert body["kill_switch"]["active"] is True  # fresh install starts halted
    assert any(r.startswith("kill_switch") for r in body["blocking_reasons"])
    assert len(body["config_fingerprint"]) == 64
    assert "not guarantees of profit" in body["disclaimer"]


def test_analyst_can_halt_but_not_resume(
    client: TestClient, admin: User, analyst: User, db: Session
) -> None:
    a = auth_header(client, analyst.email)
    h = auth_header(client, admin.email)

    resumed = client.post(
        "/trading/kill-switch",
        headers=h,
        json={"active": False, "reason": "admin reviewed initial state"},
    )
    assert resumed.status_code == 200 and resumed.json()["active"] is False

    halted = client.post(
        "/trading/kill-switch", headers=a, json={"active": True, "reason": "suspicious price feed"}
    )
    assert halted.status_code == 200 and halted.json()["active"] is True

    denied = client.post(
        "/trading/kill-switch",
        headers=a,
        json={"active": False, "reason": "analyst tries to resume"},
    )
    assert denied.status_code == 403
    status = client.get("/risk/status", headers=a).json()
    assert status["kill_switch"]["active"] is True
    assert status["kill_switch"]["reason"] == "suspicious price feed"

    actions = db.scalars(select(AuditLog.action).order_by(AuditLog.id)).all()
    assert [x for x in actions if x.startswith("kill_switch")] == [
        "kill_switch.deactivate",
        "kill_switch.activate",
        "kill_switch.deactivate_denied",
    ]
    events = db.scalars(select(RiskEvent).order_by(RiskEvent.id)).all()
    critical = [e for e in events if e.event_type == "kill_switch_activated"]
    assert len(critical) == 1 and critical[0].requires_review


def test_resuming_kill_switch_does_not_enable_trading(client: TestClient, admin: User) -> None:
    h = auth_header(client, admin.email)
    client.post("/trading/kill-switch", headers=h, json={"active": False, "reason": "resume ok"})
    body = client.get("/risk/status", headers=h).json()
    assert body["kill_switch"]["active"] is False
    assert body["live_orders_permitted"] is False  # research mode, no broker, no risk engine


def test_kill_switch_reason_is_required(client: TestClient, admin: User) -> None:
    h = auth_header(client, admin.email)
    r = client.post("/trading/kill-switch", headers=h, json={"active": True, "reason": ""})
    assert r.status_code == 422


@pytest.mark.parametrize(
    "stmt", ["UPDATE audit_logs SET action = 'x'", "DELETE FROM audit_logs", "TRUNCATE audit_logs"]
)
def test_audit_log_is_append_only(
    client: TestClient, analyst: User, db: Session, stmt: str
) -> None:
    auth_header(client, analyst.email)  # produces an audit row
    with pytest.raises(DBAPIError, match="append-only"):
        db.execute(text(stmt))
    db.rollback()
    assert db.scalar(select(AuditLog.id).limit(1)) is not None
