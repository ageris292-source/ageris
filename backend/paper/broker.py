"""Simulated paper broker fills (spec §28).

Fill = reference price (latest available close) moved AGAINST the order by
slippage + half spread + market impact; statutory fees are charged in cash.
Deterministic, and never better than the reference price.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal

from app.core.config_file import CostSchedule

PAISE = Decimal("0.01")
TICK = Decimal("0.0001")


@dataclass(frozen=True)
class Fill:
    reference_price: Decimal
    fill_price: Decimal
    notional: Decimal
    fees: Decimal
    fee_breakdown: dict[str, str]
    adverse_bps: float


def simulate_fill(
    side: str,
    quantity: int,
    reference: Decimal,
    s: CostSchedule,
    adtv: float | None,
    spread_bps: float | None,
) -> Fill:
    notional_ref = float(reference) * quantity
    impact = s.market_impact_bps_per_pct_adv * (notional_ref / adtv * 100) if adtv else 0.0
    half = spread_bps / 2 if spread_bps is not None else s.half_spread_bps
    adverse = s.slippage_bps + half + impact
    factor = Decimal(str(1 + adverse / 1e4)) if side == "buy" else Decimal(str(1 - adverse / 1e4))
    price = (reference * factor).quantize(TICK, ROUND_HALF_UP)
    notional = (price * quantity).quantize(PAISE, ROUND_HALF_UP)

    def bps(x: float) -> Decimal:
        return (notional * Decimal(str(x)) / Decimal(10_000)).quantize(PAISE, ROUND_HALF_UP)

    fees = {
        "brokerage": bps(s.brokerage_bps),
        "exchange": bps(s.exchange_fee_bps),
        "regulatory": bps(s.regulatory_fee_bps),
        "securities_tax": bps(s.securities_tax_bps),
        "stamp_duty": bps(s.stamp_duty_buy_bps) if side == "buy" else Decimal("0.00"),
    }
    fees["gst"] = (
        (fees["brokerage"] + fees["exchange"] + fees["regulatory"])
        * Decimal(str(s.gst_rate_on_fees))
    ).quantize(PAISE, ROUND_HALF_UP)
    total = sum(fees.values(), Decimal("0.00"))
    return Fill(reference, price, notional, total, {k: str(v) for k, v in fees.items()}, adverse)
