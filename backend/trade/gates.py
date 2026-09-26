"""The Trade Risk Engine (spec §17-§19): 24 deterministic gates, fixed order.

`evaluate` is a PURE function of (proposal, context, config): no database,
no clock, no model. The same inputs always give the same decision and the
same hash. A proposal is APPROVED only if every applicable gate is PASS;
FAIL and UNKNOWN both reject. Exits (sells of an existing long) skip the
entry-only gates (NOT_APPLICABLE) so risk-reducing trades are never blocked
by profitability rules, but the kill switch, mode, data and execution
gates still apply.
"""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Any

from app.core.config_file import AegisConfig
from app.trade.costs import CostError, round_trip
from app.trade.probability import ProbabilityEstimate
from app.trade.schemas import CostBreakdown, GateResult, TradeProposal, TradeRiskDecision

ENGINE_VERSION = "trade-risk-engine-1.0.0"


@dataclass
class GateContext:
    """Everything the gates may look at, captured once (and stored with the
    decision so it can be replayed)."""

    as_of: datetime
    system_mode: str
    live_trading_enabled: bool
    broker_healthy: bool | None
    kill_switch_active: bool
    kill_switch_known: bool
    # instrument
    stock_found: bool
    exchange: str | None
    currency: str | None
    stock_active: bool
    delisted: bool
    # portfolio
    portfolio_kind: str | None
    equity: float | None
    cash: float | None
    held_quantity: int
    limits_status_after: str | None  # PASS / FAIL / UNKNOWN from portfolio analysis
    limit_failures_after: list[str] = field(default_factory=list)
    loss_daily: float | None = None  # negative = loss, fraction of equity
    loss_weekly: float | None = None
    drawdown: float | None = None  # positive fraction from peak equity
    # market data
    reference_price: float | None = None
    price_date: str | None = None
    price_licensed: bool | None = None
    price_source: str | None = None
    fresh: bool | None = None
    freshness_reason: str = ""
    data_quality: float | None = None
    adtv: float | None = None
    volatility: float | None = None
    # research
    report_id: int | None = None
    report_hash_ok: bool | None = None
    report_age_hours: float | None = None
    report_stance: str | None = None
    report_conflicts: int | None = None
    probability: ProbabilityEstimate | None = None

    def snapshot(self) -> dict[str, Any]:
        d = asdict(self)
        d["as_of"] = self.as_of.isoformat()
        if self.probability is not None:
            d["probability"] = {
                **asdict(self.probability),
                "as_of_date": self.probability.as_of_date.isoformat(),
            }
        return d


@dataclass
class _Eval:
    p: TradeProposal
    c: GateContext
    cfg: AegisConfig
    costs: CostBreakdown | None = None
    cost_error: str | None = None
    metrics: dict[str, float | None] = field(default_factory=dict)

    @property
    def entry(self) -> float:
        return float(self.p.entry_price)

    @property
    def value(self) -> float:
        return self.entry * self.p.quantity

    @property
    def is_exit(self) -> bool:
        return self.p.side == "sell"


Gate = tuple[str, bool, Callable[[_Eval], tuple[str, Any, Any, str]]]
# (name, applies_to_exits, fn -> (status, value, threshold, reason))


def _kill_switch(e: _Eval) -> tuple[str, Any, Any, str]:
    if not e.c.kill_switch_known:
        return "UNKNOWN", None, "inactive", "Kill switch state unreadable"
    if e.c.kill_switch_active:
        return "FAIL", "active", "inactive", "Kill switch is active: all trading halted"
    return "PASS", "inactive", "inactive", "Kill switch inactive"


def _execution_mode(e: _Eval) -> tuple[str, Any, Any, str]:
    if e.p.mode == "paper":
        ok = e.c.system_mode == "paper"
        return (
            "PASS" if ok else "FAIL",
            e.c.system_mode,
            "paper",
            "Paper trading enabled" if ok else f"System mode is {e.c.system_mode}, not paper",
        )
    if e.c.system_mode != "live" or not e.c.live_trading_enabled:
        return "FAIL", e.c.system_mode, "live + flag", "Live trading is disabled"
    if e.c.broker_healthy is None:
        return "UNKNOWN", None, "healthy", "Live broker health unknown"
    if not e.c.broker_healthy:
        return "FAIL", "unhealthy", "healthy", "Live broker unhealthy"
    return "PASS", "live", "live + flag", "Live mode, flag set, broker healthy"


