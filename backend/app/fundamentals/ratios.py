"""Deterministic financial ratios (spec §9, §50). Missing inputs give None —
a ratio is never computed from a substituted zero."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date


def _div(a: float | None, b: float | None) -> float | None:
    if a is None or b is None or b == 0:
        return None
    return a / b


def _growth(cur: float | None, prev: float | None) -> float | None:
    if cur is None or prev is None or prev <= 0:
        return None  # growth off a zero/negative base is not meaningful
    return cur / prev - 1


@dataclass
class PeriodRatios:
    period_end: date
    values: dict[str, float] = field(default_factory=dict)
    ratios: dict[str, float | None] = field(default_factory=dict)


def annual_ratios(periods: dict[date, dict[str, float]]) -> list[PeriodRatios]:
    """`periods`: annual period_end -> line items. Returns oldest -> newest."""
    out: list[PeriodRatios] = []
    ends = sorted(periods)
    for i, end in enumerate(ends):
        v = periods[end]
        prev = periods[ends[i - 1]] if i > 0 else {}
        g = v.get
        rev, ni, ebit = g("revenue"), g("net_income"), g("ebit") or g("operating_income")
        equity, prev_equity = g("equity"), prev.get("equity")
        avg_equity = (equity + prev_equity) / 2 if equity is not None and prev_equity else equity
        fcf = g("free_cash_flow")
        ocf, capex = g("operating_cash_flow"), g("capex")
        if fcf is None and ocf is not None and capex is not None:
            fcf = ocf + capex  # capex is reported negative
        assets, cur_liab = g("total_assets"), g("current_liabilities")
        cap_employed = assets - cur_liab if assets is not None and cur_liab is not None else None
        interest = g("interest_expense")
        r: dict[str, float | None] = {
            "revenue_growth": _growth(rev, prev.get("revenue")),
            "eps_growth": _growth(g("eps_diluted"), prev.get("eps_diluted")),
            "net_income_growth": _growth(ni, prev.get("net_income")),
            "gross_margin": _div(g("gross_profit"), rev),
            "operating_margin": _div(g("operating_income"), rev),
            "net_margin": _div(ni, rev),
            "free_cash_flow": fcf,
            "fcf_conversion": _div(fcf, ni) if ni and ni > 0 else None,
            "ocf_to_net_income": _div(g("operating_cash_flow"), ni) if ni and ni > 0 else None,
            "roe": _div(ni, avg_equity) if avg_equity and avg_equity > 0 else None,
            "roce": _div(ebit, cap_employed) if cap_employed and cap_employed > 0 else None,
            "debt_to_equity": _div(g("total_debt"), equity) if equity and equity > 0 else None,
            "interest_coverage": _div(ebit, abs(interest)) if interest else None,
            "cash": g("cash"),
            "eps": g("eps_diluted"),
        }
        out.append(PeriodRatios(end, dict(v), r))
    return out


def valuation(
    price: float,
    latest: dict[str, float],
    eps_growth: float | None,
) -> dict[str, float | None]:
    """Market multiples from the latest annual figures and a price."""
    shares = latest.get("shares_diluted")
    eps = latest.get("eps_diluted")
    mcap = price * shares if shares else None
    debt, cash = latest.get("total_debt"), latest.get("cash")
    ev = (
        mcap + (debt or 0) - (cash or 0)
        if mcap is not None and debt is not None and cash is not None
        else None
    )
    pe = price / eps if eps and eps > 0 else None
    return {
        "market_cap": mcap,
        "enterprise_value": ev,
        "pe": pe,
        "pb": _div(mcap, latest.get("equity")) if latest.get("equity", 0) > 0 else None,
        "ev_ebitda": _div(ev, latest.get("ebitda")) if latest.get("ebitda", 0) > 0 else None,
        "peg": pe / (eps_growth * 100) if pe and eps_growth and eps_growth > 0 else None,
        "earnings_yield": _div(eps, price) if eps else None,
        "fcf_yield": _div(latest.get("free_cash_flow"), mcap),
    }
