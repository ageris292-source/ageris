"""Phase 15: live-trading scaffolding stays disabled. Every layer is
checked on its own, including the case where all the others are bypassed."""

from __future__ import annotations

import re
import socket
from collections.abc import Iterator
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.routes.stocks import get_now
from app.core import modes
from app.core.modes import SystemMode
from app.core.settings import get_settings
from app.live import broker as lb
from app.live import service as live
from app.main import app
from app.models import Alert, AuditLog, PaperExecution, PaperOrder, User
from app.services.trading_controls import KillSwitchState, evaluate_execution_readiness
from app.trade import context as trade_context
from app.trade import service as trade_service
from app.trade.schemas import TradeProposal
from tests.conftest import auth_header
from tests.market_helpers import NOW

BACKEND = Path(__file__).resolve().parents[1]
LIVE = get_settings().model_copy(
    update={"system_mode": SystemMode.LIVE, "live_trading_enabled": True}
)


# ------------------------------------------------------------- build + adapter --


def test_build_has_no_live_broker(monkeypatch: pytest.MonkeyPatch) -> None:
    assert modes.LIVE_TRADING_AVAILABLE is False
    for var in ("AEGIS_BROKER", "AEGIS_LIVE_BROKER", "BROKER", "KITE_API_KEY"):
        monkeypatch.setenv(var, "zerodha")
    b = lb.get_broker()
    assert isinstance(b, lb.UnavailableBroker)  # nothing selects another adapter
    st = b.status()
    assert st.available is False and st.healthy is None and lb.readiness_status(b) == "UNKNOWN"
    order = lb.LiveOrderRequest(
        decision_id=1,
        idempotency_key="k" * 8,
        approved_by=__import__("uuid").uuid4(),
        ticker="TCS.NS",
        exchange="NSE",
        side="buy",
        quantity=1,
        limit_price=Decimal("1000"),
    )
    for call in (
        lambda: b.place_order(order),
        lambda: b.cancel_order("x"),
        lambda: b.order_status("x"),
        lambda: b.positions,
    ):
        with pytest.raises(lb.BrokerUnavailableError):
            r = call()
            if callable(r):
                r()


def test_no_broker_sdk_and_no_other_order_path() -> None:
    deps = (BACKEND / "pyproject.toml").read_text().lower()
    for sdk in ("kiteconnect", "smartapi", "upstox", "fyers", "dhanhq", "breeze", "angelone"):
        assert sdk not in deps
    callers = [
        str(p.relative_to(BACKEND))
        for p in (BACKEND / "app").rglob("*.py")
        if re.search(r"\.place_order\(", p.read_text())
    ]
    # the paper routes call paper.place_order; only app/live reaches a broker
    assert sorted(callers) == ["app/api/routes/paper.py", "app/live/service.py"]


# --------------------------------------------------------------- readiness --


def test_readiness_never_permits_live_orders(client: TestClient, admin: User) -> None:
    ks = KillSwitchState(active=False, reason="off", known=True)
    r = evaluate_execution_readiness(LIVE, ks, broker_status="PASS", risk_engine_status="PASS")
    assert r.live_orders_permitted is False
    assert r.blocking_reasons == ["live_build: live trading is not available in this build"]
    h = auth_header(client, admin.email)
    rs = client.get("/risk/status", headers=h).json()
    checks = {c["name"]: c["status"] for c in rs["checks"]}
    assert checks["live_build"] == "FAIL" and checks["broker_health"] == "UNKNOWN"
    assert rs["live_orders_permitted"] is False
    st = client.get("/live/status", headers=h).json()
    assert st["available"] is False and st["broker"] == "unavailable"
    assert st["live_orders_permitted"] is False


# ------------------------------------------------------------------ engine --


