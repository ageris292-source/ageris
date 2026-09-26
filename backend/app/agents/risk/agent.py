"""Risk Agent (spec §13): historical risk profile of one stock.

Score direction follows the other agents: higher = more favourable, i.e. LOWER
measured risk. 50 = typical. Historical statistics describe the past; they
are not forecasts. A stock failing the configured liquidity minimum gets a
maximal bearish liquidity signal and an explicit risk line (the trade risk
engine in Phase 9 enforces it as a hard gate).
"""

from __future__ import annotations

import logging
import math
import time
import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy.orm import Session

from app.agents.base import AgentInput, AgentOutput, AgentStatus, Evidence, Signal
from app.agents.common import composite, new_input, not_ok, record_run, sig
from app.core.config_file import get_config
from app.market_data import service as md
from app.market_data.types import Ticker
from app.models import Stock
from app.risk import service as rs

log = logging.getLogger(__name__)

AGENT = "risk"
AGENT_VERSION = "risk-agent-1.0.0"
SCORE_BASIS = (
    "Risk suitability 0-100: higher = lower measured historical risk, 50 = typical. "
    "Composite of volatility, drawdown, market sensitivity, return quality and liquidity. "
    "Historical description, not a forecast or probability."
)


def _fmt(v: float | None, pct: bool = True) -> str:
    if v is None:
        return "n/a"
    return f"{v:.1%}" if pct else f"{v:.2f}"


