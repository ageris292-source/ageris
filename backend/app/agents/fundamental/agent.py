"""Fundamental Analysis Agent (spec §9).

Point-in-time financial facts -> deterministic ratios -> history and peer
comparison -> signals -> typed AgentOutput. All numbers are computed here;
nothing is inferred when inputs are missing.
"""

from __future__ import annotations

import hashlib
import logging
import statistics
import time
import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy.orm import Session

from app.agents.base import AgentInput, AgentOutput, AgentStatus, Evidence, Signal
from app.agents.common import composite, new_input, not_ok, record_run, sig
from app.core.config_file import FundamentalRules, get_config
from app.fundamentals import service as fs
from app.fundamentals.ratios import PeriodRatios, annual_ratios, valuation
from app.market_data import service as md
from app.market_data.types import PriceBasis, Ticker
from app.models import Stock

log = logging.getLogger(__name__)

AGENT = "fundamental"
AGENT_VERSION = "fundamental-agent-1.0.0"
SCORE_BASIS = (
    "Deterministic composite of fundamental signals (growth, profitability, balance sheet, "
    "cash quality, valuation), 0-100; 50 = no tilt. Descriptive only: not a probability."
)


def _pct(x: float | None) -> str:
    return "n/a" if x is None else f"{x:.1%}"