def test_engine_rejects_live_proposals_even_in_live_mode(
    db: Session, client: TestClient, admin: User, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(trade_context, "get_settings", lambda: LIVE)
    db.execute(text("UPDATE trading_controls SET kill_switch_active = false"))
    db.commit()
    pid = _paper_portfolio(client, auth_header(client, admin.email))
    p = TradeProposal(
        ticker="TCS.NS",
        side="buy",
        quantity=1,
        entry_price=Decimal("1000"),
        stop_loss=Decimal("950"),
        target=Decimal("1150"),
        horizon_days=20,
        portfolio_id=pid,
        mode="live",
    )
    d, _, _ = trade_service.submit(db, p, None, NOW)
    gates = {g.name: g for g in d.gates}
    assert d.decision == "REJECTED"
    assert gates["execution_mode"].status == "UNKNOWN"  # broker health from the adapter
    assert "broker health unknown" in gates["execution_mode"].reason
    assert gates["portfolio_match"].status == "FAIL"  # no live portfolio can exist


def _paper_portfolio(client: TestClient, h: dict[str, str]) -> int:
    r = client.post(
        "/portfolios", headers=h, json={"name": "Paper", "kind": "paper", "cash": "100000"}
    )
    assert r.status_code == 201, r.text
    return int(r.json()["id"])


def test_a_live_portfolio_cannot_exist(db: Session, client: TestClient, admin: User) -> None:
    r = client.post(
        "/portfolios",
        headers=auth_header(client, admin.email),
        json={"name": "Live", "kind": "live", "cash": "1000"},
    )
    assert r.status_code == 422
    with pytest.raises(IntegrityError):
        db.execute(
            text(
                "INSERT INTO portfolios (name, kind, cash, starting_cash, is_active) "
                "VALUES ('x', 'live', 1, 1, true)"
            )
        )
        db.flush()
    db.rollback()


# -------------------------------------------------------- the live order path --


@pytest.fixture
def forged(
    client: TestClient, admin: User, monkeypatch: pytest.MonkeyPatch
) -> Iterator[dict[str, Any]]:
    """Worst case: a defective engine APPROVES a live proposal."""
    real = trade_service.evaluate

    def approve_everything(*a: Any, **kw: Any) -> Any:
        d = real(*a, **kw)
        return d.model_copy(
            update={"decision": "APPROVED", "failed_gates": [], "first_failure": None}
        )

    monkeypatch.setattr(trade_service, "evaluate", approve_everything)
    monkeypatch.setattr(trade_context, "get_settings", lambda: LIVE)
    monkeypatch.setattr(live, "get_settings", lambda: LIVE)
    app.dependency_overrides[get_now] = lambda: NOW
    h = auth_header(client, admin.email)
    client.post("/trading/kill-switch", headers=h, json={"active": False, "reason": "test resume"})
    d = client.post(
        "/trade/proposals",
        headers=h,
        json={
            "ticker": "TCS.NS",
            "side": "buy",
            "quantity": 1,
            "entry_price": "1000",
            "stop_loss": "950",
            "target": "1150",
            "horizon_days": 20,
            "portfolio_id": _paper_portfolio(client, h),
            "mode": "live",
        },
    ).json()
    assert d["decision"] == "APPROVED"
    yield {"client": client, "h": h, "decision_id": d["decision_id"]}
    app.dependency_overrides.clear()


def _order(f: dict[str, Any], key: str = "live-key-0001", h: dict[str, str] | None = None) -> Any:
    return f["client"].post(
        "/live/orders",
        headers={**(h or f["h"]), "Idempotency-Key": key},
        json={"decision_id": f["decision_id"]},
    )


def test_even_an_approved_live_decision_is_refused(
    forged: dict[str, Any], db: Session, analyst: User
) -> None:
    r = _order(forged)
    assert r.status_code == 503
    detail = r.json()["detail"]
    assert detail["message"] == "live trading is not available in this build"
    assert any(x.startswith("live_build") for x in detail["reasons"])
    assert any(x.startswith("broker_health") for x in detail["reasons"])
    audit = db.scalars(select(AuditLog).where(AuditLog.action == "live.order.refused")).one()
    assert audit.entity_id == str(forged["decision_id"])
    assert db.scalars(select(Alert).where(Alert.kind == "live.order_refused")).one()
    # the paper path refuses it too, and nothing was filled anywhere
    paper = forged["client"].post(
        "/paper/orders",
        headers={**forged["h"], "Idempotency-Key": "paper-key-001"},
        json={"decision_id": forged["decision_id"]},
    )
    assert paper.status_code == 409 and "only paper orders" in paper.json()["detail"]
    assert db.query(PaperOrder).count() == 0 and db.query(PaperExecution).count() == 0
    # human approval: admin only, idempotency key required, unknown decision
    assert _order(forged, h=auth_header(forged["client"], analyst.email)).status_code == 403
    no_key = forged["client"].post(
        "/live/orders", headers=forged["h"], json={"decision_id": forged["decision_id"]}
    )
    assert no_key.status_code == 422
    missing = forged["client"].post(
        "/live/orders",
        headers={**forged["h"], "Idempotency-Key": "live-key-0002"},
        json={"decision_id": 999999},
    )
    assert missing.status_code == 404


def test_adapter_refuses_when_every_other_safeguard_is_bypassed(
    forged: dict[str, Any], db: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Bypass the build switch and readiness entirely ...
    monkeypatch.setattr(
        live,
        "status",
        lambda _db: live.LiveStatus(True, "unavailable", "", True, []),
    )
    reached: list[lb.LiveOrderRequest] = []
    real_place = lb.UnavailableBroker.place_order

    def spy(self: lb.UnavailableBroker, order: lb.LiveOrderRequest) -> Any:
        reached.append(order)
        return real_place(self, order)

    monkeypatch.setattr(lb.UnavailableBroker, "place_order", spy)

    def no_network(*_: Any, **__: Any) -> None:
        raise AssertionError("a network connection was attempted")

    monkeypatch.setattr(socket.socket, "connect", no_network)
    # ... the adapter itself still refuses, and nothing leaves the process.
    with pytest.raises(live.LiveOrderRefusedError) as exc:
        live.submit_live_order(
            db, forged["decision_id"], "bypass-key-01", db.scalars(select(User)).first(), NOW
        )
    assert len(reached) == 1 and reached[0].side == "buy" and reached[0].quantity == 1
    assert exc.value.reasons == [f"broker: {lb.UNAVAILABLE_REASON}"]


def test_live_endpoints_need_auth(client: TestClient) -> None:
    assert client.get("/live/status").status_code == 401
    assert client.post("/live/orders", json={"decision_id": 1}).status_code == 401
