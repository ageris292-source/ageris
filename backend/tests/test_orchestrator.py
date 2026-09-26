"""Phase 8: bull/bear synthesis, narrative guard, orchestrated reports."""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from datetime import UTC, datetime

import httpx
import pytest
from fastapi.testclient import TestClient
from hypothesis import given, settings
from hypothesis import strategies as st
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from app.agents.base import AgentOutput, AgentStatus, Evidence, Signal
from app.api.routes.stocks import get_now
from app.core.config_file import get_config
from app.main import app
from app.models import AgentRun, AnalysisReport, User
from app.orchestrator import narrative as nv
from app.orchestrator.synthesis import synthesize
from tests.conftest import auth_header
from tests.market_helpers import NOW
from tests.test_risk_portfolio import CALM, MKT, _seed_benchmark, _seed_stock

RULES = get_config().orchestrator
T0 = datetime(2026, 9, 1, tzinfo=UTC)


def _out(
    agent: str,
    score: float | None,
    *,
    conf: float = 0.5,
    sigs: list[Signal] | None = None,
    status: AgentStatus = AgentStatus.OK,
    risks: list[str] | None = None,
) -> AgentOutput:
    ok = status is AgentStatus.OK
    return AgentOutput(
        agent=agent,
        agent_version=f"{agent}-1",
        ticker="TCS.NS",
        as_of=T0,
        knowledge_at=T0,
        generated_at=T0,
        status=status,
        score=score if ok else None,
        score_basis="x",
        confidence=conf if ok else 0.0,
        confidence_basis="heuristic_uncalibrated" if ok else "none",
        signals=(sigs or []) if ok else [],
        evidence=[Evidence(ref=f"{agent}:ref", description="d")],
        risks=risks or [],
        data_quality=1.0,
        data_snapshot_id="s" * 64,
        config_fingerprint="f",
        warnings=[] if ok else ["no data"],
    )


def _sig(name: str, direction: str, strength: float) -> Signal:
    return Signal(name=name, category="c", direction=direction, strength=strength, detail=name)  # type: ignore[arg-type]


def test_stance_and_composite() -> None:
    outs = {a: _out(a, 70) for a in ("technical", "fundamental", "valuation", "risk")}
    s = synthesize(outs, RULES)
    assert s["stance"] == "POSITIVE_TILT" and s["composite_score"] == 70
    assert s["decision"]["trade"] == "NO TRADE"
    outs = {a: _out(a, 55) for a in ("technical", "fundamental", "valuation", "risk")}
    assert synthesize(outs, RULES)["stance"] == "NO_CLEAR_TILT"
    outs = {a: _out(a, 30) for a in ("technical", "fundamental", "valuation", "risk")}
    assert synthesize(outs, RULES)["stance"] == "NEGATIVE_TILT"


def test_insufficient_when_required_missing_or_too_few() -> None:
    outs = {a: _out(a, 80) for a in ("technical", "fundamental", "valuation", "news")}
    outs["risk"] = _out("risk", None, status=AgentStatus.INSUFFICIENT_DATA)
    s = synthesize(outs, RULES)
    assert s["stance"] == "INSUFFICIENT_DATA"
    assert any("risk" in r for r in s["insufficient_reasons"])
    few = synthesize({"risk": _out("risk", 90), "technical": _out("technical", 90)}, RULES)
    assert few["stance"] == "INSUFFICIENT_DATA"
    assert any(w["agent"] == "risk" for w in s["data_warnings"])


def test_weights_renormalise_over_usable_agents() -> None:
    outs = {
        "technical": _out("technical", 80),
        "fundamental": _out("fundamental", 40),
        "risk": _out("risk", 60),
        "news": _out("news", 50),
        "valuation": _out("valuation", None, status=AgentStatus.FAILED),
    }
    w = RULES.agent_weights
    expect = (80 * w["technical"] + 40 * w["fundamental"] + 60 * w["risk"] + 50 * w["news"]) / (
        w["technical"] + w["fundamental"] + w["risk"] + w["news"]
    )
    s = synthesize(outs, RULES)
    assert s["composite_score"] == pytest.approx(round(expect, 2))
    assert s["coverage"] == pytest.approx(1 - w["valuation"] / sum(w[a] for a in outs), abs=1e-4)