def _portfolio_match(e: _Eval) -> tuple[str, Any, Any, str]:
    if e.c.portfolio_kind is None:
        return "FAIL", None, e.p.mode, "Portfolio not found"
    ok = e.c.portfolio_kind == e.p.mode
    return (
        "PASS" if ok else "FAIL",
        e.c.portfolio_kind,
        e.p.mode,
        "Portfolio matches the trading mode"
        if ok
        else f"{e.p.mode} orders need a {e.p.mode} portfolio (this one is {e.c.portfolio_kind})",
    )


def _instrument(e: _Eval) -> tuple[str, Any, Any, str]:
    c = e.c
    if not c.stock_found:
        return "FAIL", None, "NSE/BSE equity", "Unknown instrument"
    if c.exchange not in ("NSE", "BSE") or c.currency != "INR":
        return "FAIL", c.exchange, "NSE/BSE, INR", "Outside the Indian-equity scope"
    if not c.stock_active or c.delisted:
        return "FAIL", "inactive", "active", "Instrument inactive or delisted"
    if e.is_exit and c.held_quantity < e.p.quantity:
        return (
            "FAIL",
            c.held_quantity,
            e.p.quantity,
            f"Long-only: cannot sell {e.p.quantity}, holding {c.held_quantity}",
        )
    return "PASS", c.exchange, "NSE/BSE equity", "Listed Indian equity"


def _data_licensed(e: _Eval) -> tuple[str, Any, Any, str]:
    if e.c.price_licensed is None:
        return "UNKNOWN", None, True, "No stored prices"
    if not e.c.price_licensed:
        return "FAIL", e.c.price_source, "licensed", "Price source is unlicensed (research only)"
    return "PASS", e.c.price_source, "licensed", "Licensed price source"


def _data_freshness(e: _Eval) -> tuple[str, Any, Any, str]:
    if e.c.fresh is None:
        return "UNKNOWN", e.c.price_date, "fresh", e.c.freshness_reason or "Freshness unknown"
    return (
        "PASS" if e.c.fresh else "FAIL",
        e.c.price_date,
        "fresh",
        e.c.freshness_reason or ("Fresh" if e.c.fresh else "Stale"),
    )


def _data_quality(e: _Eval) -> tuple[str, Any, Any, str]:
    t = e.cfg.trade_gates.minimum_data_quality_score
    q = e.c.data_quality
    if q is None:
        return "UNKNOWN", None, t, "Data quality not measured"
    return ("PASS" if q >= t else "FAIL"), q, t, f"Quality {q:.2f} vs minimum {t:.2f}"


def _entry_deviation(e: _Eval) -> tuple[str, Any, Any, str]:
    t = e.cfg.execution.maximum_acceptable_entry_deviation
    ref = e.c.reference_price
    if ref is None or ref <= 0:
        return "UNKNOWN", None, t, "No reference price"
    dev = abs(e.entry - ref) / ref
    e.metrics["entry_deviation"] = dev
    return (
        "PASS" if dev <= t else "FAIL",
        dev,
        t,
        f"Entry ₹{e.entry:,.2f} vs reference ₹{ref:,.2f} ({dev:.2%})",
    )


def _research_report(e: _Eval) -> tuple[str, Any, Any, str]:
    t = e.cfg.trade_engine.max_report_age_hours
    c = e.c
    if c.report_id is None:
        return "UNKNOWN", None, t, "No research report for this stock"
    if not c.report_hash_ok:
        return "FAIL", c.report_id, "hash verified", "Report hash does not verify"
    if c.report_age_hours is None or c.report_age_hours < 0:
        return "FAIL", c.report_age_hours, t, "Report is dated after the evaluation time"
    ok = c.report_age_hours <= t
    return (
        "PASS" if ok else "FAIL",
        round(c.report_age_hours, 2),
        t,
        f"Report #{c.report_id} is {c.report_age_hours:.1f}h old (max {t:g}h)",
    )


def _research_stance(e: _Eval) -> tuple[str, Any, Any, str]:
    need = e.cfg.trade_engine.required_stance
    if e.c.report_stance is None:
        return "UNKNOWN", None, need, "No research stance"
    ok = e.c.report_stance == need
    return ("PASS" if ok else "FAIL"), e.c.report_stance, need, f"Stance {e.c.report_stance}"