def analyze_fundamentals(
    rows: list[PeriodRatios],
    price: float | None,
    rules: FundamentalRules,
    peer_medians: dict[str, float] | None = None,
    *,
    financial_sector: bool = False,
) -> tuple[list[Signal], list[str], dict[str, float | None]]:
    """For lenders (`financial_sector`), debt/equity, interest coverage and
    free-cash-flow tests are skipped: deposits are a bank's raw material, so
    industrial ratios would mislead rather than inform."""
    signals: list[Signal] = []
    risks: list[str] = []
    latest, prev = rows[-1], rows[-2]
    r, p = latest.ratios, prev.ratios
    metrics: dict[str, float | None] = {k: v for k, v in r.items()}

    # growth
    g = r["revenue_growth"]
    if g is not None:
        strength = min(1.0, abs(g) / rules.strong_growth)
        signals.append(
            sig(
                "revenue_growth",
                "growth",
                g,
                strength,
                f"Revenue growth {_pct(g)} in the year to {latest.period_end}",
            )
        )
        pg = p.get("revenue_growth")
        if pg is not None:
            accel = g - pg
            if abs(accel) >= 0.03:
                signals.append(
                    sig(
                        "growth_trend",
                        "growth",
                        accel,
                        min(1.0, abs(accel) / 0.10),
                        f"Revenue growth {'accelerated' if accel > 0 else 'decelerated'} "
                        f"from {_pct(pg)} to {_pct(g)}",
                    )
                )
    eg = r["eps_growth"]
    if eg is not None:
        signals.append(
            sig(
                "eps_growth",
                "growth",
                eg,
                min(1.0, abs(eg) / rules.strong_growth),
                f"Diluted EPS growth {_pct(eg)}",
            )
        )

    # profitability
    om, pom = r["operating_margin"], p.get("operating_margin")
    if om is not None and pom is not None:
        d = om - pom
        if d <= -rules.margin_deterioration_pts:
            signals.append(
                sig(
                    "margin_deterioration",
                    "profitability",
                    -1,
                    min(1.0, -d / 0.05),
                    f"Operating margin fell {abs(d) * 100:.1f} pts to {_pct(om)}",
                )
            )
            risks.append(f"Margin deterioration: operating margin down {abs(d) * 100:.1f} pts")
        elif d >= rules.margin_deterioration_pts:
            signals.append(
                sig(
                    "margin_expansion",
                    "profitability",
                    1,
                    min(1.0, d / 0.05),
                    f"Operating margin rose {d * 100:.1f} pts to {_pct(om)}",
                )
            )
        else:
            signals.append(
                sig(
                    "margin_stable",
                    "profitability",
                    0,
                    0.3,
                    f"Operating margin broadly stable at {_pct(om)}",
                )
            )
    if r["roe"] is not None:
        signals.append(
            sig(
                "roe",
                "profitability",
                r["roe"] - rules.high_roe,
                min(1.0, abs(r["roe"] - rules.high_roe) / rules.high_roe),
                f"Return on equity {_pct(r['roe'])} vs {_pct(rules.high_roe)} benchmark",
            )
        )
    if r["roce"] is not None:
        signals.append(
            sig(
                "roce",
                "profitability",
                r["roce"] - rules.high_roce,
                min(1.0, abs(r["roce"] - rules.high_roce) / rules.high_roce),
                f"Return on capital employed {_pct(r['roce'])}",
            )
        )

    # balance sheet
    de = None if financial_sector else r["debt_to_equity"]
    if de is not None:
        stressed = de > rules.max_debt_to_equity
        signals.append(
            sig(
                "leverage",
                "balance_sheet",
                -1 if stressed else 1,
                min(1.0, de / rules.max_debt_to_equity)
                if stressed
                else 1 - de / rules.max_debt_to_equity,
                f"Debt/equity {de:.2f} (limit {rules.max_debt_to_equity:g})",
            )
        )
        if stressed:
            risks.append(f"Debt stress: debt/equity {de:.2f}")
    ic = None if financial_sector else r["interest_coverage"]
    if ic is not None:
        weak = ic < rules.min_interest_coverage
        signals.append(
            sig(
                "interest_coverage",
                "balance_sheet",
                -1 if weak else 1,
                0.8 if weak else min(1.0, ic / (rules.min_interest_coverage * 10)),
                f"Interest coverage {ic:.1f}x (minimum {rules.min_interest_coverage:g}x)",
            )
        )
        if weak:
            risks.append(f"Weak interest coverage {ic:.1f}x")

    # cash quality
    fc = None if financial_sector else r["fcf_conversion"]
    if fc is not None:
        weak = fc < rules.weak_cash_conversion
        signals.append(
            sig(
                "cash_conversion",
                "cash_quality",
                -1 if weak else 1,
                min(1.0, abs(fc - rules.weak_cash_conversion) / 0.5),
                f"Free cash flow is {fc:.0%} of net income",
            )
        )
        if weak:
            risks.append(f"Weak cash conversion: FCF {fc:.0%} of net income")
    oq = None if financial_sector else r["ocf_to_net_income"]
    if oq is not None and oq < 1:
        signals.append(
            sig(
                "earnings_quality",
                "cash_quality",
                -1,
                min(1.0, 1 - oq),
                f"Operating cash flow below net income ({oq:.2f}x): accrual-heavy earnings",
            )
        )

    # valuation
    if price is not None:
        vals = valuation(price, latest.values, eg)
        metrics.update(vals)
        pe = vals["pe"]
        if pe is not None:
            if pe >= rules.expensive_pe:
                signals.append(
                    sig(
                        "pe_level",
                        "valuation",
                        -1,
                        min(1.0, pe / rules.expensive_pe - 0.5),
                        f"P/E {pe:.1f} at or above {rules.expensive_pe:g}",
                    )
                )
            elif pe <= rules.cheap_pe:
                signals.append(
                    sig(
                        "pe_level",
                        "valuation",
                        1,
                        min(1.0, rules.cheap_pe / pe - 0.5),
                        f"P/E {pe:.1f} at or below {rules.cheap_pe:g}",
                    )
                )
            else:
                signals.append(
                    sig("pe_level", "valuation", 0, 0.3, f"P/E {pe:.1f} in the neutral range")
                )
        if peer_medians and pe is not None and peer_medians.get("pe"):
            rel = pe / peer_medians["pe"] - 1
            signals.append(
                sig(
                    "pe_vs_peers",
                    "valuation",
                    -rel,
                    min(1.0, abs(rel)),
                    f"P/E {pe:.1f} vs peer median {peer_medians['pe']:.1f} ({rel:+.0%})",
                )
            )
        if vals["peg"] is not None and eg is not None and eg >= rules.min_growth_for_peg:
            peg = vals["peg"]
            signals.append(
                sig(
                    "peg",
                    "valuation",
                    1 if peg < 1 else -1 if peg > 2 else 0,
                    min(1.0, abs(peg - 1.5) / 1.5),
                    f"PEG {peg:.2f}",
                )
            )

    # vs own history (3y averages where available)
    hist = [
        x.ratios.get("operating_margin")
        for x in rows[:-1]
        if x.ratios.get("operating_margin") is not None
    ]
    if om is not None and len(hist) >= 2:
        avg = statistics.mean(hist)  # type: ignore[type-var]
        metrics["operating_margin_hist_avg"] = avg
    return signals, risks, metrics


