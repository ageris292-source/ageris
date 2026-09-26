"""Build the Trade Risk Engine's input context from the database.

Everything is read at one `as_of`; anything that cannot be determined is
left as None, which the gates treat as UNKNOWN (reject).
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.analysis import risk as rk
from app.core.config_file import get_config
from app.core.settings import get_settings
from app.live.broker import get_broker
from app.market_data import service as md
from app.market_data.types import InvalidTickerError, Ticker
from app.models import AnalysisReport, Portfolio, Position, Stock
from app.orchestrator import service as orch
from app.portfolio import service as ps
from app.risk import service as rs
from app.services.trading_controls import read_kill_switch
from app.trade import probability
from app.trade.gates import GateContext
from app.trade.schemas import TradeProposal


def _stock(db: Session, ticker: str) -> Stock | None:
    try:
        return md.get_stock(db, Ticker.parse(ticker))
    except (InvalidTickerError, md.StockNotFoundError):
        return None


def build(
    db: Session,
    p: TradeProposal,
    as_of: datetime,
    *,
    broker_healthy: bool | None = None,
) -> tuple[GateContext, Stock | None]:
    cfg = get_config()
    s = get_settings()
    ks = read_kill_switch(db)
    if broker_healthy is None:  # from the live adapter: always unknown in this build
        broker_healthy = get_broker().status().healthy
    stock = _stock(db, p.ticker)
    pf = db.get(Portfolio, p.portfolio_id)
    ctx = GateContext(
        as_of=as_of,
        system_mode=s.system_mode.value,
        live_trading_enabled=s.live_trading_enabled,
        broker_healthy=broker_healthy,
        kill_switch_active=ks.active,
        kill_switch_known=ks.known,
        stock_found=stock is not None,
        exchange=stock.exchange if stock else None,
        currency=stock.currency if stock else None,
        stock_active=bool(stock and stock.is_active),
        delisted=bool(stock and stock.delisted_on and stock.delisted_on <= as_of.date()),
        portfolio_kind=pf.kind if pf else None,
        equity=None,
        cash=None,
        held_quantity=0,
        limits_status_after=None,
    )
    if stock is not None:
        h = rs.load_history(db, stock, as_of, None, cfg.risk_analysis.lookback_sessions)
        if h.traded:
            d, close, _ = h.traded[-1]
            ctx.reference_price, ctx.price_date = close, d.isoformat()
            fr = md.freshness_for_date(d, as_of, cfg)
            ctx.fresh, ctx.freshness_reason = fr.status == "PASS", fr.reason
            ctx.price_licensed, ctx.price_source = h.licensed, h.source
            ctx.data_quality = h.report.quality_score if h.report else None
            ctx.adtv = rk.average_daily_traded_value(
                [c for _, c, _ in h.traded],
                [v for _, _, v in h.traded],
                cfg.risk_analysis.adv_window_sessions,
            )
            r = rk.returns([v for _, v in h.closes])
            ctx.volatility = rk.annual_volatility(r, cfg.risk_analysis.trading_days_per_year)
        q = select(AnalysisReport).where(
            AnalysisReport.stock_id == stock.id, AnalysisReport.created_at <= as_of
        )
        if p.report_id is not None:
            q = q.where(AnalysisReport.id == p.report_id)
        rep = db.scalar(q.order_by(AnalysisReport.created_at.desc()).limit(1))
        if rep is not None:
            ctx.report_id = rep.id
            ctx.report_hash_ok = orch.verify(rep)
            ctx.report_age_hours = (as_of - rep.created_at).total_seconds() / 3600
            ctx.report_stance = rep.stance
            ctx.report_conflicts = len(rep.report.get("synthesis", {}).get("conflicts", []))
        ctx.probability = probability.estimate(db, stock, as_of, p.horizon_days)

    if pf is not None:
        before = ps.analyze(db, pf, as_of)
        eq = before["metrics"].get("equity")
        unknown = any(x["value"] is None for x in before["holdings"])
        ctx.equity = None if unknown else eq
        ctx.cash = before["metrics"].get("cash")
        if stock is not None:
            pos = db.scalar(
                select(Position).where(
                    Position.portfolio_id == pf.id, Position.stock_id == stock.id
                )
            )
            ctx.held_quantity = pos.quantity if pos else 0
        if stock is not None and p.side == "buy" and ctx.equity:
            after = ps.analyze(
                db,
                pf,
                as_of,
                candidate=(stock, min(1.0, p.quantity * float(p.entry_price) / ctx.equity)),
                candidate_quantity=p.quantity,
                candidate_price=float(p.entry_price),
            )
            ctx.limits_status_after = after["limits_status"]
            ctx.limit_failures_after = [
                f"{c['name']}: {c['reason']}"
                for c in after["checks"]
                if c["kind"] == "limit" and c["status"] != "PASS"
            ]
        if ctx.equity is not None:
            ctx.loss_daily, ctx.loss_weekly, ctx.drawdown = ps.loss_state(db, pf, ctx.equity, as_of)
    return ctx, stock
