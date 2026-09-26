"""Portfolio construction checks and analytics (spec §14).

Every limit check is PASS / FAIL / UNKNOWN; UNKNOWN (a missing price, an
unclassified sector large enough to matter, missing volume) never passes.
Limit checks mirror `risk_controls` / `liquidity` in the config; advisory
checks (correlation, concentration, simulated drawdown) inform but do not
block. Portfolio statistics simulate the CURRENT weights over the lookback,
which is a description of the holdings, not a track record.
"""

from __future__ import annotations

import math
import uuid
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Any, Literal

import numpy as np
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.agents.macro.agent import sector_of
from app.analysis import risk as rk
from app.core.config_file import AegisConfig, get_config
from app.market_data import service as md
from app.models import Portfolio, PortfolioSnapshot, Position, Stock
from app.risk import service as rs
from app.services.audit import record_audit

Status = Literal["PASS", "FAIL", "UNKNOWN"]


class PortfolioError(ValueError):
    pass


# ---------------------------------------------------------------- CRUD


def create(
    db: Session, *, name: str, kind: str, cash: Decimal, user: uuid.UUID | None
) -> Portfolio:
    if kind not in ("model", "paper"):
        raise PortfolioError("kind must be 'model' or 'paper'")
    if cash < 0:
        raise PortfolioError("cash must be non-negative")
    if db.scalar(select(Portfolio).where(Portfolio.name == name)):
        raise PortfolioError(f"portfolio {name!r} already exists")
    pf = Portfolio(name=name, kind=kind, starting_cash=cash, cash=cash, owner_id=user)
    db.add(pf)
    db.flush()
    record_audit(
        db,
        action="portfolio.create",
        actor_user_id=user,
        entity_type="portfolio",
        entity_id=str(pf.id),
        details={"name": name, "kind": kind, "cash": str(cash)},
    )
    return pf


def positions(db: Session, pf: Portfolio) -> list[tuple[Position, Stock]]:
    rows = db.execute(
        select(Position, Stock)
        .join(Stock, Stock.id == Position.stock_id)
        .where(Position.portfolio_id == pf.id)
        .order_by(Stock.symbol)
    ).all()
    return [(p, s) for p, s in rows]


def set_position(
    db: Session,
    pf: Portfolio,
    stock: Stock,
    quantity: int,
    avg_cost: Decimal,
    user: uuid.UUID | None,
) -> Position | None:
    """Model portfolios only. quantity 0 removes the holding."""
    if pf.kind != "model":
        raise PortfolioError("paper portfolios change only through recorded paper executions")
    if quantity < 0:
        raise PortfolioError("long-only: quantity must be >= 0")
    pos = db.scalar(
        select(Position).where(Position.portfolio_id == pf.id, Position.stock_id == stock.id)
    )
    before = {"quantity": pos.quantity, "avg_cost": str(pos.avg_cost)} if pos else None
    if quantity == 0:
        if pos:
            db.delete(pos)
        pos = None
    else:
        if avg_cost <= 0:
            raise PortfolioError("avg_cost must be positive")
        if pos is None:
            pos = Position(
                portfolio_id=pf.id, stock_id=stock.id, quantity=quantity, avg_cost=avg_cost
            )
            db.add(pos)
        else:
            pos.quantity, pos.avg_cost = quantity, avg_cost
    record_audit(
        db,
        action="portfolio.position.set",
        actor_user_id=user,
        entity_type="portfolio",
        entity_id=str(pf.id),
        details={
            "ticker": str(md.ticker_of(stock)),
            "before": before,
            "after": {"quantity": quantity, "avg_cost": str(avg_cost)} if quantity else None,
        },
    )
    db.flush()
    return pos


def set_cash(db: Session, pf: Portfolio, cash: Decimal, user: uuid.UUID | None) -> None:
    if pf.kind != "model":
        raise PortfolioError("paper portfolio cash changes only through paper executions")
    if cash < 0:
        raise PortfolioError("cash must be non-negative")
    record_audit(
        db,
        action="portfolio.cash.set",
        actor_user_id=user,
        entity_type="portfolio",
        entity_id=str(pf.id),
        details={"before": str(pf.cash), "after": str(cash)},
    )
    pf.cash = cash


