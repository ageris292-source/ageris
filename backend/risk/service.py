"""Point-in-time price histories and single-stock risk metrics (spec §13).

Returns use the total-return basis (dividends reinvested) when it can be
derived, otherwise split-adjusted closes with a warning. Traded value uses
split-adjusted close x volume (invariant to splits).
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from typing import Any

import numpy as np
from sqlalchemy.orm import Session

from app.analysis import risk as rk
from app.core.config_file import AegisConfig, get_config
from app.macro import service as ms
from app.market_data import service as md
from app.market_data.adjustments import AdjustmentError
from app.market_data.types import PriceBasis
from app.market_data.validation import ValidationReport
from app.models import Stock

IST_OFFSET = timedelta(hours=5, minutes=30)


def ist_date(ts: datetime) -> date:
    return (ts.astimezone(UTC) + IST_OFFSET).date()


@dataclass
class History:
    ticker: str
    closes: list[tuple[date, float]]  # return basis (total-return if possible)
    traded: list[tuple[date, float, int]]  # split-adjusted close, volume
    basis: str
    source: str | None
    licensed: bool | None
    report: ValidationReport | None
    snapshot: str
    warnings: list[str] = field(default_factory=list)

    @property
    def last(self) -> tuple[date, float] | None:
        return self.closes[-1] if self.closes else None


def load_history(
    db: Session,
    stock: Stock,
    as_of: datetime,
    knowledge_at: datetime | None,
    sessions: int,
) -> History:
    end = ist_date(as_of)
    start = end - timedelta(days=int(sessions * 1.6) + 30)
    warnings: list[str] = []
    adj = md.get_series(
        db, stock, PriceBasis.SPLIT_ADJUSTED, start, end, as_of=as_of, knowledge_at=knowledge_at
    )
    try:
        tr = md.get_series(
            db, stock, PriceBasis.TOTAL_RETURN, start, end, as_of=as_of, knowledge_at=knowledge_at
        )
        basis = "total_return"
    except AdjustmentError as exc:
        tr = adj
        basis = "split_adjusted"
        warnings.append(f"Total-return series unavailable ({exc}); returns exclude dividends")
    closes = [(b.bar.session, float(b.bar.close)) for b in tr.bars][-(sessions + 1) :]
    traded = [(b.bar.session, float(b.bar.close), int(b.bar.volume)) for b in adj.bars][
        -(sessions + 1) :
    ]
    report = None
    if adj.bars:
        report = md.validate_stored(adj, as_of, (adj.bars[0].bar.session, end))
    h = hashlib.sha256(f"{stock.id}|{basis}|{adj.source}".encode())
    for b in adj.bars:
        h.update(f"{b.bar.session}|{b.bar.close}|{b.bar.volume}|{b.data_version}".encode())
    return History(
        str(md.ticker_of(stock)),
        closes,
        traded,
        basis,
        adj.source,
        adj.licensed,
        report,
        h.hexdigest(),
        warnings,
    )


def benchmark(
    db: Session,
    as_of: datetime,
    knowledge_at: datetime | None,
    sessions: int,
    cfg: AegisConfig | None = None,
) -> list[tuple[date, float]]:
    c = cfg or get_config()
    start = ist_date(as_of) - timedelta(days=int(sessions * 1.6) + 30)
    return ms.series_as_of(db, c.macro.benchmark, as_of, knowledge_at, start)[-(sessions + 1) :]


def stock_metrics(
    h: History, bench: list[tuple[date, float]], cfg: AegisConfig | None = None
) -> dict[str, Any]:
    """All single-stock risk metrics. None where not computable (never 0)."""
    c = cfg or get_config()
    rules = c.risk_analysis
    days = rules.trading_days_per_year
    rf = c.valuation.risk_free_rate
    r = rk.returns([v for _, v in h.closes])
    out: dict[str, Any] = {
        "history_sessions": len(r),
        "volatility_annual": rk.annual_volatility(r, days),
        "volatility_20d_annual": rk.annual_volatility(r[-20:], days) if len(r) >= 20 else None,
        "sharpe": rk.sharpe(r, rf, days),
        "sortino": rk.sortino(r, rf, days),
        "return_period": (h.closes[-1][1] / h.closes[0][1] - 1) if len(h.closes) >= 2 else None,
    }
    dd = rk.max_drawdown(h.closes)
    out.update(
        max_drawdown=dd.max_drawdown if h.closes else None,
        drawdown_peak=dd.peak.isoformat() if dd.peak else None,
        drawdown_trough=dd.trough.isoformat() if dd.trough else None,
        current_drawdown=dd.current if h.closes else None,
    )
    for conf in rules.var_confidence:
        v, cv = rk.var_cvar(r, conf)
        pct = round(conf * 100)
        out[f"var_{pct}_1d"] = v
        out[f"cvar_{pct}_1d"] = cv
    rs, rm, _ = rk.aligned_returns(h.closes, bench)
    out["beta"] = rk.beta_daily(rs, rm)
    out["beta_observations"] = len(rs)
    out["correlation_to_benchmark"] = float(np.corrcoef(rs, rm)[0, 1]) if len(rs) >= 30 else None
    out["adtv"] = rk.average_daily_traded_value(
        [c_ for _, c_, _ in h.traded], [v for _, _, v in h.traded], rules.adv_window_sessions
    )
    return out