def _agent_conflicts(e: _Eval) -> tuple[str, Any, Any, str]:
    t = e.cfg.trade_engine.max_agent_conflicts
    n = e.c.report_conflicts
    if n is None:
        return "UNKNOWN", None, t, "Conflicts unknown"
    return ("PASS" if n <= t else "FAIL"), n, t, f"{n} agent conflict(s) (max {t})"


def _prob(e: _Eval) -> ProbabilityEstimate | None:
    pr = e.c.probability
    if pr is not None and pr.horizon_days != e.p.horizon_days:
        return None
    return pr


def _model_calibration(e: _Eval) -> tuple[str, Any, Any, str]:
    t = e.cfg.trade_gates.maximum_calibration_error
    pr = _prob(e)
    if pr is None:
        return "UNKNOWN", None, t, "No calibrated model estimate for this horizon"
    if not pr.calibrated:
        return "FAIL", pr.calibration_error, t, f"Model {pr.model_id} is not calibrated"
    ok = pr.calibration_error <= t
    return (
        "PASS" if ok else "FAIL",
        pr.calibration_error,
        t,
        f"Calibration error {pr.calibration_error:.3f} (max {t:.3f}) · model {pr.model_id}",
    )


def _out_of_sample(e: _Eval) -> tuple[str, Any, Any, str]:
    t = e.cfg.trade_gates.minimum_out_of_sample_periods
    pr = _prob(e)
    if pr is None:
        return "UNKNOWN", None, t, "No model estimate"
    ok = pr.oos_periods >= t
    return "PASS" if ok else "FAIL", pr.oos_periods, t, f"{pr.oos_periods} out-of-sample folds"


def _ensure_costs(e: _Eval) -> None:
    if e.costs is None and e.cost_error is None:
        s = e.cfg.trade_engine.cost_schedule
        try:
            e.costs = round_trip(
                s,
                e.cfg.transaction_costs[s],
                e.value,
                e.c.adtv,
                e.p.horizon_days,
                e.p.quoted_spread_bps,
            )
            e.metrics["round_trip_cost"] = e.costs.round_trip_fraction
        except CostError as exc:
            e.cost_error = str(exc)


def _probability_of_profit(e: _Eval) -> tuple[str, Any, Any, str]:
    t = e.cfg.trade_gates.minimum_probability_of_profit
    pr = _prob(e)
    if pr is None:
        return "UNKNOWN", None, t, "No model estimate"
    e.metrics["probability_of_profit"] = pr.p_profit
    ok = pr.p_profit >= t
    return "PASS" if ok else "FAIL", pr.p_profit, t, f"P(profit) {pr.p_profit:.2f} (min {t:.2f})"


def _expected_net(e: _Eval) -> tuple[str, Any, Any, str]:
    t = e.cfg.trade_gates.minimum_expected_net_return
    pr = _prob(e)
    _ensure_costs(e)
    if pr is None:
        return "UNKNOWN", None, t, "No model estimate"
    if e.costs is None:
        return "UNKNOWN", None, t, f"Costs unknown: {e.cost_error}"
    net = pr.expected_return - e.costs.round_trip_fraction
    e.metrics["expected_net_return"] = net
    return (
        "PASS" if net >= t else "FAIL",
        net,
        t,
        f"Expected {pr.expected_return:.2%} gross - {e.costs.round_trip_fraction:.2%} costs "
        f"= {net:.2%} net (min {t:.0%})",
    )


def _edge(e: _Eval) -> tuple[str, Any, Any, str]:
    t = e.cfg.trade_gates.minimum_edge_vs_benchmark
    net = e.metrics.get("expected_net_return")
    if net is None:
        return "UNKNOWN", None, t, "Expected net return unknown"
    bench = (1 + e.cfg.trade_engine.benchmark_expected_annual_return) ** (
        e.p.horizon_days / 252
    ) - 1
    edge = net - bench
    e.metrics["edge_vs_benchmark"] = edge
    return (
        "PASS" if edge >= t else "FAIL",
        edge,
        t,
        f"Net {net:.2%} vs benchmark {bench:.2%} over {e.p.horizon_days}d = edge {edge:.2%}",
    )