def test_bull_bear_cases_and_conflicts() -> None:
    outs = {
        "technical": _out(
            "technical", 20, sigs=[_sig("trend_down", "bearish", 1.0), _sig("rsi", "bullish", 0.2)]
        ),
        "fundamental": _out(
            "fundamental", 80, sigs=[_sig("roe", "bullish", 0.9), _sig("flat", "neutral", 0.0)]
        ),
        "risk": _out("risk", 50, risks=["Deep drawdown"]),
        "news": _out("news", 50, risks=["Deep drawdown"]),
    }
    s = synthesize(outs, RULES)
    assert [p["signal"] for p in s["bull_case"]] == ["roe", "rsi"]  # ranked by strength x weight
    assert [p["signal"] for p in s["bear_case"]] == ["trend_down"]
    assert s["bull_case"][0]["evidence"] == "fundamental:ref"
    assert len(s["conflicts"]) == 1 and s["conflicts"][0]["agents"] == ["fundamental", "technical"]
    assert [r["risk"] for r in s["key_risks"]] == ["Deep drawdown"]  # de-duplicated
    calm = {**outs, "technical": _out("technical", 45), "fundamental": _out("fundamental", 55)}
    assert synthesize(calm, RULES)["confidence"] > s["confidence"]  # conflict penalty


@settings(max_examples=100, deadline=None)
@given(st.lists(st.one_of(st.none(), st.floats(0, 100)), min_size=7, max_size=7))
def test_synthesis_properties(scores: list[float | None]) -> None:
    names = ["technical", "fundamental", "valuation", "risk", "news", "macro", "portfolio"]
    outs = {
        n: _out(n, s) if s is not None else _out(n, None, status=AgentStatus.INSUFFICIENT_DATA)
        for n, s in zip(names, scores, strict=True)
    }
    a, b = synthesize(outs, RULES), synthesize(outs, RULES)
    assert a == b  # deterministic
    c = a["composite_score"]
    assert c is None or 0 <= c <= 100
    assert 0 <= a["confidence"] <= 1
    assert a["decision"]["trade"] == "NO TRADE"
    if a["stance"] == "POSITIVE_TILT":
        assert c is not None and c >= 50 + RULES.stance_band
    if outs["risk"].status is not AgentStatus.OK:
        assert a["stance"] == "INSUFFICIENT_DATA"


# --------------------------------------------------------------- narrative --

FACTS = "Composite 46.2/100. Volatility 21.4%. Price ₹1,234.50 on 2026-09-25. Decision: NO TRADE."


def test_narrative_guard() -> None:
    assert nv.validate_narrative("Composite 46.2 with volatility 21.4% at ₹1234.5.", FACTS) == []
    bad = nv.validate_narrative("Composite 46.2 and 12% upside expected.", FACTS)
    assert bad and "12" in bad[0]
    assert nv.validate_narrative("A strong buy here.", FACTS)
    assert nv.validate_narrative("  ", FACTS) == ["empty narrative"]


def _mock_narrator(reply: str | None, code: int = 200) -> nv.AnthropicNarrator:
    def handler(req: httpx.Request) -> httpx.Response:
        assert req.headers["x-api-key"] == "k"
        return httpx.Response(code, json={"content": [{"type": "text", "text": reply or ""}]})

    return nv.AnthropicNarrator("k", "m", transport=httpx.MockTransport(handler))


def test_llm_narrator_is_validated() -> None:
    report = {
        "ticker": "TCS.NS",
        "synthesis": {
            "stance_text": "No clear tilt",
            "composite_score": 46.2,
            "confidence": 0.3,
            "insufficient_reasons": [],
            "bull_case": [],
            "bear_case": [],
            "conflicts": [],
            "key_risks": [],
        },
    }
    good = nv.narrate(report, FACTS, _mock_narrator("No clear tilt at 46.2; NO TRADE."))
    assert good["source"] == "llm:anthropic" and good["warnings"] == []
    hallucinated = nv.narrate(report, FACTS, _mock_narrator("Expect 30% gains by 2027."))
    assert hallucinated["source"] == "deterministic"
    assert "rejected" in hallucinated["warnings"][0]
    down = nv.narrate(report, FACTS, _mock_narrator(None, code=500))
    assert down["source"] == "deterministic" and "failed" in down["warnings"][0]
    assert nv.narrate(report, FACTS, None)["source"] == "deterministic"


