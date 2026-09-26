"""Daily opportunity ranking, no-trade analytics and counterfactuals (spec §32-§35).

For every stock in the universe a STANDARDISED candidate trade (entry at the
last close, stop from ATR, target at a fixed reward multiple, size from the
risk budget) is evaluated by the real Trade Risk Engine. A stock is a
QUALIFIED opportunity only if every opportunity gate passes. Operational
gates (kill switch, execution mode, portfolio kind) and the spread gate
(needs a live quote at order time) are reported separately.
Nothing here places or proposes an order.
"""

from __future__ import annotations

import math
import uuid
from collections import Counter
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

import numpy as np
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.alerts.service import raise_alert
from app.analysis.indicators import atr
from app.backtest.data import universe
from app.core.config_file import get_config
from app.market_data import service as md
from app.market_data.types import PriceBasis, Ticker
from app.models import AnalysisReport, Portfolio, RankingRun, Stock
from app.orchestrator import service as orch
from app.portfolio import service as ps
from app.risk.service import ist_date
from app.services.audit import record_audit
from app.trade import context
from app.trade.gates import evaluate
from app.trade.schemas import TradeProposal

OPERATIONAL_GATES = frozenset({"kill_switch", "execution_mode", "portfolio_match", "spread"})
NO_OPPORTUNITIES = "NO QUALIFIED OPPORTUNITIES TODAY"


def _levels(db: Session, stock: Stock, as_of: datetime) -> tuple[float, float] | None:
    """(last close, ATR14) from split-adjusted bars available at as_of."""
    end = ist_date(as_of)
    s = md.get_series(
        db, stock, PriceBasis.SPLIT_ADJUSTED, end - timedelta(days=60), end, as_of=as_of
    )
    if len(s.bars) < 16:
        return None
    h = np.array([float(b.bar.high) for b in s.bars])
    lo = np.array([float(b.bar.low) for b in s.bars])
    c = np.array([float(b.bar.close) for b in s.bars])
    a = atr(h, lo, c, 14)[-1]
    if not np.isfinite(a):
        return None
    return float(c[-1]), float(a)


def _default_portfolio(db: Session) -> Portfolio | None:
    return db.scalar(
        select(Portfolio)
        .where(Portfolio.kind == "paper", Portfolio.is_active)
        .order_by(Portfolio.id)
        .limit(1)
    )


def _latest_report(db: Session, stock: Stock, as_of: datetime) -> AnalysisReport | None:
    return db.scalar(
        select(AnalysisReport)
        .where(AnalysisReport.stock_id == stock.id, AnalysisReport.created_at <= as_of)
        .order_by(AnalysisReport.created_at.desc())
        .limit(1)
    )


