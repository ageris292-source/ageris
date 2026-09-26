"""Valuation Agent (spec §12): DCF bear/base/bull + relative multiples.

Never outputs a single intrinsic value without its assumptions: the result
always carries the scenario table, the assumptions behind each scenario and
a WACC x terminal-growth sensitivity grid.
"""

from __future__ import annotations

import hashlib
import logging
import math
import statistics
import time
import uuid
from dataclasses import asdict
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy.orm import Session

from app.agents.base import AgentInput, AgentOutput, AgentStatus, Evidence, Signal
from app.agents.common import new_input, not_ok, record_run, sig
from app.agents.macro.agent import sector_of
from app.analysis.stats import beta as calc_beta
from app.core.config_file import get_config
from app.fundamentals import service as fs
from app.fundamentals.ratios import valuation as multiples
from app.macro import service as ms
from app.market_data import service as md
from app.market_data.types import PriceBasis, Ticker
from app.models import Stock
from app.valuation.dcf import Assumptions, DcfError, cost_of_capital, run_dcf, sensitivity

log = logging.getLogger(__name__)

AGENT = "valuation"
AGENT_VERSION = "valuation-agent-1.0.0"
SCORE_BASIS = (
    "50 + 50 x tanh(base-case margin of safety / scale); 50 = fairly valued on the base "
    "case. Model estimate under stated assumptions, not a price target or probability."
)
INDIA_STATUTORY_TAX = 0.2517  # fallback only when the effective rate is unavailable


def _cagr(values: list[float]) -> float | None:
    if len(values) < 2 or values[0] <= 0 or values[-1] <= 0:
        return None
    return float((values[-1] / values[0]) ** (1 / (len(values) - 1)) - 1)