# ------------------------------------------------------------ analytics


@dataclass
class Holding:
    ticker: str
    stock: Stock
    quantity: float
    avg_cost: float | None
    candidate: bool
    history: rs.History
    price: float | None = None
    price_date: date | None = None
    value: float | None = None
    sector: str = "unclassified"


def _check(
    name: str,
    kind: str,
    status: Status,
    value: float | None,
    limit: float | None,
    reason: str,
    offenders: list[str] | None = None,
) -> dict[str, Any]:
    return {
        "name": name,
        "kind": kind,
        "status": status,
        "value": value,
        "limit": limit,
        "reason": reason,
        "offenders": offenders or [],
    }


def _load(
    db: Session,
    stock: Stock,
    qty: float,
    cost: float | None,
    cand: bool,
    as_of: datetime,
    knowledge_at: datetime | None,
    cfg: AegisConfig,
) -> Holding:
    h = rs.load_history(db, stock, as_of, knowledge_at, cfg.risk_analysis.lookback_sessions)
    t = str(md.ticker_of(stock))
    hold = Holding(
        t, stock, qty, cost, cand, h, sector=sector_of(t) or stock.sector or "unclassified"
    )
    if h.traded:
        d, close, _ = h.traded[-1]
        hold.price, hold.price_date, hold.value = close, d, qty * close
    return hold