def _trade_plan(e: _Eval) -> tuple[str, Any, Any, str]:
    te = e.cfg.trade_engine
    p = e.p
    if p.stop_loss is None or p.target is None:
        return "FAIL", None, "stop < entry < target", "Entry needs both a stop-loss and a target"
    if not p.stop_loss < p.entry_price < p.target:
        return "FAIL", None, "stop < entry < target", "Stop must be below entry, target above"
    if not te.min_holding_days <= p.horizon_days <= te.max_holding_days:
        return (
            "FAIL",
            p.horizon_days,
            f"{te.min_holding_days}-{te.max_holding_days}",
            "Horizon outside the allowed holding period",
        )
    return "PASS", None, "stop < entry < target", "Stop, target and horizon are consistent"


def _reward_risk(e: _Eval) -> tuple[str, Any, Any, str]:
    t = e.cfg.trade_gates.minimum_reward_risk_ratio
    p = e.p
    _ensure_costs(e)
    if p.stop_loss is None or p.target is None or not p.stop_loss < p.entry_price < p.target:
        return "FAIL", None, t, "Invalid trade plan"
    if e.costs is None:
        return "UNKNOWN", None, t, f"Costs unknown: {e.cost_error}"
    cost = e.costs.round_trip_fraction
    up = float(p.target) / e.entry - 1 - cost
    down = 1 - float(p.stop_loss) / e.entry + cost
    rr = up / down
    e.metrics["reward_risk"] = rr
    return "PASS" if rr >= t else "FAIL", rr, t, f"Net reward {up:.2%} / net risk {down:.2%}"


def _liquidity(e: _Eval) -> tuple[str, Any, Any, str]:
    t = e.cfg.liquidity.minimum_average_daily_traded_value
    a = e.c.adtv
    if a is None:
        return "UNKNOWN", None, t, "Average daily traded value unknown"
    return (
        "PASS" if a >= t else "FAIL",
        a,
        t,
        f"ADTV ₹{a / 1e7:,.1f} cr (min ₹{t / 1e7:,.1f} cr)",
    )


def _participation(e: _Eval) -> tuple[str, Any, Any, str]:
    t = e.cfg.liquidity.maximum_participation_of_adv
    a = e.c.adtv
    if a is None or a <= 0:
        return "UNKNOWN", None, t, "Average daily traded value unknown"
    part = e.value / a
    e.metrics["participation"] = part
    return (
        "PASS" if part <= t else "FAIL",
        part,
        t,
        f"Order ₹{e.value:,.0f} is {part:.3%} of ADTV (max {t:.2%})",
    )


def _spread(e: _Eval) -> tuple[str, Any, Any, str]:
    t = e.cfg.liquidity.maximum_spread_bps
    s = e.p.quoted_spread_bps
    if s is None:
        return "UNKNOWN", None, t, "No live quote: spread unknown"
    return "PASS" if s <= t else "FAIL", s, t, f"Spread {s:.1f} bps (max {t:g})"


def _position_sizing(e: _Eval) -> tuple[str, Any, Any, str]:
    ps = e.cfg.position_sizing
    eq = e.c.equity
    p = e.p
    if eq is None or eq <= 0:
        return "UNKNOWN", None, None, "Portfolio equity unknown"
    if p.stop_loss is None or p.stop_loss >= p.entry_price:
        return "FAIL", None, None, "Sizing needs a stop below entry"
    risk_per_share = e.entry - float(p.stop_loss)
    caps = {
        "risk_per_trade": math.floor(eq * ps.risk_per_trade / risk_per_share),
        "max_order_value": math.floor(eq * e.cfg.trade_engine.max_order_value_fraction / e.entry),
    }
    if ps.method == "volatility_target":
        if e.c.volatility is None or e.c.volatility <= 0:
            return "UNKNOWN", None, None, "Volatility unknown for volatility targeting"
        w = min(1.0, ps.target_annual_volatility / e.c.volatility)
        caps["volatility_target"] = math.floor(eq * w / e.entry)
    elif ps.method == "fractional_kelly":
        pr = _prob(e)
        rr = e.metrics.get("reward_risk")
        if pr is None or rr is None or rr <= 0:
            return "UNKNOWN", None, None, "Kelly sizing needs a probability and reward/risk"
        f = max(0.0, pr.p_profit - (1 - pr.p_profit) / rr)
        caps["fractional_kelly"] = math.floor(eq * ps.kelly_fraction_cap * f / e.entry)
    limit = min(caps.values())
    e.metrics["max_quantity"] = float(limit)
    binding = min(caps, key=lambda k: caps[k])
    return (
        "PASS" if p.quantity <= limit else "FAIL",
        p.quantity,
        limit,
        f"Quantity {p.quantity} vs max {limit} ({binding}; method {ps.method})",
    )


