"""Deterministic DCF with bear / base / bull scenarios (spec §12).

Free cash flow to the firm is projected as revenue x FCF margin, revenue
compounding at the scenario growth rate for `years`, then a Gordon terminal
value. EV -> equity = EV - debt + cash -> per share. All assumptions are
returned with the result; nothing is hidden inside a single number.
"""

from __future__ import annotations

from dataclasses import dataclass, field


class DcfError(ValueError):
    pass


@dataclass(frozen=True)
class Assumptions:
    revenue: float
    growth: float
    fcf_margin: float
    wacc: float
    terminal_growth: float
    years: int
    debt: float
    cash: float
    shares: float


@dataclass
class DcfResult:
    assumptions: Assumptions
    fcf: list[float]
    pv_fcf: float
    terminal_value: float
    pv_terminal: float
    enterprise_value: float
    equity_value: float
    per_share: float
    terminal_share_of_ev: float
    notes: list[str] = field(default_factory=list)


def run_dcf(a: Assumptions) -> DcfResult:
    if a.wacc <= a.terminal_growth:
        raise DcfError(f"WACC {a.wacc:.2%} must exceed terminal growth {a.terminal_growth:.2%}")
    if a.shares <= 0 or a.revenue <= 0:
        raise DcfError("revenue and share count must be positive")
    fcf: list[float] = []
    rev = a.revenue
    pv = 0.0
    for t in range(1, a.years + 1):
        rev *= 1 + a.growth
        f = rev * a.fcf_margin
        fcf.append(f)
        pv += f / (1 + a.wacc) ** t
    tv = fcf[-1] * (1 + a.terminal_growth) / (a.wacc - a.terminal_growth)
    pv_tv = tv / (1 + a.wacc) ** a.years
    ev = pv + pv_tv
    equity = ev - a.debt + a.cash
    res = DcfResult(a, fcf, pv, tv, pv_tv, ev, equity, equity / a.shares, pv_tv / ev if ev else 0.0)
    if res.terminal_share_of_ev > 0.75:
        res.notes.append(
            f"Terminal value is {res.terminal_share_of_ev:.0%} of EV: highly sensitive to "
            "long-run assumptions"
        )
    return res


def sensitivity(
    a: Assumptions, wacc_steps: list[float], g_steps: list[float]
) -> list[list[float | None]]:
    """Per-share value grid: rows = WACC deltas, columns = terminal growth deltas."""
    grid: list[list[float | None]] = []
    for dw in wacc_steps:
        row: list[float | None] = []
        for dg in g_steps:
            try:
                row.append(
                    run_dcf(
                        Assumptions(
                            **{
                                **a.__dict__,
                                "wacc": a.wacc + dw,
                                "terminal_growth": a.terminal_growth + dg,
                            }
                        )
                    ).per_share
                )
            except DcfError:
                row.append(None)
        grid.append(row)
    return grid


def cost_of_capital(
    *,
    risk_free: float,
    erp: float,
    beta: float,
    market_cap: float,
    debt: float,
    interest_expense: float | None,
    tax_rate: float,
) -> tuple[float, dict[str, float]]:
    """CAPM cost of equity; pre-tax cost of debt = interest / debt (floored at
    the risk-free rate); market-value weights."""
    ke = risk_free + beta * erp
    kd_pre = (
        max(risk_free, abs(interest_expense) / debt) if debt > 0 and interest_expense else risk_free
    )
    kd = kd_pre * (1 - tax_rate)
    total = market_cap + debt
    we = market_cap / total if total > 0 else 1.0
    wacc = we * ke + (1 - we) * kd
    return wacc, {"cost_of_equity": ke, "cost_of_debt_after_tax": kd, "equity_weight": we}
