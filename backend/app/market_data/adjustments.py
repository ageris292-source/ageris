"""Deterministic price-basis conversions (spec §40).

Allowed conversions only:
    RAW            -> SPLIT_ADJUSTED   (needs splits)
    SPLIT_ADJUSTED -> TOTAL_RETURN     (needs split-adjusted dividends)
    RAW            -> TOTAL_RETURN     (both, in that order)
Anything else (e.g. adjusted -> raw) cannot be reconstructed and raises.

Back-adjustment convention: the most recent prices are left unchanged and
earlier prices are scaled, so today's price is the traded price.
"""

from __future__ import annotations

from datetime import date
from decimal import ROUND_HALF_EVEN, Decimal

from app.market_data.types import Bar, CorporateActionIn, PriceBasis

_Q = Decimal("0.0001")


class AdjustmentError(ValueError):
    pass


def _scale(b: Bar, price_factor: Decimal, volume_factor: Decimal) -> Bar:
    if price_factor == 1 and volume_factor == 1:
        return b
    return Bar(
        session=b.session,
        open=(b.open * price_factor).quantize(_Q, ROUND_HALF_EVEN),
        high=(b.high * price_factor).quantize(_Q, ROUND_HALF_EVEN),
        low=(b.low * price_factor).quantize(_Q, ROUND_HALF_EVEN),
        close=(b.close * price_factor).quantize(_Q, ROUND_HALF_EVEN),
        volume=int((Decimal(b.volume) * volume_factor).to_integral_value(ROUND_HALF_EVEN)),
    )


def raw_to_split_adjusted(bars: list[Bar], actions: list[CorporateActionIn]) -> list[Bar]:
    splits = sorted((a for a in actions if a.kind == "split"), key=lambda a: a.ex_date)
    for s in splits:
        if s.numerator is None or s.denominator is None:
            raise AdjustmentError(f"split on {s.ex_date} has no ratio")
    ordered = sorted(bars, key=lambda b: b.session)
    out: list[Bar] = []
    for b in ordered:
        factor = Decimal(1)
        for s in splits:
            if b.session < s.ex_date:
                assert s.numerator is not None and s.denominator is not None
                factor *= s.denominator / s.numerator
        out.append(_scale(b, factor, 1 / factor))
    return out


def split_adjusted_to_total_return(bars: list[Bar], actions: list[CorporateActionIn]) -> list[Bar]:
    """Dividend back-adjustment: every bar before ex-date E is multiplied by
    (1 - D / C_prev), where C_prev is the close of the session before E."""
    ordered = sorted(bars, key=lambda b: b.session)
    if not ordered:
        return []
    dividends = sorted((a for a in actions if a.kind == "dividend"), key=lambda a: a.ex_date)
    factors: list[tuple[date, Decimal]] = []
    for d in dividends:
        if d.amount is None:
            raise AdjustmentError(f"dividend on {d.ex_date} has no amount")
        if d.ex_date <= ordered[0].session or d.ex_date > ordered[-1].session:
            continue  # outside the series; no earlier bar to adjust
        prev = [b for b in ordered if b.session < d.ex_date][-1]
        if d.amount >= prev.close:
            raise AdjustmentError(f"dividend {d.amount} on {d.ex_date} >= previous close")
        factors.append((d.ex_date, 1 - d.amount / prev.close))

    out: list[Bar] = []
    for b in ordered:
        factor = Decimal(1)
        for ex_date, f in factors:
            if b.session < ex_date:
                factor *= f
        out.append(_scale(b, factor, Decimal(1)))
    return out


def convert(
    bars: list[Bar],
    source_basis: PriceBasis,
    target_basis: PriceBasis,
    actions: list[CorporateActionIn],
) -> list[Bar]:
    if source_basis == target_basis:
        return sorted(bars, key=lambda b: b.session)
    if source_basis == PriceBasis.RAW and target_basis == PriceBasis.SPLIT_ADJUSTED:
        return raw_to_split_adjusted(bars, actions)
    if source_basis == PriceBasis.SPLIT_ADJUSTED and target_basis == PriceBasis.TOTAL_RETURN:
        return split_adjusted_to_total_return(bars, actions)
    if source_basis == PriceBasis.RAW and target_basis == PriceBasis.TOTAL_RETURN:
        # Dividends from providers are quoted per share on the ex-date (raw);
        # restate them in split-adjusted terms before the dividend step.
        adjusted = raw_to_split_adjusted(bars, actions)
        return split_adjusted_to_total_return(adjusted, _split_adjust_dividends(actions))
    raise AdjustmentError(f"cannot derive {target_basis.value} prices from {source_basis.value}")


def _split_adjust_dividends(actions: list[CorporateActionIn]) -> list[CorporateActionIn]:
    splits = [a for a in actions if a.kind == "split"]
    out: list[CorporateActionIn] = []
    for a in actions:
        if a.kind != "dividend" or a.amount is None:
            continue
        factor = Decimal(1)
        for s in splits:
            if a.ex_date < s.ex_date and s.numerator and s.denominator:
                factor *= s.denominator / s.numerator
        out.append(a.model_copy(update={"amount": a.amount * factor}))
    return out