# -------------------------------------------------------------- end-to-end --


@pytest.fixture
def api(client: TestClient, admin: User) -> Iterator[tuple[TestClient, dict[str, str]]]:
    app.dependency_overrides[get_now] = lambda: NOW
    h = auth_header(client, admin.email)
    yield client, h
    app.dependency_overrides.clear()


def test_full_analysis_report(api: tuple[TestClient, dict[str, str]], db: Session) -> None:
    client, h = api
    _seed_benchmark(db, MKT)
    _seed_stock(db, "TCS.NS", CALM)
    r = client.post("/analysis/TCS.NS", headers=h, json={})
    assert r.status_code == 201, r.text
    rep = r.json()
    s = rep["synthesis"]
    agents = {a["agent"]: a["status"] for a in s["agents"]}
    assert set(agents) == {"technical", "fundamental", "valuation", "risk", "news", "macro"}
    assert agents["risk"] == "ok" and agents["technical"] == "ok"
    assert agents["fundamental"] == "insufficient_data"  # no financials ingested: fail closed
    assert s["stance"] == "INSUFFICIENT_DATA"  # only 3-4 agents usable (< min_agents_ok)
    assert s["decision"]["trade"] == "NO TRADE"
    assert rep["narrative"]["source"] == "deterministic"
    # every agent ran at the same point in time, and each run is linked
    runs = [db.get(AgentRun, uuid.UUID(i)) for i in rep["agent_run_ids"].values()]
    assert all(r is not None for r in runs)
    assert len({r.knowledge_at for r in runs if r}) == 1 and len({r.as_of for r in runs if r}) == 1

    got = client.get(f"/reports/{rep['report_id']}", headers=h).json()
    assert got["hash_verified"] and got["report_hash"] == rep["report_hash"]
    latest = client.get("/analysis/TCS.NS/latest", headers=h).json()
    assert latest["report_id"] == rep["report_id"]
    md = client.get(f"/reports/{rep['report_id']}/markdown", headers=h)
    assert md.status_code == 200 and md.headers["content-type"].startswith("text/markdown")
    for section in (
        "## 1. Decision",
        "**NO TRADE**",
        "## 4. Bull case",
        "## 5. Bear case",
        "## 12. Data quality",
        "## 13. Summary",
    ):
        assert section in md.text
    assert len(client.get("/analysis/TCS.NS/history", headers=h).json()) == 1
    # immutable
    with pytest.raises(DBAPIError):
        db.execute(text("UPDATE analysis_reports SET stance = 'POSITIVE_TILT'"))
        db.flush()
    db.rollback()
    assert db.query(AnalysisReport).count() == 1


def test_analysis_with_portfolio_and_errors(
    api: tuple[TestClient, dict[str, str]], db: Session
) -> None:
    client, h = api
    _seed_stock(db, "TCS.NS", CALM)
    pid = client.post("/portfolios", headers=h, json={"name": "Core", "cash": "1000000"}).json()[
        "id"
    ]
    rep = client.post(
        "/analysis/TCS.NS", headers=h, json={"portfolio_id": pid, "weight": 0.05}
    ).json()
    assert any(a["agent"] == "portfolio" for a in rep["synthesis"]["agents"])
    assert rep["portfolio_fit"]["portfolio_id"] == pid
    assert (
        client.post("/analysis/TCS.NS", headers=h, json={"portfolio_id": 99999}).status_code == 404
    )
    assert client.post("/analysis/NOPE.NS", headers=h, json={}).status_code == 404
    assert (
        client.post(
            "/analysis/TCS.NS", headers=h, json={"as_of": "2026-09-01T00:00:00"}
        ).status_code
        == 422
    )
    assert client.get("/narrator/status", headers=h).json()["available"] is False


def test_analysis_needs_auth(client: TestClient) -> None:
    assert client.post("/analysis/TCS.NS", json={}).status_code == 401
    for p in ("/analysis/TCS.NS/latest", "/reports/1", "/reports/1/markdown", "/narrator/status"):
        assert client.get(p).status_code == 401
