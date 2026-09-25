"""Deterministic bar validation and price-basis conversions."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from app.core.config_file import get_config
from app.market_data.adjustments import (
    AdjustmentError,
    convert,
    raw_to_split_adjusted,
    split_adjusted_to_total_return,
)
from app.market_data.calendar import get_calendar
from app.market_data.types import Bar, CorporateActionIn, PriceBasis
from app.market_data.validation import validate_bars
from tests.market_helpers import NOW

CAL = get_calendar()
RULES = get_config().market_data
SESSIONS = CAL.sessions(date(2026, 8, 3), date(2026, 9, 25))


def bar(d: date, c: str | Decimal = "100", **kw: object) -> Bar:
    c = Decimal(c)
    data: dict[str, object] = {
        "session": d,
        "open": c,
        "high": c + 1,
        "low": c - 1,
        "close": c,
        "volume": 1000,
    }
    data.update(kw)
    return Bar.model_validate(data)


def clean_series() -> list[Bar]:
    return [bar(d, str(100 + i % 3)) for i, d in enumerate(SESSIONS)]


def run(bars: list[Bar], actions: list[CorporateActionIn] | None = None):  # type: ignore[no-untyped-def]
    return validate_bars(
        bars, CAL, RULES, now=NOW, window=(SESSIONS[0], SESSIONS[-1]), actions=actions
    )


def codes(report) -> set[str]:  # type: ignore[no-untyped-def]
    return {i.code for i in report.issues}


def test_clean_series_is_usable_with_full_score() -> None:
    r = run(clean_series())
    assert r.usable and r.quality_score == 1.0 and not r.issues
    assert r.expected_sessions == len(SESSIONS)


@pytest.mark.parametrize(
    ("override", "code"),
    [
        ({"low": Decimal("0")}, "non_positive_price"),
        ({"high": Decimal("90")}, "high_below_low"),
        ({"open": Decimal("150")}, "open_or_close_outside_range"),
        ({"volume": -5}, "negative_volume"),
    ],
)
def test_corrupt_rows_are_rejected_and_block_the_series(
    override: dict[str, object], code: str
) -> None:
    bars = clean_series()
    bars[5] = bars[5].model_copy(update=override)
    r = run(bars)
    assert code in codes(r)
    assert not r.usable and r.quality_score == 0.0
    assert all(b.session != SESSIONS[5] for b in r.accepted)


def test_conflicting_duplicates_are_critical_identical_ones_collapse() -> None:
    bars = clean_series()
    r = run([*bars, bars[3]])
    assert r.usable and "duplicate_collapsed" in codes(r)
    r2 = run([*bars, bars[3].model_copy(update={"close": Decimal("100.5")})])
    assert not r2.usable and "conflicting_duplicate" in codes(r2)


def test_weekend_bar_is_excluded_as_warning() -> None:
    bars = [*clean_series(), bar(date(2026, 9, 26))]  # Saturday
    r = run(bars)
    assert "non_calendar_session_excluded" in codes(r)
    assert r.usable and all(b.session != date(2026, 9, 26) for b in r.accepted)


def test_missing_sessions_warn_then_block() -> None:
    year = CAL.sessions(date(2025, 9, 25), date(2026, 9, 25))
    bars = [bar(d, str(100 + i % 3)) for i, d in enumerate(year)]
    window = (year[0], year[-1])
    r = validate_bars(
        [b for i, b in enumerate(bars) if i != 10], CAL, RULES, now=NOW, window=window
    )
    assert r.usable and r.missing_sessions == [year[10]]
    assert r.quality_score == pytest.approx(1 - 5 / len(year) - 0.01)
    # One missing session in a short 8-week window already exceeds the 2% limit.
    r2 = run([b for i, b in enumerate(clean_series()) if i != 10])
    assert not r2.usable and "excessive_missing_sessions" in codes(r2)


def test_abnormal_move_flagged_unless_explained_by_corporate_action() -> None:
    bars = clean_series()
    bars[20] = bar(SESSIONS[20], "50")
    assert "abnormal_move_unexplained" in codes(run(bars))
    split = CorporateActionIn(
        kind="split", ex_date=SESSIONS[20], numerator=Decimal(2), denominator=Decimal(1)
    )
    moves = [i for i in run(bars, [split]).issues if i.code == "abnormal_move_unexplained"]
    assert all(i.session != SESSIONS[20] for i in moves)


def test_zero_volume_and_stale_prices_warn() -> None:
    bars = [bar(d, "100") for d in SESSIONS]
    bars[3] = bars[3].model_copy(update={"volume": 0})
    c = codes(run(bars))
    assert {"zero_volume", "stale_prices"} <= c


def test_short_history_reports_low_coverage() -> None:
    late = clean_series()[20:]
    r = run(late)
    assert r.usable  # clean bars, but...
    assert r.coverage == pytest.approx(len(late) / len(SESSIONS))
    assert "history_starts_late" in codes(r)
    assert r.quality_score == pytest.approx(r.coverage)  # capped by coverage
    assert run(clean_series()).coverage == 1.0


def test_empty_input_is_critical() -> None:
    r = validate_bars([], CAL, RULES, now=NOW)
    assert not r.usable and "no_data" in codes(r)


@settings(max_examples=100, deadline=None)
@given(
    idx=st.integers(min_value=0, max_value=len(SESSIONS) - 1),
    low=st.decimals(min_value=-10, max_value=200, places=2),
    high=st.decimals(min_value=-10, max_value=200, places=2),
    close=st.decimals(min_value=-10, max_value=200, places=2),
)
def test_no_invalid_bar_is_ever_accepted(
    idx: int, low: Decimal, high: Decimal, close: Decimal
) -> None:
    bars = clean_series()
    bars[idx] = Bar(session=SESSIONS[idx], open=close, high=high, low=low, close=close, volume=1)
    for b in run(bars).accepted:
        assert b.low > 0 and b.low <= b.open <= b.high and b.low <= b.close <= b.high


# ------------------------------------------------------------ adjustments --

SPLIT = CorporateActionIn(
    kind="split", ex_date=SESSIONS[10], numerator=Decimal(2), denominator=Decimal(1)
)


def test_raw_split_becomes_continuous_after_adjustment() -> None:
    raw = [bar(d, "200" if i < 10 else "100") for i, d in enumerate(SESSIONS)]
    raw[9] = raw[9].model_copy(update={"volume": 1000})
    adj = raw_to_split_adjusted(raw, [SPLIT])
    assert adj[9].close == Decimal("100") and adj[10].close == Decimal("100")
    assert adj[9].volume == 2000  # share counts restated
    assert adj[-1] == raw[-1]  # latest prices untouched


def test_total_return_dividend_factor() -> None:
    sa = [bar(d, "100") for d in SESSIONS[:5]]
    div = CorporateActionIn(kind="dividend", ex_date=SESSIONS[3], amount=Decimal("2"))
    tr = split_adjusted_to_total_return(sa, [div])
    assert tr[2].close == Decimal("98.0000")  # 100 * (1 - 2/100)
    assert tr[3].close == Decimal("100") and tr[4].close == Decimal("100")


def test_dividend_not_smaller_than_price_is_rejected() -> None:
    sa = [bar(d, "10") for d in SESSIONS[:5]]
    div = CorporateActionIn(kind="dividend", ex_date=SESSIONS[3], amount=Decimal("10"))
    with pytest.raises(AdjustmentError):
        split_adjusted_to_total_return(sa, [div])


@pytest.mark.parametrize(
    ("src", "dst"),
    [
        (PriceBasis.SPLIT_ADJUSTED, PriceBasis.RAW),
        (PriceBasis.TOTAL_RETURN, PriceBasis.RAW),
        (PriceBasis.TOTAL_RETURN, PriceBasis.SPLIT_ADJUSTED),
    ],
)
def test_irreversible_conversions_refused(src: PriceBasis, dst: PriceBasis) -> None:
    with pytest.raises(AdjustmentError, match="cannot derive"):
        convert([bar(SESSIONS[0])], src, dst, [])


def test_raw_to_total_return_equals_two_step_path() -> None:
    raw = [bar(d, str(200 - i) if i < 10 else str(100 - i)) for i, d in enumerate(SESSIONS[:20])]
    raw_div = CorporateActionIn(kind="dividend", ex_date=SESSIONS[5], amount=Decimal("4"))
    direct = convert(raw, PriceBasis.RAW, PriceBasis.TOTAL_RETURN, [SPLIT, raw_div])
    sa = raw_to_split_adjusted(raw, [SPLIT])
    sa_div = raw_div.model_copy(update={"amount": Decimal("2")})  # restated for the 2:1 split
    two_step = split_adjusted_to_total_return(sa, [sa_div])
    assert direct == two_step


@settings(max_examples=50, deadline=None)
@given(
    amounts=st.lists(st.decimals(min_value="0.01", max_value="5", places=2), min_size=1, max_size=4)
)
def test_total_return_never_raises_past_prices(amounts: list[Decimal]) -> None:
    sa = [bar(d, "100") for d in SESSIONS[:15]]
    divs = [
        CorporateActionIn(kind="dividend", ex_date=SESSIONS[2 + 3 * i], amount=a)
        for i, a in enumerate(amounts)
    ]
    tr = split_adjusted_to_total_return(sa, divs)
    for before, after in zip(sa, tr, strict=True):
        assert after.close <= before.close
    assert tr[-1].close == sa[-1].close