def build(db: Session, stock: Stock, inp: AgentInput) -> tuple[AgentOutput, dict[str, Any]]:
    cfg = get_config()
    v = cfg.valuation
    ticker = str(md.ticker_of(stock))
    facts = fs.facts_as_of(db, stock, inp.as_of, inp.knowledge_at)
    annual = fs.periods_of(facts, "annual")
    ends = sorted(annual)
    if len(ends) < 2:
        return not_ok(
            AGENT,
            AGENT_VERSION,
            inp,
            AgentStatus.INSUFFICIENT_DATA,
            [f"Need 2 annual periods of financials as of {inp.as_of.date()}, have {len(ends)}"],
            cfg,
            SCORE_BASIS,
        ), {}
    latest = annual[ends[-1]]
    as_of_date = (inp.as_of + timedelta(hours=5, minutes=30)).date()
    prices = md.get_series(
        db,
        stock,
        PriceBasis.SPLIT_ADJUSTED,
        as_of_date - timedelta(days=v.beta_lookback_weeks * 7 + 30),
        as_of_date,
        as_of=inp.as_of,
        knowledge_at=inp.knowledge_at,
    )
    if not prices.bars:
        return not_ok(
            AGENT,
            AGENT_VERSION,
            inp,
            AgentStatus.INSUFFICIENT_DATA,
            ["No price available as of this date"],
            cfg,
            SCORE_BASIS,
        ), {}
    price = float(prices.bars[-1].bar.close)
    warnings = [
        "Financials and prices from unlicensed sources: research use only",
        f"Risk-free rate {v.risk_free_rate:.2%} and ERP {v.equity_risk_premium:.2%} are "
        "configured assumptions, not live market data",
    ]
    details: dict[str, Any] = {
        "price": price,
        "price_date": prices.bars[-1].bar.session.isoformat(),
    }
    signals: list[Signal] = []
    risks: list[str] = []
    metrics: dict[str, float | None] = {"price": price}

    # ---- relative valuation (always attempted) -----------------------------
    eps_g = None
    if len(ends) >= 2 and annual[ends[-2]].get("eps_diluted") and latest.get("eps_diluted"):
        prev_eps = annual[ends[-2]]["eps_diluted"]
        eps_g = latest["eps_diluted"] / prev_eps - 1 if prev_eps > 0 else None
    own = multiples(price, latest, eps_g)
    metrics.update({k: own[k] for k in ("pe", "pb", "ev_ebitda", "fcf_yield", "earnings_yield")})
    peers = _peer_multiples(db, stock, inp)
    details["peer_medians"] = peers
    for key, label in (("pe", "P/E"), ("ev_ebitda", "EV/EBITDA"), ("pb", "P/B")):
        mine, med = own.get(key), peers.get(key)
        if mine and med:
            rel = mine / med - 1
            signals.append(
                sig(
                    f"{key}_vs_peers",
                    "relative",
                    -rel,
                    min(1.0, abs(rel)),
                    f"{label} {mine:.1f} vs peer median {med:.1f} ({rel:+.0%})",
                )
            )

    # ---- DCF ---------------------------------------------------------------
    financial = sector_of(ticker) in cfg.fundamentals.financial_sector_groups
    scenarios: dict[str, dict[str, Any]] = {}
    base_mos: float | None = None
    if financial:
        warnings.append("Lender: free-cash-flow DCF is not meaningful; relative valuation only")
    else:
        revenues = [annual[e].get("revenue") for e in ends]
        fcfs = []
        for e in ends:
            a = annual[e]
            f = a.get("free_cash_flow")
            if (
                f is None
                and a.get("operating_cash_flow") is not None
                and a.get("capex") is not None
            ):
                f = a["operating_cash_flow"] + a["capex"]
            fcfs.append(f)
        margins = [f / r for f, r in zip(fcfs, revenues, strict=True) if f is not None and r]
        needed = {k: latest.get(k) for k in ("revenue", "shares_diluted", "total_debt", "cash")}
        missing = [k for k, val in needed.items() if val is None]
        growth = _cagr([r for r in revenues if r is not None])
        if missing or not margins or growth is None:
            warnings.append(
                "DCF not computed: missing "
                + ", ".join(
                    missing
                    + ([] if margins else ["free cash flow"])
                    + ([] if growth is not None else ["revenue history"])
                )
            )
        elif statistics.mean(margins) <= 0:
            warnings.append("DCF not computed: negative average free-cash-flow margin")
        else:
            rev0, debt0 = float(needed["revenue"] or 0), float(needed["total_debt"] or 0)
            cash0, shares0 = float(needed["cash"] or 0), float(needed["shares_diluted"] or 0)
            tax = (
                latest["tax"] / latest["pretax_income"]
                if latest.get("tax") and latest.get("pretax_income", 0) > 0
                else None
            )
            if tax is None or not 0 <= tax <= 0.45:
                warnings.append(
                    f"Effective tax rate unavailable; assumed statutory {INDIA_STATUTORY_TAX:.2%}"
                )
                tax = INDIA_STATUTORY_TAX
            b, n_obs = calc_beta(
                [(sb.bar.session, float(sb.bar.close)) for sb in prices.bars],
                ms.series_as_of(
                    db,
                    cfg.macro.benchmark,
                    inp.as_of,
                    inp.knowledge_at,
                    as_of_date - timedelta(days=v.beta_lookback_weeks * 7 + 30),
                ),
                v.beta_lookback_weeks,
            )
            if b is None:
                warnings.append(f"Beta not estimable ({n_obs} common weeks); assumed 1.0")
                b = 1.0
            b_used = min(max(b, v.beta_bounds[0]), v.beta_bounds[1])
            mcap = price * shares0
            wacc, parts = cost_of_capital(
                risk_free=v.risk_free_rate,
                erp=v.equity_risk_premium,
                beta=b_used,
                market_cap=mcap,
                debt=debt0,
                interest_expense=latest.get("interest_expense"),
                tax_rate=tax,
            )
            g_base = min(max(growth, v.min_growth), v.max_growth)
            m_base = statistics.mean(margins)
            spec = {
                "bear": (
                    g_base - v.growth_spread,
                    min(margins),
                    wacc + v.wacc_spread,
                    v.terminal_growth.bear,
                ),
                "base": (g_base, m_base, wacc, v.terminal_growth.base),
                "bull": (
                    g_base + v.growth_spread,
                    max(margins),
                    wacc - v.wacc_spread,
                    v.terminal_growth.bull,
                ),
            }
            base_assumptions = None
            for name, (g, m, w, tg) in spec.items():
                asm = Assumptions(
                    revenue=rev0,
                    growth=min(max(g, v.min_growth), v.max_growth),
                    fcf_margin=m,
                    wacc=w,
                    terminal_growth=tg,
                    years=v.projection_years,
                    debt=debt0,
                    cash=cash0,
                    shares=shares0,
                )
                try:
                    r = run_dcf(asm)
                except DcfError as exc:
                    warnings.append(f"{name} DCF invalid: {exc}")
                    continue
                scenarios[name] = {
                    "per_share": r.per_share,
                    "margin_of_safety": r.per_share / price - 1,
                    "enterprise_value": r.enterprise_value,
                    "equity_value": r.equity_value,
                    "terminal_share_of_ev": r.terminal_share_of_ev,
                    "assumptions": asdict(asm),
                    "notes": r.notes,
                }
                if name == "base":
                    base_assumptions = asm
                    risks.extend(r.notes)
            details.update(
                beta_raw=b,
                beta_used=b_used,
                beta_weeks=n_obs,
                tax_rate=tax,
                wacc=wacc,
                wacc_parts=parts,
                revenue_cagr=growth,
                fcf_margins=margins,
            )
            if base_assumptions is not None:
                steps = [-0.01, 0.0, 0.01]
                details["sensitivity"] = {
                    "wacc_deltas": steps,
                    "growth_deltas": steps,
                    "per_share": sensitivity(base_assumptions, steps, steps),
                }
            unreliable = []
            if min(margins) <= 0:
                unreliable.append("negative free cash flow in at least one year")
            if m_base < 0.05:
                unreliable.append(
                    f"thin average FCF margin ({m_base:.1%}); capex-heavy or cyclical"
                )
            if any(sc["per_share"] <= 0 for sc in scenarios.values()):
                unreliable.append("a scenario yields a non-positive equity value")
            details["dcf_reliable"] = not unreliable
            if unreliable:
                warnings.append("DCF shown for reference but NOT scored: " + "; ".join(unreliable))
            if "base" in scenarios and not unreliable:
                base_mos = scenarios["base"]["margin_of_safety"]
                metrics.update({f"fair_value_{k}": s["per_share"] for k, s in scenarios.items()})
                metrics.update(margin_of_safety=base_mos, wacc=wacc, beta=b_used)
                signals.append(
                    sig(
                        "dcf_base",
                        "dcf",
                        base_mos,
                        min(1.0, abs(base_mos) / v.mos_scale),
                        f"Base-case DCF ₹{scenarios['base']['per_share']:,.0f}/share vs price "
                        f"₹{price:,.0f} (margin of safety {base_mos:+.0%})",
                    )
                )
                if "bear" in scenarios and scenarios["bear"]["margin_of_safety"] < -0.2:
                    risks.append(
                        f"Bear case ₹{scenarios['bear']['per_share']:,.0f} is "
                        f"{-scenarios['bear']['margin_of_safety']:.0%} below the price"
                    )
    details["scenarios"] = scenarios

    if base_mos is None and not signals:
        return not_ok(
            AGENT,
            AGENT_VERSION,
            inp,
            AgentStatus.INSUFFICIENT_DATA,
            ["Neither a reliable DCF nor peer multiples are available", *warnings[2:]],
            cfg,
            SCORE_BASIS,
        ), details
    if base_mos is not None:
        score = round(50 + 50 * math.tanh(base_mos / v.mos_scale), 2)
    else:
        net = sum(
            (1 if s.direction == "bullish" else -1 if s.direction == "bearish" else 0) * s.strength
            for s in signals
        ) / len(signals)
        score = round(50 + 50 * net, 2)
    spread = None
    if {"bear", "bull"} <= scenarios.keys():
        spread = (scenarios["bull"]["per_share"] - scenarios["bear"]["per_share"]) / price
        metrics["scenario_spread"] = spread
    conf = 0.0 if base_mos is None else 1 / (1 + (spread or 1.0))
    evidence = [
        Evidence(
            ref=f"financials:{stock.symbol}:annual:{ends[-1]}",
            description=f"Latest annual financials ({ends[-1]})",
        ),
        Evidence(ref=f"prices:{ticker}:{details['price_date']}", description="Close used as price"),
    ]
    h = hashlib.sha256(repr((sorted(metrics.items()), details.get("wacc"))).encode()).hexdigest()
    out = AgentOutput(
        agent=AGENT,
        agent_version=AGENT_VERSION,
        ticker=inp.ticker,
        as_of=inp.as_of,
        knowledge_at=inp.knowledge_at,
        generated_at=datetime.now(UTC),
        status=AgentStatus.OK,
        score=score,
        score_basis=SCORE_BASIS,
        confidence=round(conf * (0.5 if financial else 1.0), 4),
        confidence_basis="heuristic_uncalibrated",
        signals=signals,
        evidence=evidence,
        risks=risks,
        invalidation_conditions=(
            [f"Price rises above the bull-case value ₹{scenarios['bull']['per_share']:,.0f}"]
            if score > 50 and "bull" in scenarios
            else [f"Price falls below the bear-case value ₹{scenarios['bear']['per_share']:,.0f}"]
            if score < 50 and "bear" in scenarios
            else ["Reported free-cash-flow margin moves outside the historical range"]
        ),
        metrics=metrics,
        data_quality=0.9,
        data_snapshot_id=h,
        config_fingerprint=cfg.fingerprint(),
        warnings=warnings,
    )
    return out, details


