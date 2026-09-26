"""Portfolio Agent (spec §14): how well a candidate fits a given portfolio.

Compares the portfolio before and after buying the candidate at a target
weight (funded from cash). Higher score = better fit. Any breached LIMIT
check is a maximal bearish signal; an UNKNOWN limit check makes the output
insufficient_data (fail closed: fit cannot be judged).
"""

from __future__ import annotations

import logging
import time
import uuid
from datetime import UTC, datetime
from typing import Any

import numpy as np
from sqlalchemy.orm import Session

from app.agents.base import AgentInput, AgentOutput, AgentStatus, Evidence, Signal
from app.agents.common import composite, new_input, not_ok, record_run, sig
from app.analysis import risk as rk
from app.core.config_file import get_config
from app.market_data import service as md
from app.market_data.types import Ticker
from app.models import Portfolio, Stock
from app.portfolio import service as ps
from app.risk import service as rs

log = logging.getLogger(__name__)

AGENT = "portfolio"
AGENT_VERSION = "portfolio-agent-1.0.0"
SCORE_BASIS = (
    "Portfolio fit 0-100: 50 = neutral. Limit breaches, diversification (correlation "
    "with the existing holdings), marginal volatility and sector room. Descriptive, "
    "not a probability."
)


def run_fit(
    db: Session, pf: Portfolio, stock: Stock, weight: float, inp: AgentInput
) -> tuple[AgentOutput, dict[str, Any]]:
    cfg = get_config()
    rules, rc = cfg.risk_analysis, cfg.risk_controls
    cache: dict[int, ps.Holding] = {}
    before = ps.analyze(db, pf, inp.as_of, inp.knowledge_at, _cache=cache)
    after = ps.analyze(db, pf, inp.as_of, inp.knowledge_at, (stock, weight), _cache=cache)
    details = {"before": before, "after": after}
    ev = [
        Evidence(
            ref=f"portfolio:{pf.id}:as_of={inp.as_of.isoformat()}",
            description=f"Portfolio '{pf.name}' with {len(before['holdings'])} holdings; "
            f"candidate {inp.ticker} at {weight:.1%} of equity",
        )
    ]
    cand = after["candidate"] or {}
    if cand.get("price") is None:
        return not_ok(
            AGENT,
            AGENT_VERSION,
            inp,
            AgentStatus.INSUFFICIENT_DATA,
            [f"No price for {inp.ticker} as of this date"],
            cfg,
            SCORE_BASIS,
            evidence=ev,
        ), details
    limits = [c for c in after["checks"] if c["kind"] == "limit"]
    unknown = [c for c in limits if c["status"] == "UNKNOWN"]
    if unknown:
        return not_ok(
            AGENT,
            AGENT_VERSION,
            inp,
            AgentStatus.INSUFFICIENT_DATA,
            [
                "Limit checks UNKNOWN after the trade: "
                + "; ".join(f"{c['name']}: {c['reason']}" for c in unknown)
            ],
            cfg,
            SCORE_BASIS,
            evidence=ev,
        ), details

    signals: list[Signal] = []
    risks: list[str] = []
    before_status = {c["name"]: c["status"] for c in before["checks"]}
    cand_sector = next((x["sector"] for x in after["holdings"] if x["candidate"]), None)
    failed: list[dict[str, Any]] = []
    pre_existing: list[dict[str, Any]] = []
    for c in (c for c in limits if c["status"] == "FAIL"):
        # A breach is attributed to the trade if the trade's stock/sector is an
        # offender, or the check passed before the trade (gross, cash).
        caused = (
            inp.ticker in c["offenders"]
            or (cand_sector is not None and cand_sector in c["offenders"])
            or before_status.get(c["name"]) != "FAIL"
        )
        (failed if caused else pre_existing).append(c)
    for c in failed:
        signals.append(
            sig(f"limit_{c['name']}", "limits", -1, 1.0, f"Breaches {c['name']}: {c['reason']}")
        )
        risks.append(f"Would breach {c['name'].replace('_', ' ')} limit ({c['reason']})")
    if not failed:
        signals.append(sig("limits", "limits", 1, 0.5, "The trade breaches no portfolio limit"))

    # Diversification: correlation of the candidate with the existing portfolio.
    h = rs.load_history(db, stock, inp.as_of, inp.knowledge_at, rules.lookback_sessions)
    existing = [x for x in before["holdings"] if x["ticker"] != inp.ticker]
    corr_pf: float | None = None
    if existing and before["metrics"].get("volatility_annual") is not None:
        series = {
            x.ticker: dict(x.history.closes)
            for x in cache.values()
            if not x.candidate and x.ticker != inp.ticker
        }
        mine = dict(h.closes)
        common = sorted(set(mine).intersection(*(set(v) for v in series.values())))
        if len(common) > rules.min_history_sessions // 2:
            w = {x["ticker"]: x["weight"] for x in existing}
            tot = sum(w.values())
            pr = sum(rk.returns([series[t][d] for d in common]) * (w[t] / tot) for t in series)
            cr = rk.returns([mine[d] for d in common])
            corr_pf = float(np.corrcoef(cr, pr)[0, 1])
    if corr_pf is not None:
        signals.append(
            sig(
                "diversification",
                "diversification",
                0.5 - corr_pf,
                min(1.0, abs(corr_pf - 0.5) * 2),
                f"Correlation with the existing portfolio {corr_pf:.2f} "
                f"(high >= {rules.high_correlation})",
                correlation=corr_pf,
            )
        )
        if corr_pf >= rules.high_correlation:
            risks.append(
                f"Adds little diversification: correlation {corr_pf:.2f} with the portfolio"
            )

    vb, va = before["metrics"].get("volatility_annual"), after["metrics"].get("volatility_annual")
    if vb is not None and va is not None:
        d = va - vb
        signals.append(
            sig(
                "marginal_volatility",
                "volatility",
                -d,
                min(1.0, abs(d) / 0.02),
                f"Portfolio volatility {vb:.1%} -> {va:.1%} ({d * 100:+.2f} pts)",
                before=vb,
                after=va,
            )
        )
    sector = next((x["sector"] for x in after["holdings"] if x["candidate"]), "unclassified")
    if sector != "unclassified":
        sw = after["sector_weights"].get(sector, 0.0)
        room = rc.max_sector_weight - sw
        signals.append(
            sig(
                "sector_room",
                "sector",
                room,
                min(1.0, abs(room) / rc.max_sector_weight),
                f"{sector} weight after the trade {sw:.1%} (limit {rc.max_sector_weight:.0%})",
                sector_weight=sw,
            )
        )
    comp = composite(signals, rules.portfolio_fit_weights)
    metrics: dict[str, float | None] = {
        "target_weight": weight,
        "quantity": float(cand.get("quantity") or 0),
        "trade_value": cand.get("value"),
        "correlation_to_portfolio": corr_pf,
        "volatility_before": vb,
        "volatility_after": va,
        "var_95_after": after["metrics"].get("var_95_1d"),
        "limit_failures": float(len(failed)),
    }
    warnings = list(after["warnings"])
    warnings += [
        f"Portfolio already breaches {c['name'].replace('_', ' ')} ({c['reason']}); "
        "not caused by this trade"
        for c in pre_existing
    ]
    if not existing:
        warnings.append("Empty portfolio: diversification and marginal volatility not assessed")
    return AgentOutput(
        agent=AGENT,
        agent_version=AGENT_VERSION,
        ticker=inp.ticker,
        as_of=inp.as_of,
        knowledge_at=inp.knowledge_at,
        generated_at=datetime.now(UTC),
        status=AgentStatus.OK,
        score=comp.score,
        score_basis=SCORE_BASIS,
        confidence=round(comp.agreement * comp.breadth, 4),
        confidence_basis="heuristic_uncalibrated",
        signals=signals,
        evidence=ev,
        risks=risks,
        invalidation_conditions=["Portfolio composition changes", "Correlation regime shifts"],
        metrics=metrics,
        data_quality=h.report.quality_score if h.report else 0.0,
        data_snapshot_id=h.snapshot,
        config_fingerprint=cfg.fingerprint(),
        warnings=warnings,
    ), details


def run_and_record(
    db: Session,
    pf: Portfolio,
    ticker: Ticker,
    weight: float,
    as_of: datetime,
    user_id: uuid.UUID | None,
    knowledge_at: datetime | None = None,
) -> tuple[AgentOutput, dict[str, Any]]:
    stock = md.get_stock(db, ticker)
    inp = new_input(str(ticker), as_of, knowledge_at)
    t0, error = time.perf_counter(), None
    details: dict[str, Any] = {}
    try:
        out, details = run_fit(db, pf, stock, weight, inp)
    except ps.PortfolioError:
        raise
    except Exception as exc:
        log.exception("portfolio agent failed for %s", ticker)
        db.rollback()
        error = f"{exc.__class__.__name__}: {exc}"[:2000]
        out = not_ok(
            AGENT,
            AGENT_VERSION,
            inp,
            AgentStatus.FAILED,
            [f"Agent error: {exc.__class__.__name__}"],
            get_config(),
            SCORE_BASIS,
        )
    record_run(
        db, stock, out, inp.knowledge_at, user_id, int((time.perf_counter() - t0) * 1000), error
    )
    db.commit()
    return out, details