def _portfolio_limits(e: _Eval) -> tuple[str, Any, Any, str]:
    s = e.c.limits_status_after
    if s is None:
        return "UNKNOWN", None, "PASS", "Post-trade portfolio limits not evaluated"
    fails = ", ".join(e.c.limit_failures_after)
    return (
        s,
        s,
        "PASS",
        "All post-trade portfolio limits pass" if s == "PASS" else f"Post-trade: {fails or s}",
    )


def _loss_limits(e: _Eval) -> tuple[str, Any, Any, str]:
    rc = e.cfg.risk_controls
    c = e.c
    if c.loss_daily is None or c.loss_weekly is None or c.drawdown is None:
        return "UNKNOWN", None, None, "Portfolio loss history unknown"
    breaches = []
    if c.loss_daily <= -rc.daily_loss_limit:
        breaches.append(f"daily {c.loss_daily:.2%}")
    if c.loss_weekly <= -rc.weekly_loss_limit:
        breaches.append(f"weekly {c.loss_weekly:.2%}")
    if c.drawdown >= rc.max_portfolio_drawdown:
        breaches.append(f"drawdown {c.drawdown:.2%}")
    return (
        "FAIL" if breaches else "PASS",
        c.drawdown,
        rc.max_portfolio_drawdown,
        "Loss limits breached: " + ", ".join(breaches)
        if breaches
        else f"Day {c.loss_daily:+.2%}, week {c.loss_weekly:+.2%}, drawdown {c.drawdown:.2%}",
    )


GATES: list[Gate] = [
    ("kill_switch", True, _kill_switch),
    ("execution_mode", True, _execution_mode),
    ("portfolio_match", True, _portfolio_match),
    ("instrument", True, _instrument),
    ("data_licensed", True, _data_licensed),
    ("data_freshness", True, _data_freshness),
    ("data_quality", True, _data_quality),
    ("entry_deviation", True, _entry_deviation),
    ("research_report", False, _research_report),
    ("research_stance", False, _research_stance),
    ("agent_conflicts", False, _agent_conflicts),
    ("model_calibration", False, _model_calibration),
    ("out_of_sample", False, _out_of_sample),
    ("probability_of_profit", False, _probability_of_profit),
    ("expected_net_return", False, _expected_net),
    ("edge_vs_benchmark", False, _edge),
    ("trade_plan", False, _trade_plan),
    ("reward_risk", False, _reward_risk),
    ("liquidity", False, _liquidity),
    ("participation", True, _participation),
    ("spread", True, _spread),
    ("position_sizing", False, _position_sizing),
    ("portfolio_limits", False, _portfolio_limits),
    ("loss_limits", False, _loss_limits),
]
assert len(GATES) == 24


def decision_hash(d: TradeRiskDecision) -> str:
    body = d.model_dump(mode="json", exclude={"decision_hash", "evaluated_at"})
    return hashlib.sha256(json.dumps(body, sort_keys=True).encode()).hexdigest()


def evaluate(
    proposal: TradeProposal, ctx: GateContext, cfg: AegisConfig, evaluated_at: datetime
) -> TradeRiskDecision:
    e = _Eval(proposal, ctx, cfg)
    results: list[GateResult] = []
    for i, (name, for_exits, fn) in enumerate(GATES, start=1):
        if e.is_exit and not for_exits:
            results.append(
                GateResult(
                    order=i, name=name, status="NOT_APPLICABLE", reason="Entry-only gate; exit"
                )
            )
            continue
        try:
            status, value, threshold, reason = fn(e)
        except Exception as exc:  # a crashing gate never passes
            status, value, threshold, reason = "FAIL", None, None, f"Gate error: {exc!r}"
        results.append(
            GateResult(
                order=i,
                name=name,
                status=status,
                value=_clean(value),
                threshold=_clean(threshold),
                reason=reason,
            )
        )
    _ensure_costs(e)
    failed = [g.name for g in results if g.status in ("FAIL", "UNKNOWN")]
    d = TradeRiskDecision(
        decision="REJECTED" if failed else "APPROVED",
        engine_version=ENGINE_VERSION,
        evaluated_at=evaluated_at,
        as_of=ctx.as_of,
        proposal=proposal,
        gates=results,
        failed_gates=failed,
        first_failure=failed[0] if failed else None,
        requires_human_approval=True,
        costs=e.costs,
        metrics=e.metrics,
        context=ctx.snapshot(),
        config_fingerprint=cfg.fingerprint(),
    )
    d.decision_hash = decision_hash(d)
    return d


