"""Round-trip transaction-cost model (spec §20) from a configured schedule.

All components are basis points of traded value, per side. GST applies to
brokerage + exchange + regulatory fees. Market impact scales linearly with
participation (% of average daily traded value). Financing accrues over the
holding period. Fixed per-order charges (e.g. depository fees) are not
modelled and must be covered by the slippage allowance.
"""

from __future__ import annotations

from app.core.config_file import CostSchedule
from app.trade.schemas import CostBreakdown


class CostError(ValueError):
    pass


def round_trip(
    name: str,
    s: CostSchedule,
    order_value: float,
    adtv: float | None,
    holding_days: int,  # trading days
    spread_bps: float | None = None,
) -> CostBreakdown:
    if order_value <= 0:
        raise CostError("order value must be positive")
    if adtv is None or adtv <= 0:
        raise CostError("average daily traded value unknown: impact cannot be modelled")
    participation = order_value / adtv * 100
    fees = s.brokerage_bps + s.exchange_fee_bps + s.regulatory_fee_bps
    gst = fees * s.gst_rate_on_fees
    half_spread = spread_bps / 2 if spread_bps is not None else s.half_spread_bps
    impact = s.market_impact_bps_per_pct_adv * participation
    common = fees + gst + s.securities_tax_bps + s.slippage_bps + half_spread + impact
    buy = common + s.stamp_duty_buy_bps
    sell = common
    financing = s.annual_financing_rate * holding_days / 252
    return CostBreakdown(
        schedule=name,
        buy_bps=round(buy, 4),
        sell_bps=round(sell, 4),
        impact_bps_each_side=round(impact, 4),
        financing_fraction=financing,
        round_trip_fraction=(buy + sell) / 1e4 + financing,
        order_value=order_value,
        participation_pct_of_adv=participation,
        items_bps={
            "brokerage": s.brokerage_bps,
            "exchange": s.exchange_fee_bps,
            "regulatory": s.regulatory_fee_bps,
            "gst": round(gst, 4),
            "securities_tax": s.securities_tax_bps,
            "stamp_duty_buy": s.stamp_duty_buy_bps,
            "slippage": s.slippage_bps,
            "half_spread": half_spread,
            "impact": round(impact, 4),
        },
    )