def run_risk(db: Session, stock: Stock, inp: AgentInput) -> tuple[AgentOutput, dict[str, Any]]:
    cfg = get_config()
    rules = cfg.risk_analysis
    h = rs.load_history(db, stock, inp.as_of, inp.knowledge_at, rules.lookback_sessions)
    ev = [
        Evidence(
            ref=f"prices:{h.ticker}:{h.basis}:{h.source}:snapshot={h.snapshot[:16]}",
            description=f"{len(h.closes)} daily closes ({h.basis}) from {h.source}",
        )
    ]
    if not h.closes:
        return not_ok(
            AGENT,
            AGENT_VERSION,
            inp,
            AgentStatus.INSUFFICIENT_DATA,
            ["No price data available as of this date"],
            cfg,
            SCORE_BASIS,
        ), {}
    if h.report is not None and not h.report.usable:
        return not_ok(
            AGENT,
            AGENT_VERSION,
            inp,
            AgentStatus.DATA_UNUSABLE,
            ["Stored prices failed validation"],
            cfg,
            SCORE_BASIS,
            quality=h.report.quality_score,
            snapshot=h.snapshot,
            evidence=ev,
        ), {}
    quality = h.report.quality_score if h.report else 0.0
    if len(h.closes) - 1 < rules.min_history_sessions:
        return not_ok(
            AGENT,
            AGENT_VERSION,
            inp,
            AgentStatus.INSUFFICIENT_DATA,
            [f"Need {rules.min_history_sessions} daily returns, have {len(h.closes) - 1}"],
            cfg,
            SCORE_BASIS,
            quality=quality,
            snapshot=h.snapshot,
            evidence=ev,
        ), {}

    bench = rs.benchmark(db, inp.as_of, inp.knowledge_at, rules.lookback_sessions, cfg)
    m = rs.stock_metrics(h, bench, cfg)
    warnings = list(h.warnings)
    risks: list[str] = []
    signals: list[Signal] = []
    if h.licensed is False:
        warnings.append("Unlicensed price source: research use only")
    fresh = md.freshness_for_date(h.closes[-1][0], inp.as_of, cfg)
    if fresh.status != "PASS":
        warnings.append(f"Prices not fresh: {fresh.reason}")

    vol = m["volatility_annual"]
    mid = (rules.low_volatility + rules.high_volatility) / 2
    half = (rules.high_volatility - rules.low_volatility) / 2
    signals.append(
        sig(
            "volatility_level",
            "volatility",
            mid - vol,
            abs(vol - mid) / half,
            f"Annualised volatility {_fmt(vol)} (low {rules.low_volatility:.0%}, "
            f"high {rules.high_volatility:.0%})",
            level=vol,
        )
    )
    if vol >= rules.high_volatility:
        risks.append(f"High volatility: {_fmt(vol)} annualised")
    v20 = m["volatility_20d_annual"]
    if v20 is not None and vol > 0:
        ratio = v20 / vol
        if ratio >= 1.5 or ratio <= 0.67:
            signals.append(
                sig(
                    "volatility_shift",
                    "volatility",
                    1 - ratio,
                    min(1.0, abs(ratio - 1)),
                    f"20-day volatility {_fmt(v20)} is {ratio:.2f}x the 1-year level",
                    ratio=ratio,
                )
            )
            if ratio >= 1.5:
                risks.append(f"Volatility expanding: 20-day {_fmt(v20)} vs 1-year {_fmt(vol)}")

    mdd = m["max_drawdown"]
    target = rules.drawdown_warning / 2
    signals.append(
        sig(
            "max_drawdown",
            "drawdown",
            target - mdd,
            abs(mdd - target) / target,
            f"Max drawdown {_fmt(mdd)} over the lookback ({m['drawdown_peak']} -> "
            f"{m['drawdown_trough']}); currently {_fmt(m['current_drawdown'])} below peak",
            level=mdd,
        )
    )
    if mdd >= rules.drawdown_warning:
        risks.append(f"Deep drawdown: {_fmt(mdd)} peak-to-trough in the lookback")

    beta = m["beta"]
    if beta is None:
        warnings.append("Beta unavailable: benchmark (NIFTY 50) history missing; run macro ingest")
    else:
        if beta > rules.high_beta:
            val, strength = -1.0, min(1.0, 0.4 + (beta - rules.high_beta))
        elif beta < rules.low_beta:
            val, strength = 1.0, min(1.0, 0.3 + (rules.low_beta - beta))
        else:
            val, strength = 0.0, 0.0
        signals.append(
            sig(
                "beta",
                "market",
                val,
                strength,
                f"Beta {beta:.2f} vs NIFTY 50 ({m['beta_observations']} daily obs; "
                f"band {rules.low_beta}-{rules.high_beta})",
                level=beta,
            )
        )
        if beta > rules.high_beta:
            risks.append(f"High market sensitivity: beta {beta:.2f}")

    sh = m["sharpe"]
    if sh is not None:
        signals.append(
            sig(
                "sharpe",
                "return_quality",
                sh - 0.5,
                min(1.0, abs(sh - 0.5)),
                f"Sharpe {sh:.2f}, Sortino {_fmt(m['sortino'], False)} (risk-free "
                f"{cfg.valuation.risk_free_rate:.1%}, trailing, not predictive)",
                level=sh,
            )
        )

    adtv = m["adtv"]
    minimum = cfg.liquidity.minimum_average_daily_traded_value
    if adtv is None:
        warnings.append("Liquidity unknown: insufficient volume history")
    else:
        if adtv < minimum:
            signals.append(
                sig(
                    "liquidity",
                    "liquidity",
                    -1,
                    1.0,
                    f"Avg daily traded value ₹{adtv / 1e7:,.1f} cr below the ₹{minimum / 1e7:,.1f} "
                    "cr minimum",
                    level=adtv,
                )
            )
            risks.append("FAILS the liquidity minimum: not tradable under current rules")
        else:
            signals.append(
                sig(
                    "liquidity",
                    "liquidity",
                    1,
                    min(1.0, math.log10(adtv / minimum)),
                    f"Avg daily traded value ₹{adtv / 1e7:,.1f} cr "
                    f"({rules.adv_window_sessions} sessions; minimum ₹{minimum / 1e7:,.1f} cr)",
                    level=adtv,
                )
            )
    v99 = m.get("var_99_1d")
    if v99 is not None and v99 >= 0.05:
        risks.append(f"Fat left tail: 1-day historical VaR(99%) {_fmt(v99)}")

    comp = composite(signals, rules.category_weights)
    metrics = {
        k: (float(v) if v is not None else None) for k, v in m.items() if not isinstance(v, str)
    }
    out = AgentOutput(
        agent=AGENT,
        agent_version=AGENT_VERSION,
        ticker=inp.ticker,
        as_of=inp.as_of,
        knowledge_at=inp.knowledge_at,
        generated_at=datetime.now(UTC),
        status=AgentStatus.OK,
        score=comp.score,
        score_basis=SCORE_BASIS,
        confidence=round(comp.agreement * comp.breadth * quality, 4),
        confidence_basis="heuristic_uncalibrated",
        signals=signals,
        evidence=ev,
        risks=risks,
        invalidation_conditions=[
            f"20-day realised volatility rising above {rules.high_volatility:.0%}",
            f"Drawdown from peak exceeding {rules.drawdown_warning:.0%}",
            "Average daily traded value falling below the liquidity minimum",
        ],
        metrics=metrics,
        data_quality=quality,
        data_snapshot_id=h.snapshot,
        config_fingerprint=cfg.fingerprint(),
        warnings=warnings,
    )
    return out, m


def run_and_record(
    db: Session,
    ticker: Ticker,
    as_of: datetime,
    user_id: uuid.UUID | None,
    knowledge_at: datetime | None = None,
) -> AgentOutput:
    stock = md.get_stock(db, ticker)
    inp = new_input(str(ticker), as_of, knowledge_at)
    t0, error = time.perf_counter(), None
    try:
        out, _ = run_risk(db, stock, inp)
    except Exception as exc:
        log.exception("risk agent failed for %s", ticker)
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
    return out
