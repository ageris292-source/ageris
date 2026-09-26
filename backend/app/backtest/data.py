"""Point-in-time data for backtests: prices, volumes, benchmark, and the
pooled feature/label dataset."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import datetime, timedelta

import pandas as pd
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.backtest.features import WARMUP_SESSIONS, build_features, forward_labels
from app.core.config_file import get_config
from app.macro import service as ms
from app.market_data import service as md
from app.market_data.adjustments import AdjustmentError
from app.market_data.types import PriceBasis, Ticker
from app.models import Stock
from app.risk.service import ist_date


@dataclass
class StockData:
    ticker: str
    close: pd.Series
    volume: pd.Series
    licensed: bool | None
    source: str | None
    basis: str


def load_stock(
    db: Session, stock: Stock, as_of: datetime, knowledge_at: datetime | None, years: int = 15
) -> StockData:
    end = ist_date(as_of)
    start = end - timedelta(days=365 * years)
    adj = md.get_series(
        db, stock, PriceBasis.SPLIT_ADJUSTED, start, end, as_of=as_of, knowledge_at=knowledge_at
    )
    try:
        tr = md.get_series(
            db, stock, PriceBasis.TOTAL_RETURN, start, end, as_of=as_of, knowledge_at=knowledge_at
        )
        basis = "total_return"
    except AdjustmentError:
        tr, basis = adj, "split_adjusted"
    idx = pd.to_datetime([b.bar.session for b in tr.bars])
    close = pd.Series([float(b.bar.close) for b in tr.bars], index=idx, dtype=float)
    vidx = pd.to_datetime([b.bar.session for b in adj.bars])
    volume = pd.Series([float(b.bar.volume) for b in adj.bars], index=vidx, dtype=float)
    return StockData(str(md.ticker_of(stock)), close, volume, adj.licensed, adj.source, basis)


def load_benchmark(db: Session, as_of: datetime, knowledge_at: datetime | None) -> pd.Series:
    obs = ms.series_as_of(db, get_config().macro.benchmark, as_of, knowledge_at)
    return pd.Series([v for _, v in obs], index=pd.to_datetime([d for d, _ in obs]), dtype=float)


def universe(db: Session, tickers: list[str] | None) -> list[Stock]:
    """Active stocks, one listing per company: when a symbol is listed on both
    NSE and BSE only the NSE listing is used (no double counting)."""
    if tickers:
        stocks = [md.get_stock(db, Ticker.parse(t)) for t in tickers]
    else:
        stocks = list(db.scalars(select(Stock).where(Stock.is_active)).all())
    best: dict[str, Stock] = {}
    for s in sorted(stocks, key=lambda x: (x.symbol, x.exchange != "NSE")):
        best.setdefault(s.symbol, s)
    return sorted(best.values(), key=lambda x: x.symbol)


def data_hash(stocks: list[StockData], bench: pd.Series) -> str:
    h = hashlib.sha256()
    for s in sorted(stocks, key=lambda x: x.ticker):
        h.update(f"{s.ticker}|{s.basis}|{s.source}".encode())
        h.update(pd.util.hash_pandas_object(s.close, index=True).to_numpy().tobytes())
        h.update(pd.util.hash_pandas_object(s.volume, index=True).to_numpy().tobytes())
    h.update(pd.util.hash_pandas_object(bench, index=True).to_numpy().tobytes())
    return h.hexdigest()


def build_dataset(
    stocks: list[StockData], bench: pd.Series, horizon: int, round_trip_cost: float
) -> pd.DataFrame:
    frames = []
    for s in stocks:
        if len(s.close) <= WARMUP_SESSIONS + horizon:
            continue
        f = build_features(s.close, s.volume, bench)
        lab = forward_labels(s.close, bench, horizon, round_trip_cost)
        pos = lab["label_end_pos"].to_numpy()
        dates = s.close.index
        lab["label_end_date"] = [dates[p] if p < len(dates) else pd.NaT for p in pos]
        df = pd.concat([f, lab.drop(columns=["label_end_pos"])], axis=1)
        df["ticker"] = s.ticker
        df["date"] = df.index
        frames.append(df.iloc[WARMUP_SESSIONS:])
    if not frames:
        return pd.DataFrame()
    return pd.concat(frames, ignore_index=True)
