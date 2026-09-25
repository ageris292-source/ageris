"""Market-data ingestion + API against real Postgres, with recorded provider
responses. Covers versioning, conflict preservation, point-in-time reads,
immutability, fail-closed provider errors and CSV import."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import datetime, timedelta
from decimal import Decimal

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from app.api.routes.stocks import get_daily_provider, get_now
from app.main import app
from app.models import AuditLog, DataConflict, Price, User
from tests.conftest import auth_header
from tests.market_helpers import NOW, load, provider_for, with_close

Y2018 = {"start": "2018-01-01", "end": "2018-12-31"}


@pytest.fixture
def api(client: TestClient) -> Iterator[TestClient]:
    app.dependency_overrides[get_now] = lambda: NOW
    app.dependency_overrides[get_daily_provider] = lambda: provider_for(
        load("yahoo_tcs_ns_2018.json")
    )
    yield client
    app.dependency_overrides.clear()


def use_payload(payload: dict, **kw: object) -> None:  # type: ignore[type-arg]
    app.dependency_overrides[get_daily_provider] = lambda: provider_for(payload, **kw)  # type: ignore[arg-type]


@pytest.fixture
def admin_h(api: TestClient, admin: User) -> dict[str, str]:
    return auth_header(api, admin.email)


@pytest.fixture
def analyst_h(api: TestClient, analyst: User) -> dict[str, str]:
    return auth_header(api, analyst.email)


def add(api: TestClient, h: dict[str, str], ticker: str = "TCS.NS") -> None:
    r = api.post("/stocks", headers=h, json={"ticker": ticker})
    assert r.status_code == 201, r.text


def test_universe_management(api: TestClient, admin_h: dict, analyst_h: dict) -> None:  # type: ignore[type-arg]
    assert api.post("/stocks", headers=analyst_h, json={"ticker": "TCS.NS"}).status_code == 403
    add(api, admin_h)
    add(api, admin_h)  # idempotent
    for bad in ("AAPL", "TCS", "MSFT.US"):
        assert api.post("/stocks", headers=admin_h, json={"ticker": bad}).status_code == 422
    rows = api.get("/stocks", headers=analyst_h).json()
    assert [r["ticker"] for r in rows] == ["TCS.NS"]
    assert rows[0]["freshness"]["status"] == "FAIL"  # nothing ingested yet
    assert api.get("/stocks/INFY.NS", headers=analyst_h).status_code == 404


def test_ingest_stores_provenance_and_validates(
    api: TestClient,
    admin_h: dict,
    analyst_h: dict,
    db: Session,  # type: ignore[type-arg]
) -> None:
    add(api, admin_h)
    run = api.post("/stocks/TCS.NS/ingest", headers=analyst_h, json=Y2018).json()
    # 2018-11-07 was the Diwali Muhurat session: excluded with a warning.
    assert run["status"] == "succeeded_with_warnings"
    assert run["usable"] is True and run["licensed"] is False
    assert run["rows_received"] == 246 and run["rows_inserted"] == 245
    assert run["rows_rejected"] == 1
    assert run["basis"] == "split_adjusted"
    codes = {i["code"] for i in run["validation_report"]["issues"]}
    assert "non_calendar_session_excluded" in codes

    p = db.scalars(select(Price).order_by(Price.session_date)).first()
    assert p is not None
    assert (p.source, p.licensed, p.data_version, p.basis) == ("yahoo", False, 1, "split_adjusted")
    assert p.effective_at.isoformat() == "2018-01-01T10:00:00+00:00"  # 15:30 IST close
    assert p.available_at - p.effective_at == timedelta(minutes=60)
    assert p.published_at is None  # source does not state it; never invented

    detail = api.get("/stocks/TCS.NS", headers=analyst_h).json()
    assert detail["name"] == "Tata Consultancy Services Limited"
    assert detail["licensing_notice"] and "research only" in detail["licensing_notice"]
    assert detail["freshness"]["status"] == "FAIL"  # 2018 data is years stale
    assert detail["data_quality"]["usable"] is True
    assert {a["kind"] for a in detail["corporate_actions"]} == {"split", "dividend"}
    assert db.scalar(select(AuditLog).where(AuditLog.action == "market_data.ingest")) is not None


def test_reingest_is_idempotent(api: TestClient, admin_h: dict) -> None:  # type: ignore[type-arg]
    add(api, admin_h)
    api.post("/stocks/TCS.NS/ingest", headers=admin_h, json=Y2018)
    again = api.post("/stocks/TCS.NS/ingest", headers=admin_h, json=Y2018).json()
    assert (again["rows_inserted"], again["rows_revised"], again["rows_unchanged"]) == (0, 0, 245)


def test_revision_creates_new_version_and_preserves_conflict(
    api: TestClient,
    admin_h: dict,
    db: Session,  # type: ignore[type-arg]
) -> None:
    add(api, admin_h)
    first = api.post("/stocks/TCS.NS/ingest", headers=admin_h, json=Y2018).json()
    original = load("yahoo_tcs_ns_2018.json")
    use_payload(with_close(original, 100, 1234.5))
    second = api.post("/stocks/TCS.NS/ingest", headers=admin_h, json=Y2018).json()
    assert second["rows_revised"] == 1 and second["rows_inserted"] == 0

    conflict = db.scalars(select(DataConflict)).one()
    assert (conflict.previous_version, conflict.new_version) == (1, 2)
    assert conflict.new_value["close"] == "1234.5"
    assert conflict.previous_value["close"] != conflict.new_value["close"]

    session = conflict.key.split(":")[1]
    latest = api.get(
        "/stocks/TCS.NS/prices", headers=admin_h, params={"start": session, "end": session}
    ).json()["bars"][0]
    assert (latest["close"], latest["data_version"]) == ("1234.5000", 2)

    # Point-in-time: as of the first retrieval, only version 1 existed.
    as_of = datetime.fromisoformat(first["retrieved_at"]) + timedelta(microseconds=1)
    pit = api.get(
        "/stocks/TCS.NS/prices",
        headers=admin_h,
        params={"start": session, "end": session, "as_of": as_of.isoformat()},
    ).json()["bars"][0]
    assert pit["data_version"] == 1 and pit["close"] != "1234.5000"


def test_stored_prices_are_immutable(api: TestClient, admin_h: dict, db: Session) -> None:  # type: ignore[type-arg]
    add(api, admin_h)
    api.post("/stocks/TCS.NS/ingest", headers=admin_h, json=Y2018)
    for stmt in ("UPDATE prices SET close = close + 1", "DELETE FROM prices"):
        with pytest.raises(DBAPIError, match="immutable"):
            db.execute(text(stmt))
        db.rollback()


def test_provider_failure_fails_closed_and_is_audited(
    api: TestClient,
    admin_h: dict,
    db: Session,  # type: ignore[type-arg]
) -> None:
    add(api, admin_h)
    use_payload({}, exc=httpx.ConnectError("down"))
    run = api.post("/stocks/TCS.NS/ingest", headers=admin_h, json=Y2018).json()
    assert run["status"] == "failed" and run["usable"] is False
    assert "unreachable" in run["error"]
    assert db.scalar(select(Price).limit(1)) is None
    assert db.scalar(select(AuditLog).where(AuditLog.action == "market_data.ingest_failed"))


def test_price_basis_conversion_and_refusal(api: TestClient, admin_h: dict) -> None:  # type: ignore[type-arg]
    add(api, admin_h)
    api.post("/stocks/TCS.NS/ingest", headers=admin_h, json=Y2018)
    q = {"start": "2018-01-01", "end": "2018-12-31"}
    sa = api.get("/stocks/TCS.NS/prices", headers=admin_h, params=q).json()
    tr = api.get(
        "/stocks/TCS.NS/prices", headers=admin_h, params={**q, "basis": "total_return"}
    ).json()
    assert sa["derived"] is False and tr["derived"] is True
    assert tr["stored_basis"] == "split_adjusted"
    assert Decimal(tr["bars"][0]["close"]) < Decimal(sa["bars"][0]["close"])
    assert tr["bars"][-1]["close"] == sa["bars"][-1]["close"]
    raw = api.get("/stocks/TCS.NS/prices", headers=admin_h, params={**q, "basis": "raw"})
    assert raw.status_code == 422 and "cannot derive" in raw.json()["detail"]
    naive = api.get(
        "/stocks/TCS.NS/prices", headers=admin_h, params={**q, "as_of": "2020-01-01T00:00:00"}
    )
    assert naive.status_code == 422


def test_recent_data_is_fresh(api: TestClient, admin_h: dict) -> None:  # type: ignore[type-arg]
    add(api, admin_h)
    use_payload(load("yahoo_tcs_ns_recent.json"))
    run = api.post(
        "/stocks/TCS.NS/ingest", headers=admin_h, json={"start": "2026-08-01", "end": "2026-09-25"}
    ).json()
    assert run["usable"] is True
    fresh = api.get("/stocks/TCS.NS", headers=admin_h).json()["freshness"]
    assert fresh == {
        "status": "PASS",
        "latest_session": "2026-09-25",
        "expected_session": "2026-09-25",
        "sessions_behind": 0,
        "reason": "latest completed session stored",
    }


CSV_OK = (
    "date,open,high,low,close,volume\n"
    "2026-09-24,100,101,99,100.5,10\n"
    "2026-09-25,100.5,102,100,101,12\n"
)


def test_csv_import(api: TestClient, admin_h: dict, analyst_h: dict, db: Session) -> None:  # type: ignore[type-arg]
    add(api, admin_h, "INFY.NS")
    files = {"file": ("infy.csv", CSV_OK, "text/csv")}
    form = {"source": "licensed-vendor-x", "basis": "raw"}
    assert (
        api.post(
            "/stocks/INFY.NS/import-csv", headers=analyst_h, files=files, data=form
        ).status_code
        == 403
    )
    run = api.post("/stocks/INFY.NS/import-csv", headers=admin_h, files=files, data=form).json()
    assert run["provider"] == "csv:licensed-vendor-x" and run["licensed"] is True
    assert run["rows_inserted"] == 2 and run["basis"] == "raw"

    bad = "date,open,high,low,close,volume\n2026-09-24,100,101,99,oops,10\n"
    r = api.post(
        "/stocks/INFY.NS/import-csv",
        headers=admin_h,
        files={"file": ("bad.csv", bad, "text/csv")},
        data=form,
    )
    assert r.status_code == 422 and "line 2" in r.json()["detail"]
    missing = api.post(
        "/stocks/INFY.NS/import-csv",
        headers=admin_h,
        files={"file": ("m.csv", "date,close\n2026-09-24,1\n", "text/csv")},
        data=form,
    )
    assert missing.status_code == 422 and "missing required columns" in missing.json()["detail"]


def test_provider_status(api: TestClient, analyst_h: dict) -> None:  # type: ignore[type-arg]
    rows = {p["name"]: p for p in api.get("/data/providers", headers=analyst_h).json()}
    assert rows["yahoo"]["licensed"] is False and rows["yahoo"]["available"] is True
    assert rows["csv_import"]["licensed"] is True


def test_market_endpoints_require_auth(api: TestClient) -> None:
    for path in ("/stocks", "/stocks/TCS.NS", "/stocks/TCS.NS/prices", "/data/providers"):
        assert api.get(path).status_code == 401
    assert api.post("/stocks/TCS.NS/ingest").status_code == 401
