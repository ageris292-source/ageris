"""User features: named watchlists, price alerts, journal, activity log,
sign-out-everywhere, CSV exports and the paper performance scorecard."""

from __future__ import annotations

import csv
import io
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.alerts import price_rules
from app.api.routes.stocks import get_daily_provider, get_now
from app.main import app
from app.market_data.freshness import FreshnessResult
from app.models import AuditLog, MacroObservation, PortfolioSnapshot, PriceAlert, User
from tests.conftest import PASSWORD, auth_header
from tests.market_helpers import NOW, load, provider_for


@pytest.fixture
def api(client: TestClient, admin: User) -> Iterator[TestClient]:
    app.dependency_overrides[get_now] = lambda: NOW
    app.dependency_overrides[get_daily_provider] = lambda: provider_for(
        load("yahoo_tcs_ns_2018.json")
    )
    ah = auth_header(client, admin.email)
    assert client.post("/stocks", headers=ah, json={"ticker": "TCS.NS"}).status_code == 201
    run = client.post(
        "/stocks/TCS.NS/ingest", headers=ah, json={"start": "2018-01-01", "end": "2018-12-31"}
    )
    assert run.status_code == 200, run.text
    yield client
    app.dependency_overrides.clear()


def _fresh(monkeypatch: pytest.MonkeyPatch) -> None:
    """Pretend the 2018 fixture is today's data (freshness PASS)."""

    def fake(db: Session, stock: object, now: datetime, config: object = None) -> FreshnessResult:
        latest = price_rules.service.latest_session(db, stock)  # type: ignore[arg-type]
        return FreshnessResult("PASS", latest, latest, 0, "test")

    monkeypatch.setattr(price_rules.service, "freshness_for", fake)


# ------------------------------------------------------------------ watchlists


def test_named_watchlists(api: TestClient, admin: User, analyst: User) -> None:
    uh = auth_header(api, analyst.email)
    ah = auth_header(api, admin.email)
    lists = api.get("/watchlists", headers=uh).json()
    assert [w["name"] for w in lists] == ["My watchlist"]
    default = lists[0]["id"]

    banks = api.post("/watchlists", headers=uh, json={"name": "  Swing   ideas "})
    assert banks.status_code == 201 and banks.json()["name"] == "Swing ideas"
    bid = banks.json()["id"]
    assert api.post("/watchlists", headers=uh, json={"name": "swing IDEAS"}).status_code == 409

    assert api.post("/watchlist", headers=uh, json={"ticker": "TCS.NS"}).status_code == 201
    r = api.post("/watchlist", headers=uh, json={"ticker": "TCS.NS", "list_id": bid})
    assert r.status_code == 201 and r.json()["list_id"] == bid
    assert sorted(api.get("/watchlist/membership/TCS.NS", headers=uh).json()) == sorted(
        [default, bid]
    )
    assert [x["ticker"] for x in api.get(f"/watchlist?list_id={bid}", headers=uh).json()] == [
        "TCS.NS"
    ]
    counts = {w["id"]: w["count"] for w in api.get("/watchlists", headers=uh).json()}
    assert counts == {default: 1, bid: 1}

    # another user can't see or change someone else's list
    assert api.get(f"/watchlist?list_id={bid}", headers=ah).status_code == 404
    assert api.patch(f"/watchlists/{bid}", headers=ah, json={"name": "x"}).status_code == 404

    assert api.patch(f"/watchlists/{bid}", headers=uh, json={"name": "Banks"}).json()["name"] == (
        "Banks"
    )
    assert api.delete(f"/watchlist/TCS.NS?list_id={bid}", headers=uh).status_code == 204
    assert api.delete(f"/watchlists/{bid}", headers=uh).status_code == 204
    assert api.delete(f"/watchlists/{default}", headers=uh).status_code == 409  # last one


# ------------------------------------------------------------------ price alerts