def _peer_multiples(db: Session, stock: Stock, inp: AgentInput) -> dict[str, float]:
    me = str(md.ticker_of(stock))
    group = sector_of(me)
    if group is None:
        return {}
    vals: dict[str, list[float]] = {"pe": [], "pb": [], "ev_ebitda": []}
    d = (inp.as_of + timedelta(hours=5, minutes=30)).date()
    for t in get_config().fundamentals.peer_groups[group]:
        if t == me:
            continue
        try:
            peer = md.get_stock(db, Ticker.parse(t))
        except (md.StockNotFoundError, ValueError):
            continue
        annual = fs.periods_of(fs.facts_as_of(db, peer, inp.as_of, inp.knowledge_at), "annual")
        s = md.get_series(
            db,
            peer,
            PriceBasis.SPLIT_ADJUSTED,
            d - timedelta(days=10),
            d,
            as_of=inp.as_of,
            knowledge_at=inp.knowledge_at,
        )
        if not annual or not s.bars:
            continue
        m = multiples(float(s.bars[-1].bar.close), annual[max(annual)], None)
        for k in vals:
            if m.get(k):
                vals[k].append(m[k])  # type: ignore[arg-type]
    return {k: statistics.median(x) for k, x in vals.items() if x}


def run_and_record(
    db: Session,
    ticker: Ticker,
    as_of: datetime,
    user_id: uuid.UUID | None,
    knowledge_at: datetime | None = None,
) -> tuple[AgentOutput, dict[str, Any]]:
    stock = md.get_stock(db, ticker)
    inp = new_input(str(ticker), as_of, knowledge_at)
    t0, error = time.perf_counter(), None
    details: dict[str, Any] = {}
    try:
        out, details = build(db, stock, inp)
    except Exception as exc:
        log.exception("valuation agent failed for %s", ticker)
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