def analyze(
    db: Session,
    pf: Portfolio,
    as_of: datetime,
    knowledge_at: datetime | None = None,
    candidate: tuple[Stock, float] | None = None,
    *,
    candidate_quantity: int | None = None,
    candidate_price: float | None = None,
    _cache: dict[int, Holding] | None = None,
) -> dict[str, Any]:
    """Analysis of the portfolio as of `as_of`; with `candidate` = (stock,
    weight of CURRENT equity), analyses the portfolio after buying it from cash.
    `candidate_quantity` / `candidate_price` override the weight-derived
    quantity and the last close (used by the trade risk engine)."""
    cfg = get_config()
    rc, rules, liq = cfg.risk_controls, cfg.risk_analysis, cfg.liquidity
    cache = _cache if _cache is not None else {}
    holdings: list[Holding] = []
    for pos, stock in positions(db, pf):
        if stock.id not in cache:
            cache[stock.id] = _load(
                db, stock, pos.quantity, float(pos.avg_cost), False, as_of, knowledge_at, cfg
            )
        holdings.append(cache[stock.id])
    cash = float(pf.cash)
    warnings: list[str] = []
    unknown_price = [h.ticker for h in holdings if h.value is None]
    equity = cash + sum(h.value or 0.0 for h in holdings)

    cand_info: dict[str, Any] | None = None
    if candidate is not None:
        stock, weight = candidate
        if not 0 < weight <= 1:
            raise PortfolioError("candidate weight must be in (0, 1]")
        c = _load(db, stock, 0, None, True, as_of, knowledge_at, cfg)
        if c.price is None:
            unknown_price.append(c.ticker)
            cand_info = {
                "ticker": c.ticker,
                "weight": weight,
                "price": None,
                "quantity": 0,
                "value": None,
            }
        else:
            px = candidate_price if candidate_price is not None else c.price
            qty = (
                candidate_quantity
                if candidate_quantity is not None
                else math.floor(weight * equity / px)
            )
            existing = next((h for h in holdings if h.stock.id == stock.id), None)
            value = qty * c.price  # marked at the reference close
            cash -= qty * px  # pay the (limit) price
            cand_info = {
                "ticker": c.ticker,
                "weight": weight,
                "price": px,
                "quantity": qty,
                "value": value,
            }
            if existing is not None:
                holdings = [h for h in holdings if h is not existing]
                c.quantity, c.value = existing.quantity + qty, (existing.value or 0.0) + value
                c.avg_cost = existing.avg_cost
            else:
                c.quantity, c.value = qty, value
            holdings.append(c)
            if qty == 0:
                warnings.append(f"Target weight buys 0 shares of {c.ticker} at ₹{c.price:,.2f}")

    invested = sum(h.value or 0.0 for h in holdings)
    weights = {h.ticker: (h.value or 0.0) / equity if equity > 0 else 0.0 for h in holdings}
    sectors: dict[str, float] = {}
    for h in holdings:
        sectors[h.sector] = sectors.get(h.sector, 0.0) + weights[h.ticker]

    checks: list[dict[str, Any]] = []
    unk = f"price unknown for {', '.join(unknown_price)}" if unknown_price else ""
    top = max(weights.items(), key=lambda kv: kv[1], default=(None, 0.0))
    over = [t for t, w in weights.items() if w > rc.max_single_position_weight + 1e-9]
    checks.append(
        _check(
            "position_weight",
            "limit",
            "UNKNOWN" if unknown_price else "FAIL" if over else "PASS",
            top[1],
            rc.max_single_position_weight,
            unk
            or (
                f"Over limit: {', '.join(over)}"
                if over
                else f"Largest {top[0] or '—'} {top[1]:.1%}"
            ),
            over,
        )
    )
    classified = {s: w for s, w in sectors.items() if s != "unclassified"}
    s_top = max(classified.items(), key=lambda kv: kv[1], default=(None, 0.0))
    s_over = [s for s, w in classified.items() if w > rc.max_sector_weight + 1e-9]
    uncl = sectors.get("unclassified", 0.0)
    s_status: Status = (
        "UNKNOWN"
        if unknown_price
        else "FAIL"
        if s_over
        else "UNKNOWN"
        if uncl > rc.max_sector_weight
        else "PASS"
    )
    checks.append(
        _check(
            "sector_weight",
            "limit",
            s_status,
            s_top[1],
            rc.max_sector_weight,
            unk
            or (
                f"Over limit: {', '.join(s_over)}"
                if s_over
                else f"Unclassified holdings are {uncl:.1%} (sector unknown)"
                if s_status == "UNKNOWN"
                else f"Largest sector {s_top[0] or '—'} {s_top[1]:.1%}"
            ),
            s_over,
        )
    )
    gross = invested / equity if equity > 0 else 0.0
    checks.append(
        _check(
            "gross_exposure",
            "limit",
            "UNKNOWN"
            if unknown_price
            else "FAIL"
            if gross > rc.max_gross_exposure + 1e-9
            else "PASS",
            gross,
            rc.max_gross_exposure,
            unk or f"Invested {gross:.1%} of equity",
        )
    )
    checks.append(
        _check(
            "cash",
            "limit",
            "FAIL" if cash < -1e-6 else "PASS",
            cash,
            0.0,
            "Insufficient cash for the candidate" if cash < -1e-6 else f"Cash after ₹{cash:,.0f}",
        )
    )

    adtv: dict[str, float | None] = {}
    for h in holdings:
        adtv[h.ticker] = rk.average_daily_traded_value(
            [c for _, c, _ in h.history.traded],
            [v for _, _, v in h.history.traded],
            rules.adv_window_sessions,
        )
    illiquid = [
        t for t, a in adtv.items() if a is not None and a < liq.minimum_average_daily_traded_value
    ]
    no_vol = [t for t, a in adtv.items() if a is None]
    checks.append(
        _check(
            "liquidity",
            "limit",
            "FAIL" if illiquid else "UNKNOWN" if no_vol else "PASS",
            min((a for a in adtv.values() if a is not None), default=None),
            liq.minimum_average_daily_traded_value,
            f"Below minimum traded value: {', '.join(illiquid)}"
            if illiquid
            else f"Volume history missing: {', '.join(no_vol)}"
            if no_vol
            else "All holdings meet the traded-value minimum",
            illiquid,
        )
    )

    # --- return-based statistics over dates common to all priced holdings
    metrics: dict[str, float | None] = {
        "equity": equity,
        "cash": cash,
        "invested": invested,
        "gross_exposure": gross,
        "positions": float(len(holdings)),
    }
    hhi = rk.herfindahl(list(weights.values()))
    metrics["herfindahl"] = hhi if holdings else None
    metrics["effective_positions"] = (1 / hhi) if hhi > 0 else None
    corr: dict[str, dict[str, float]] = {}
    pairs: list[dict[str, Any]] = []
    priced = [h for h in holdings if len(h.history.closes) > 1]
    port_r: np.ndarray | None = None
    common: list[date] = []
    if priced:
        maps = {h.ticker: dict(h.history.closes) for h in priced}
        common = sorted(set.intersection(*(set(m) for m in maps.values())))
        if len(common) > rules.min_history_sessions // 2:
            rets = {t: rk.returns([m[d] for d in common]) for t, m in maps.items()}
            w = np.array([weights[t] for t in rets])
            port_r = np.vstack(list(rets.values())).T @ w
            if len(rets) > 1:
                corr = rk.correlation_matrix(rets)
                keys = sorted(rets)
                for i, a in enumerate(keys):
                    for b in keys[i + 1 :]:
                        if corr[a][b] >= rules.high_correlation:
                            pairs.append({"a": a, "b": b, "correlation": corr[a][b]})
                off = [corr[a][b] for i, a in enumerate(keys) for b in keys[i + 1 :]]
                metrics["average_pairwise_correlation"] = float(np.mean(off))
        else:
            warnings.append(
                f"Only {len(common)} common sessions across holdings: statistics skipped"
            )
    days = rules.trading_days_per_year
    if port_r is not None and len(port_r) >= 20:
        metrics["volatility_annual"] = rk.annual_volatility(port_r, days)
        metrics["sharpe"] = rk.sharpe(port_r, cfg.valuation.risk_free_rate, days)
        for conf in rules.var_confidence:
            v, cv = rk.var_cvar(port_r, conf)
            metrics[f"var_{round(conf * 100)}_1d"] = v
            metrics[f"cvar_{round(conf * 100)}_1d"] = cv
        nav = np.cumprod(1 + port_r)
        dd = rk.max_drawdown(list(zip(common[1:], nav.tolist(), strict=True)))
        metrics["simulated_max_drawdown"] = dd.max_drawdown
        bench = rs.benchmark(db, as_of, knowledge_at, rules.lookback_sessions, cfg)
        bmap = dict(bench)
        idx = [i for i, d in enumerate(common[1:]) if d in bmap]
        if len(idx) > 30:
            # benchmark returns between consecutive common dates it also has
            bd = [common[1:][i] for i in idx]
            b_r = rk.returns([bmap[d] for d in bd])
            p_nav = [nav[i] for i in idx]
            p_r = rk.returns(p_nav)
            metrics["beta"] = rk.beta_daily(p_r, b_r)
        else:
            metrics["beta"] = None
            warnings.append("Portfolio beta unavailable: NIFTY 50 history missing")
    checks.append(
        _check(
            "portfolio_drawdown",
            "advisory",
            "UNKNOWN"
            if metrics.get("simulated_max_drawdown") is None
            else "FAIL"
            if (metrics["simulated_max_drawdown"] or 0) > rc.max_portfolio_drawdown
            else "PASS",
            metrics.get("simulated_max_drawdown"),
            rc.max_portfolio_drawdown,
            "Current weights simulated over the lookback (not a track record)",
        )
    )
    checks.append(
        _check(
            "correlation",
            "advisory",
            "FAIL" if pairs else "PASS" if corr else "UNKNOWN",
            max((p["correlation"] for p in pairs), default=None),
            rules.high_correlation,
            f"{len(pairs)} highly correlated pair(s)"
            if pairs
            else "No highly correlated pairs"
            if corr
            else "Fewer than two holdings with common history",
        )
    )
    eff = metrics["effective_positions"]
    checks.append(
        _check(
            "concentration",
            "advisory",
            "UNKNOWN"
            if eff is None
            else "FAIL"
            if eff < rules.max_effective_positions_floor
            else "PASS",
            eff,
            float(rules.max_effective_positions_floor),
            "Effective number of positions = 1 / HHI",
        )
    )

    limits = [c for c in checks if c["kind"] == "limit"]
    overall: Status = (
        "FAIL"
        if any(c["status"] == "FAIL" for c in limits)
        else "UNKNOWN"
        if any(c["status"] == "UNKNOWN" for c in limits)
        else "PASS"
    )
    if any(h.history.licensed is False for h in holdings):
        warnings.append("Some prices come from unlicensed sources: research use only")
    return {
        "portfolio": {"id": pf.id, "name": pf.name, "kind": pf.kind, "currency": pf.base_currency},
        "as_of": as_of.isoformat(),
        "knowledge_at": knowledge_at.isoformat() if knowledge_at else None,
        "limits_status": overall,
        "holdings": [
            {
                "ticker": h.ticker,
                "quantity": h.quantity,
                "avg_cost": h.avg_cost,
                "price": h.price,
                "price_date": h.price_date.isoformat() if h.price_date else None,
                "value": h.value,
                "weight": weights[h.ticker],
                "sector": h.sector,
                "unrealised_pnl": (h.value - h.quantity * h.avg_cost)
                if h.value is not None and h.avg_cost
                else None,
                "adtv": adtv.get(h.ticker),
                "candidate": h.candidate,
            }
            for h in holdings
        ],
        "sector_weights": sectors,
        "checks": checks,
        "metrics": metrics,
        "correlation": corr,
        "high_correlation_pairs": pairs,
        "candidate": cand_info,
        "common_sessions": len(common),
        "warnings": warnings,
    }