def run_fundamental(db: Session, stock: Stock, inp: AgentInput) -> AgentOutput:
    cfg = get_config()
    rules = cfg.fundamentals
    facts = fs.facts_as_of(db, stock, inp.as_of, inp.knowledge_at)
    annual = fs.periods_of(facts, "annual")
    if len(annual) < rules.min_annual_periods:
        return not_ok(
            AGENT,
            AGENT_VERSION,
            inp,
            AgentStatus.INSUFFICIENT_DATA,
            [
                f"Need {rules.min_annual_periods} annual periods available as of "
                f"{inp.as_of.date()}, have {len(annual)}"
            ],
            cfg,
            SCORE_BASIS,
        )
    h = hashlib.sha256()
    for f in facts:
        h.update(
            f"{f.period_type}{f.period_end}{f.line_item}{f.value}{f.source}{f.data_version}".encode()
        )
    snap = h.hexdigest()
    rows = annual_ratios(annual)

    as_of_date = (inp.as_of + timedelta(hours=5, minutes=30)).date()
    series = md.get_series(
        db,
        stock,
        PriceBasis.SPLIT_ADJUSTED,
        as_of_date - timedelta(days=10),
        as_of_date,
        as_of=inp.as_of,
        knowledge_at=inp.knowledge_at,
    )
    price = float(series.bars[-1].bar.close) if series.bars else None

    peers = _peer_medians(db, stock, inp)
    me = str(md.ticker_of(stock))
    financial_sector = any(
        me in rules.peer_groups.get(g, []) for g in rules.financial_sector_groups
    )
    signals, risks, metrics = analyze_fundamentals(
        rows, price, rules, peers, financial_sector=financial_sector
    )
    comp = composite(signals, {str(k): w for k, w in rules.category_weights.items()})

    warnings: list[str] = []
    estimated = any(f.availability_estimated for f in facts)
    unlicensed = any(not f.licensed for f in facts)
    if unlicensed:
        warnings.append("Unlicensed financial data source: research use only")
    if estimated:
        warnings.append(
            "Publication dates estimated from SEBI filing deadlines; excluded from "
            "historical backtests"
        )
    if price is None:
        warnings.append("No price available: valuation ratios not computed")
    if peers is None:
        warnings.append("No peer data available for relative comparison")
    if financial_sector:
        warnings.append(
            "Lender: industrial leverage and cash-flow ratios skipped; bank-specific "
            "metrics (NIM, GNPA, CASA, capital adequacy) are not available from this source"
        )
    latest_end = rows[-1].period_end
    stale_days = (as_of_date - latest_end).days
    if stale_days > cfg.freshness.financials_days + rules.annual_publication_lag_days + 365:
        warnings.append(f"Latest annual figures are for {latest_end} ({stale_days} days old)")
    quality = 1.0 if not unlicensed else 0.9
    evidence = [
        Evidence(
            ref=f"financials:{stock.symbol}:{f.source}:{f.period_type}:"
            f"{f.period_end}:{f.line_item}:v{f.data_version}",
            description=f"{f.line_item} {f.period_type} {f.period_end}",
        )
        for f in facts
        if f.period_end == latest_end and f.period_type == "annual"
    ][:12]
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
        confidence=round(comp.agreement * comp.breadth * quality, 4),
        confidence_basis="heuristic_uncalibrated",
        signals=signals,
        evidence=evidence,
        risks=risks,
        invalidation_conditions=_invalidation(comp.score, rows),
        metrics={**metrics, "signal_agreement": comp.agreement, "category_breadth": comp.breadth},
        data_quality=quality,
        data_snapshot_id=snap,
        config_fingerprint=cfg.fingerprint(),
        warnings=warnings,
    )


def _invalidation(score: float, rows: list[PeriodRatios]) -> list[str]:
    r = rows[-1].ratios
    out: list[str] = []
    if score > 50:
        if r.get("revenue_growth") is not None:
            out.append("Next reported annual revenue growth turns negative")
        if r.get("operating_margin") is not None:
            out.append(f"Operating margin falls below {(r['operating_margin'] or 0) - 0.02:.1%}")
    elif score < 50:
        out.append("Two consecutive quarters of margin expansion and positive revenue growth")
    else:
        out.append("No directional thesis: nothing to invalidate")
    return out


def _peer_medians(db: Session, stock: Stock, inp: AgentInput) -> dict[str, float] | None:
    rules = get_config().fundamentals
    me = str(md.ticker_of(stock))
    group = next((g for g in rules.peer_groups.values() if me in g), None)
    if not group:
        return None
    pes: list[float] = []
    for t in group:
        if t == me:
            continue
        try:
            peer = md.get_stock(db, Ticker.parse(t))
        except (md.StockNotFoundError, ValueError):
            continue
        facts = fs.facts_as_of(db, peer, inp.as_of, inp.knowledge_at)
        annual = fs.periods_of(facts, "annual")
        if not annual:
            continue
        latest = annual[max(annual)]
        d = (inp.as_of + timedelta(hours=5, minutes=30)).date()
        s = md.get_series(
            db,
            peer,
            PriceBasis.SPLIT_ADJUSTED,
            d - timedelta(days=10),
            d,
            as_of=inp.as_of,
            knowledge_at=inp.knowledge_at,
        )
        eps = latest.get("eps_diluted")
        if s.bars and eps and eps > 0:
            pes.append(float(s.bars[-1].bar.close) / eps)
    return {"pe": statistics.median(pes)} if pes else None


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
        out = run_fundamental(db, stock, inp)
    except Exception as exc:
        log.exception("fundamental agent failed for %s", ticker)
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