def run_ranking(
    db: Session,
    as_of: datetime,
    user_id: uuid.UUID | None,
    portfolio_id: int | None = None,
    refresh: bool | None = None,
    clock: Callable[[], datetime] = lambda: datetime.now(UTC),
) -> RankingRun:
    """Rank the universe at `as_of`. Records an immutable RankingRun, raises
    an in-app alert and commits. Places and proposes nothing."""
    cfg = get_config()
    rules = cfg.ranking
    refresh = rules.refresh_reports if refresh is None else refresh
    pf = db.get(Portfolio, portfolio_id) if portfolio_id is not None else _default_portfolio(db)
    equity: float | None = None
    if pf is not None:
        a = ps.analyze(db, pf, as_of)
        if all(h["value"] is not None for h in a["holdings"]):
            equity = a["metrics"].get("equity")

    stocks = universe(db, None)
    if refresh:
        # Refresh stale reports FIRST, then evaluate everything at one instant
        # after the refresh: a report is only visible to the engine once it
        # exists (created_at <= as_of), so no look-ahead and no invisible reports.
        max_age = timedelta(hours=cfg.trade_engine.max_report_age_hours)
        refreshed = False
        for stock in stocks:
            rep = _latest_report(db, stock, as_of)
            if rep is None or as_of - rep.created_at > max_age:
                orch.run_analysis(db, md.ticker_of(stock), as_of, user_id)
                refreshed = True
        if refreshed:
            as_of = max(as_of, clock())

    rows: list[dict[str, Any]] = []
    first_fail: Counter[str] = Counter()
    operational: set[str] = set()
    for stock in stocks:
        ticker = str(md.ticker_of(stock))
        rep = _latest_report(db, stock, as_of)
        lv = _levels(db, stock, as_of)
        row: dict[str, Any] = {
            "ticker": ticker,
            "name": stock.name,
            "stance": rep.stance if rep else None,
            "composite": rep.composite_score if rep else None,
            "report_id": rep.id if rep else None,
        }
        if lv is None:
            row.update(
                qualified=False, first_failure="data", failures=["insufficient price history"]
            )
            first_fail["data"] += 1
            rows.append(row)
            continue
        close, a14 = lv
        dist = max(rules.stop_atr_multiple * a14, rules.min_stop_fraction * close)
        entry = Decimal(f"{close:.2f}")
        stop = Decimal(f"{close - dist:.2f}")
        target = Decimal(f"{close + rules.target_reward_multiple * dist:.2f}")
        qty = 1
        if equity:
            qty = max(
                1,
                math.floor(
                    min(
                        equity * cfg.position_sizing.risk_per_trade / dist,
                        equity * cfg.trade_engine.max_order_value_fraction / close,
                    )
                ),
            )
        p = TradeProposal(
            ticker=ticker,
            side="buy",
            quantity=qty,
            entry_price=entry,
            stop_loss=stop,
            target=target,
            horizon_days=rules.horizon,
            portfolio_id=pf.id if pf else 0,
            mode="paper",
            rationale="standardised ranking candidate",
        )
        ctx, _ = context.build(db, p, as_of)
        d = evaluate(p, ctx, cfg, as_of)
        bad = [g for g in d.gates if g.status in ("FAIL", "UNKNOWN")]
        opp = [g for g in bad if g.name not in OPERATIONAL_GATES]
        for g in bad:
            if g.name in OPERATIONAL_GATES and g.name != "spread":
                operational.add(f"{g.name}: {g.reason}")
        if opp:
            first_fail[opp[0].name] += 1
        pr = ctx.probability
        row.update(
            qualified=not opp,
            first_failure=opp[0].name if opp else None,
            failures=[f"{g.name}: {g.reason}" for g in opp],
            entry=float(entry),
            stop=float(stop),
            target=float(target),
            quantity=qty,
            p_profit=pr.p_profit if pr else None,
            p_outperform=pr.p_outperform if pr else None,
            expected_net_return=d.metrics.get("expected_net_return"),
            reward_risk=d.metrics.get("reward_risk"),
            round_trip_cost=d.metrics.get("round_trip_cost"),
            needs_live_quote=True,
        )
        rows.append(row)

    def desc(v: float | None) -> float:
        return -v if v is not None else math.inf  # unknown sorts last

    def key(r: dict[str, Any]) -> tuple[Any, ...]:
        return (
            not r["qualified"],
            desc(r.get("expected_net_return")),
            desc(r.get("composite")),
            r["ticker"],
        )

    rows.sort(key=key)
    for i, r in enumerate(rows, start=1):
        r["rank"] = i
    n = sum(1 for r in rows if r["qualified"])
    headline = (
        f"{n} QUALIFIED OPPORTUNIT{'Y' if n == 1 else 'IES'} "
        "(pending live quote and human approval)"
        if n
        else NO_OPPORTUNITIES
    )
    run = RankingRun(
        as_of=as_of,
        horizon=rules.horizon,
        portfolio_id=pf.id if pf else None,
        headline=headline[:80],
        qualified=n,
        evaluated=len(rows),
        rows=rows,
        gate_failure_counts=dict(first_fail.most_common()),
        operational_blockers=sorted(operational),
        config_fingerprint=cfg.fingerprint(),
    )
    db.add(run)
    db.flush()
    top = ", ".join([r["ticker"] for r in rows if r["qualified"]][: rules.top_n])
    blockers = ", ".join(f"{k} ({v})" for k, v in first_fail.most_common(3))
    raise_alert(
        db,
        kind="ranking",
        severity="warning" if n else "info",
        title=headline,
        body=(f"Qualified: {top}." if n else f"Most common blocking gates: {blockers or '—'}.")
        + (" Operational blockers: " + "; ".join(sorted(operational)) if operational else ""),
        dedupe_key=f"ranking:{run.id}",
        link="/ranking",
    )
    record_audit(
        db,
        action="ranking.run",
        actor_user_id=user_id,
        entity_type="ranking_run",
        entity_id=str(run.id),
        details={"qualified": n, "evaluated": len(rows)},
    )
    db.commit()
    return run


def counterfactuals(db: Session, now: datetime) -> dict[str, Any]:
    """What happened to every ranked candidate after the ranking date:
    realised forward return (entry next session close, exit `horizon`
    sessions later) and excess over NIFTY, grouped by qualified / first
    blocking gate. Tells whether the gates are rejecting the right trades."""
    from app.macro import service as ms

    runs = db.scalars(select(RankingRun).order_by(RankingRun.as_of)).all()
    bench = dict(ms.series_as_of(db, get_config().macro.benchmark, now, None))
    groups: dict[str, list[tuple[float, float | None]]] = {}
    pending = 0
    for run in runs:
        start = ist_date(run.as_of)
        for r in run.rows:
            try:
                stock = md.get_stock(db, Ticker.parse(r["ticker"]))
            except md.StockNotFoundError:
                continue
            s = md.get_series(
                db,
                stock,
                PriceBasis.SPLIT_ADJUSTED,
                start,
                start + timedelta(days=run.horizon * 3),
                as_of=now,
            )
            after = [b for b in s.bars if b.bar.session > start]
            if len(after) <= run.horizon:
                pending += 1
                continue
            e, x = after[0], after[run.horizon]
            ret = float(x.bar.close) / float(e.bar.close) - 1
            be, bx = bench.get(e.bar.session), bench.get(x.bar.session)
            excess = ret - (bx / be - 1) if be and bx else None
            g = "QUALIFIED" if r["qualified"] else f"blocked:{r.get('first_failure')}"
            groups.setdefault(g, []).append((ret, excess))
    out = []
    for g, vals in sorted(groups.items()):
        rets = [v for v, _ in vals]
        exc = [x for _, x in vals if x is not None]
        out.append(
            {
                "group": g,
                "n": len(vals),
                "mean_forward_return": float(np.mean(rets)),
                "hit_rate": float(np.mean([v > 0 for v in rets])),
                "mean_excess_vs_nifty": float(np.mean(exc)) if exc else None,
            }
        )
    return {"groups": out, "pending": pending, "rankings": len(runs)}