def _clean(v: Any) -> float | str | None:
    if v is None or isinstance(v, str):
        return v
    if isinstance(v, bool):
        return str(v)
    if isinstance(v, int | float):
        return float(v)
    return str(v)


def self_test(cfg: AegisConfig) -> tuple[bool, str]:
    """Health check: 24 gates loaded and an all-unknown context is rejected
    at the first gate. Used by execution readiness (never passes on error)."""
    try:
        if len(GATES) != 24:
            return False, f"expected 24 gates, found {len(GATES)}"
        from datetime import UTC
        from decimal import Decimal

        t = datetime(2000, 1, 3, tzinfo=UTC)
        p = TradeProposal(
            ticker="TEST.NS", side="buy", quantity=1, entry_price=Decimal(1), portfolio_id=0
        )
        ctx = GateContext(
            as_of=t,
            system_mode="research",
            live_trading_enabled=False,
            broker_healthy=None,
            kill_switch_active=True,
            kill_switch_known=False,
            stock_found=False,
            exchange=None,
            currency=None,
            stock_active=False,
            delisted=False,
            portfolio_kind=None,
            equity=None,
            cash=None,
            held_quantity=0,
            limits_status_after=None,
        )
        d = evaluate(p, ctx, cfg, t)
        if d.decision != "REJECTED" or d.first_failure != "kill_switch":
            return False, "self-test proposal was not rejected at the kill switch"
        if len(d.failed_gates) != 24:
            return False, "self-test: an all-unknown context passed some gate"
        return True, f"{ENGINE_VERSION}: 24 gates, self-test passed"
    except Exception as exc:
        return False, f"self-test error: {exc.__class__.__name__}"


GATE_DESCRIPTIONS: dict[str, str] = {
    "kill_switch": "Kill switch must be readable and inactive.",
    "execution_mode": "Paper orders need paper mode; live needs live mode, the live flag and a "
    "healthy broker.",
    "portfolio_match": "The portfolio's kind must match the order mode (paper/live).",
    "instrument": "Active NSE/BSE equity in INR; sells cannot exceed the held quantity "
    "(long-only).",
    "data_licensed": "Prices must come from a licensed source (unlicensed = research only).",
    "data_freshness": "Latest bar must be within the freshness rule.",
    "data_quality": "Price-series quality score at least the minimum.",
    "entry_deviation": "Limit price within the maximum deviation of the reference price.",
    "research_report": "A hash-verified research report no older than the maximum age.",
    "research_stance": "The report's stance must be the required one (POSITIVE_TILT).",
    "agent_conflicts": "No more agent conflicts than allowed.",
    "model_calibration": "A calibrated model estimate for this horizon with low calibration error.",
    "out_of_sample": "The model has enough walk-forward out-of-sample folds.",
    "probability_of_profit": "Calibrated P(net return > 0) at least the minimum.",
    "expected_net_return": "Model expected return minus modelled round-trip costs at least the "
    "minimum.",
    "edge_vs_benchmark": "Expected net return beats the benchmark over the horizon by the "
    "minimum edge.",
    "trade_plan": "Stop < entry < target and the horizon is within the holding-period bounds.",
    "reward_risk": "Net-of-cost reward/risk ratio at least the minimum.",
    "liquidity": "Average daily traded value at least the minimum.",
    "participation": "Order value at most the maximum share of average daily traded value.",
    "spread": "Quoted spread known and at most the maximum.",
    "position_sizing": "Quantity within the sizing method's limit and the per-order value cap.",
    "portfolio_limits": "Every post-trade portfolio limit (position, sector, gross, cash, "
    "liquidity) passes.",
    "loss_limits": "Daily and weekly loss limits and the portfolio drawdown limit are not "
    "breached.",
}
assert set(GATE_DESCRIPTIONS) == {g[0] for g in GATES}