def test_price_alerts_fire_once_for_the_owner_only(
    api: TestClient, admin: User, analyst: User, db: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    uh = auth_header(api, analyst.email)
    ah = auth_header(api, admin.email)
    last = api.get("/stocks/TCS.NS", headers=uh).json()["latest_bar"]["close"]
    last = float(last)

    bad = {"ticker": "TCS.NS", "condition": "rsi_above", "threshold": 150}
    assert api.post("/price-alerts", headers=uh, json=bad).status_code == 422
    assert (
        api.post(
            "/price-alerts", headers=uh, json={"ticker": "TCS.NS", "condition": "x", "threshold": 1}
        ).status_code
        == 422
    )

    above = api.post(
        "/price-alerts",
        headers=uh,
        json={"ticker": "TCS.NS", "condition": "price_above", "threshold": last - 1, "note": "hi"},
    ).json()
    below = api.post(
        "/price-alerts",
        headers=uh,
        json={"ticker": "TCS.NS", "condition": "price_below", "threshold": last - 1},
    ).json()
    rsi_rule = api.post(
        "/price-alerts",
        headers=uh,
        json={"ticker": "TCS.NS", "condition": "rsi_above", "threshold": 1, "repeat": True},
    ).json()
    assert above["description"].startswith("closes above ₹")

    # stale data (2018 bars judged in 2026): nothing is checked, nothing fires
    r = api.post("/price-alerts/check", headers=uh).json()
    assert r["fired"] == 0
    assert all(x["status"].startswith("not checked: price data") for x in r["results"])

    _fresh(monkeypatch)
    r = api.post("/price-alerts/check", headers=uh).json()
    fired = {x["id"] for x in r["results"] if x["fired"]}
    assert fired == {above["id"], rsi_rule["id"]}
    rsi_val = next(x["value"] for x in r["results"] if x["id"] == rsi_rule["id"])
    assert 0 < rsi_val < 100

    rules = {x["id"]: x for x in api.get("/price-alerts", headers=uh).json()}
    assert rules[above["id"]]["is_active"] is False  # one-shot
    assert rules[above["id"]]["trigger_count"] == 1
    assert rules[below["id"]]["is_active"] is True and rules[below["id"]]["trigger_count"] == 0
    assert rules[rsi_rule["id"]]["is_active"] is True and rules[rsi_rule["id"]]["armed"] is False

    # a second check on the same close does nothing
    again = api.post("/price-alerts/check", headers=uh).json()
    assert again["fired"] == 0

    mine = api.get("/alerts", headers=uh).json()
    kinds = [a for a in mine["alerts"] if a["personal"]]
    assert len(kinds) == 2 and all("does not trade" in a["body"] for a in kinds)
    assert mine["unread"] == 2
    # the admin does not see the analyst's personal alerts
    theirs = api.get("/alerts", headers=ah).json()
    assert theirs["unread"] == 0 and theirs["alerts"] == []
    aid = kinds[0]["id"]
    assert api.post(f"/alerts/{aid}/read", headers=ah).status_code == 404
    assert api.post("/alerts/read-all", headers=ah).json()["marked"] == 0
    assert api.post("/alerts/read-all", headers=uh).json()["marked"] == 2

    # repeating rule re-arms once the condition clears
    rule = db.get(PriceAlert, rsi_rule["id"])
    assert rule is not None
    rule.threshold = 99  # type: ignore[assignment]
    rule.last_session = None
    db.commit()
    res = price_rules.check_rule(db, rule, NOW)
    db.commit()
    assert not res.fired and rule.armed is True

    # the owner can edit and delete; others can't
    assert api.patch(f"/price-alerts/{below['id']}", headers=ah, json={}).status_code == 404
    p = api.patch(
        f"/price-alerts/{below['id']}", headers=uh, json={"importance": "high", "is_active": False}
    ).json()
    assert p["importance"] == "high" and p["is_active"] is False
    assert api.delete(f"/price-alerts/{below['id']}", headers=uh).status_code == 204
    assert api.delete(f"/price-alerts/{below['id']}", headers=uh).status_code == 404


# ------------------------------------------------------------------ journal


def test_journal_is_private_and_audit_holds_no_text(
    api: TestClient, admin: User, analyst: User, db: Session
) -> None:
    uh = auth_header(api, analyst.email)
    ah = auth_header(api, admin.email)
    e = api.post(
        "/journal",
        headers=uh,
        json={
            "ticker": "tcs.ns",
            "kind": "entry",
            "title": "Why TCS",
            "body": "Secret thesis: margins recover",
            "tags": ["IT", " it ", "Large Cap"],
        },
    )
    assert e.status_code == 201, e.text
    entry = e.json()
    assert entry["ticker"] == "TCS.NS" and entry["tags"] == ["it", "large cap"]
    api.post("/journal", headers=uh, json={"body": "general market note"})

    assert len(api.get("/journal", headers=uh).json()) == 2
    assert [x["id"] for x in api.get("/journal?ticker=TCS.NS", headers=uh).json()] == [entry["id"]]
    assert len(api.get("/journal?q=margins", headers=uh).json()) == 1
    assert len(api.get("/journal?tag=it", headers=uh).json()) == 1
    assert len(api.get("/journal?kind=note", headers=uh).json()) == 1
    assert api.get("/journal", headers=ah).json() == []
    assert api.patch(f"/journal/{entry['id']}", headers=ah, json={"body": "x"}).status_code == 404
    assert api.post("/journal", headers=uh, json={"order_id": 999999, "body": "x"}).status_code == (
        404
    )

    upd = api.patch(f"/journal/{entry['id']}", headers=uh, json={"kind": "review", "tags": []})
    assert upd.json()["kind"] == "review" and upd.json()["tags"] == []

    logs = db.scalars(select(AuditLog).where(AuditLog.action.like("journal.%"))).all()
    assert logs and all("Secret" not in str(a.details) for a in logs)
    assert api.delete(f"/journal/{entry['id']}", headers=uh).status_code == 204


# ------------------------------------------------------------------ activity & security


def test_activity_scope_sign_ins_and_logout_everywhere(
    client: TestClient, admin: User, analyst: User
) -> None:
    bad = client.post("/auth/token", data={"username": analyst.email, "password": "nope"})
    assert bad.status_code == 401
    uh = auth_header(client, analyst.email)
    ah = auth_header(client, admin.email)

    mine = client.get("/activity", headers=uh).json()
    assert mine["scope"] == "me"
    assert {i["actor_email"] for i in mine["items"]} == {analyst.email}
    everyone = client.get("/activity", headers=ah).json()
    assert everyone["scope"] == "all"
    assert {analyst.email, admin.email} <= {i["actor_email"] for i in everyone["items"]}
    only_auth = client.get("/activity?action=auth", headers=ah).json()["items"]
    assert only_auth and all(i["action"].startswith("auth.") for i in only_auth)
    page = client.get("/activity?limit=1", headers=ah).json()
    assert len(page["items"]) == 1 and page["next_before_id"] is not None

    s = client.get("/auth/sessions", headers=uh).json()
    actions = [i["action"] for i in s["items"]]
    assert "auth.login" in actions and "auth.login_failed" in actions
    assert s["failed_recent"] == 1

    r = client.post("/auth/logout-all", headers=uh)
    assert r.status_code == 200
    fresh = {"Authorization": f"Bearer {r.json()['access_token']}"}
    assert client.get("/auth/me", headers=uh).status_code == 401  # old session ended
    assert client.get("/auth/me", headers=fresh).status_code == 200
    assert client.post("/auth/token", data={"username": analyst.email, "password": PASSWORD})


# ------------------------------------------------------------------ exports


def test_csv_exports(api: TestClient, analyst: User, admin: User) -> None:
    uh = auth_header(api, analyst.email)
    api.post("/watchlist", headers=uh, json={"ticker": "TCS.NS", "note": "=HYPERLINK(1)"})
    api.post("/journal", headers=uh, json={"body": "-not a number", "title": "@cmd"})

    r = api.get("/export/watchlist.csv", headers=uh)
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/csv")
    assert "attachment" in r.headers["content-disposition"]
    rows = list(csv.reader(io.StringIO(r.text)))
    assert rows[0][:2] == ["list", "ticker"] and rows[1][1] == "TCS.NS"
    assert rows[1][4] == "'=HYPERLINK(1)"  # formula neutralised

    j = list(csv.reader(io.StringIO(api.get("/export/journal.csv", headers=uh).text)))
    assert j[1][6] == "'@cmd" and j[1][8] == "'-not a number"

    assert api.get("/export/positions.csv", headers=uh).status_code == 422
    assert api.get("/export/nope.csv", headers=uh).status_code == 422
    act = list(csv.reader(io.StringIO(api.get("/export/activity.csv", headers=uh).text)))
    assert act[0][0] == "id" and all(r[2] == analyst.email for r in act[1:])
    assert api.get("/export/orders.csv").status_code == 401


# ------------------------------------------------------------------ paper performance


def test_paper_performance_against_benchmark(client: TestClient, admin: User, db: Session) -> None:
    h = auth_header(client, admin.email)
    pid = client.post(
        "/portfolios", headers=h, json={"name": "Paper", "kind": "paper", "cash": "1000000"}
    ).json()["id"]

    empty = client.get(f"/paper/portfolios/{pid}/performance", headers=h).json()
    assert empty["trades"]["win_rate"] is None  # no closed trades: unknown, not 0%
    assert empty["equity"]["total_return"] is None
    assert empty["benchmark"]["available"] is False

    today = datetime.now(UTC)
    start = today.date() + timedelta(days=1)
    for i, eq in enumerate([1_000_000, 1_050_000, 980_000, 1_100_000]):
        db.add(
            PortfolioSnapshot(
                portfolio_id=pid,
                taken_at=datetime.combine(start + timedelta(days=i), datetime.min.time(), UTC)
                + timedelta(hours=12),
                equity=eq,
                cash=eq,
                invested=0,
                source="test",
            )
        )
    for i, v in enumerate([20_000, 20_400, 20_200, 21_000]):
        d = start + timedelta(days=i)
        db.add(
            MacroObservation(
                series="nifty50",
                frequency="daily",
                period_date=d,
                value=v,
                unit="index",
                source="test",
                licensed=False,
                retrieved_at=today,
                published_at=None,
                available_at=today,
                availability_estimated=False,
            )
        )
    db.commit()

    later = start + timedelta(days=10)
    app.dependency_overrides[get_now] = lambda: datetime.combine(later, datetime.min.time(), UTC)
    try:
        p = client.get(f"/paper/portfolios/{pid}/performance", headers=h).json()
    finally:
        app.dependency_overrides.clear()
    assert p["equity"]["total_return"] == pytest.approx(0.10)
    assert p["equity"]["max_drawdown"] == pytest.approx(980_000 / 1_050_000 - 1)
    assert p["benchmark"]["available"] is True
    # benchmark is indexed at the first date it exists (start), portfolio at creation
    assert p["benchmark"]["return"] == pytest.approx(21_000 / 20_000 - 1)
    assert p["benchmark"]["excess_return"] == pytest.approx(0.10 - 0.05)
    assert p["curve"][-1]["portfolio_index"] == pytest.approx(110.0)
    assert client.get("/paper/portfolios/999999/performance", headers=h).status_code == 404