# --------------------------------------------------- equity snapshots / losses


def record_snapshot(
    db: Session, pf: Portfolio, as_of: datetime, source: str = "eod"
) -> PortfolioSnapshot | None:
    """Mark the portfolio to market at as_of. Skipped (None) if any holding
    has no price: an unknown mark is never stored as if it were known."""
    a = analyze(db, pf, as_of)
    if any(h["value"] is None for h in a["holdings"]):
        return None
    m = a["metrics"]
    snap = PortfolioSnapshot(
        portfolio_id=pf.id,
        taken_at=as_of,
        equity=float(m["equity"] or 0.0),
        cash=float(m["cash"] or 0.0),
        invested=float(m["invested"] or 0.0),
        source=source,
    )
    db.add(snap)
    db.flush()
    return snap


def loss_state(
    db: Session, pf: Portfolio, equity_now: float, as_of: datetime
) -> tuple[float, float, float]:
    """(day change, week change, drawdown from peak) of equity, IST calendar.
    Baselines are the last snapshot before the IST day / ISO week started,
    falling back to the starting cash for a portfolio created within it."""
    ist = rs.IST_OFFSET
    local = as_of.astimezone(UTC) + ist
    day_start = datetime(local.year, local.month, local.day, tzinfo=UTC) - ist
    week_start = day_start - timedelta(days=local.weekday())
    snaps = db.scalars(
        select(PortfolioSnapshot)
        .where(PortfolioSnapshot.portfolio_id == pf.id, PortfolioSnapshot.taken_at <= as_of)
        .order_by(PortfolioSnapshot.taken_at)
    ).all()
    start = float(pf.starting_cash)

    def base(before: datetime) -> float:
        prior = [s.equity for s in snaps if s.taken_at < before]
        return prior[-1] if prior else start

    b_day, b_week = base(day_start), base(week_start)
    peak = max([start, equity_now, *(s.equity for s in snaps)])
    return (
        equity_now / b_day - 1 if b_day > 0 else 0.0,
        equity_now / b_week - 1 if b_week > 0 else 0.0,
        1 - equity_now / peak if peak > 0 else 0.0,
    )
