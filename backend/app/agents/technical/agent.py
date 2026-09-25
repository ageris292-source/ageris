"""Technical Analysis Agent (spec §8).

Flow: point-in-time prices from MarketDataService -> data-quality gate ->
history gate -> deterministic analysis -> typed AgentOutput -> persisted run,
output and feature-store rows. Any failure produces a non-OK output; nothing
is guessed.
"""

from __future__ import annotations

import hashlib
import logging
import time
import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy.orm import Session

from app.agents.base import AgentInput, AgentOutput, AgentStatus, Evidence
from app.agents.technical.analysis import analyze
from app.analysis.indicators import CALCULATION_VERSION
from app.core.config_file import AegisConfig, get_config
from app.market_data import service as md
from app.market_data.types import PriceBasis, Ticker
from app.models import AgentOutputRecord, AgentRun, Stock, TechnicalIndicator

log = logging.getLogger(__name__)

AGENT = "technical"
AGENT_VERSION = f"technical-agent-1.0.0/{CALCULATION_VERSION}"
IST_OFFSET = timedelta(hours=5, minutes=30)
BASIS = PriceBasis.SPLIT_ADJUSTED  # indicators need continuity across splits/bonuses
SCORE_BASIS = (
    "Deterministic composite of technical signals, 0-100; 50 = no tilt. "
    "Descriptive only: not a probability of profit."
)


def snapshot_id(series: md.PriceSeries) -> str:
    """Content hash of the exact input bars (incl. data versions)."""
    h = hashlib.sha256()
    h.update(f"{series.ticker}|{series.basis}|{series.source}".encode())
    for sb in series.bars:
        b = sb.bar
        h.update(
            f"|{b.session}:{b.open}:{b.high}:{b.low}:{b.close}:{b.volume}:{sb.data_version}".encode()
        )
    return h.hexdigest()


def _empty(
    inp: AgentInput,
    status: AgentStatus,
    warnings: list[str],
    cfg: AegisConfig,
    *,
    quality: float = 0.0,
    snap: str | None = None,
    evidence: list[Evidence] | None = None,
) -> AgentOutput:
    return AgentOutput(
        agent=AGENT,
        agent_version=AGENT_VERSION,
        ticker=inp.ticker,
        as_of=inp.as_of,
        knowledge_at=inp.knowledge_at,
        generated_at=datetime.now(UTC),
        status=status,
        score=None,
        score_basis=SCORE_BASIS,
        confidence=0.0,
        confidence_basis="none",
        data_quality=quality,
        data_snapshot_id=snap,
        config_fingerprint=cfg.fingerprint(),
        warnings=warnings,
        evidence=evidence or [],
    )


def run_technical(db: Session, stock: Stock, inp: AgentInput) -> tuple[AgentOutput, md.PriceSeries]:
    cfg = get_config()
    rules = cfg.technical
    as_of_date = (inp.as_of.astimezone(UTC) + IST_OFFSET).date()  # IST session date
    # Calendar days needed to comfortably cover min_history sessions (~250/yr).
    lookback_days = int(rules.min_history_sessions * 1.6) + 30
    start = as_of_date - timedelta(days=lookback_days)
    series = md.get_series(
        db, stock, BASIS, start, as_of_date, as_of=inp.as_of, knowledge_at=inp.knowledge_at
    )
    if not series.bars:
        return _empty(
            inp,
            AgentStatus.INSUFFICIENT_DATA,
            [f"No price data available as of {inp.as_of.isoformat()}"],
            cfg,
        ), series

    snap = snapshot_id(series)
    first, last = series.bars[0].bar.session, series.bars[-1].bar.session
    evidence = [
        Evidence(
            ref=f"prices:{series.ticker}:{series.basis.value}:{series.source}:{first}..{last}"
            f":snapshot={snap[:16]}",
            description=f"{len(series.bars)} daily bars ({series.basis.value}"
            f"{', derived' if series.derived else ''}) from {series.source}",
        )
    ]

    report = md.validate_stored(series, inp.as_of, (first, as_of_date))
    if not report.usable:
        crit = [f"{i.code}{f' ({i.session})' if i.session else ''}" for i in report.critical][:5]
        return _empty(
            inp,
            AgentStatus.DATA_UNUSABLE,
            ["Stored prices failed validation: " + ", ".join(crit)],
            cfg,
            snap=snap,
            evidence=evidence,
        ), series

    if len(series.bars) < rules.min_history_sessions:
        return _empty(
            inp,
            AgentStatus.INSUFFICIENT_DATA,
            [f"Need {rules.min_history_sessions} sessions of history, have {len(series.bars)}"],
            cfg,
            quality=report.quality_score,
            snap=snap,
            evidence=evidence,
        ), series

    warnings: list[str] = []
    fresh = md.freshness_for_date(last, inp.as_of, cfg)
    if fresh.status != "PASS":
        warnings.append(f"Data freshness {fresh.status}: {fresh.reason}")
    if series.licensed is False:
        warnings.append("Unlicensed price source: research use only")
    if report.quality_score < cfg.trade_gates.minimum_data_quality_score:
        warnings.append(
            f"Data quality {report.quality_score:.2f} below the trading minimum "
            f"{cfg.trade_gates.minimum_data_quality_score:.2f}"
        )

    result = analyze([sb.bar for sb in series.bars], rules, cfg.liquidity)

    # Confidence is an UNCALIBRATED heuristic, never a probability (spec §27,
    # §43): signal agreement x category breadth x data quality, halved when the
    # data is not fresh. Empirical calibration arrives with backtesting.
    confidence = result.agreement * result.breadth * report.quality_score
    if fresh.status != "PASS":
        confidence *= 0.5

    for lv in result.supports[:1]:
        evidence.append(
            Evidence(
                ref=f"level:support:{lv.price:.2f}",
                description=f"Support ₹{lv.price:,.2f} ({lv.touches} touch(es))",
            )
        )
    for lv in result.resistances[:1]:
        evidence.append(
            Evidence(
                ref=f"level:resistance:{lv.price:.2f}",
                description=f"Resistance ₹{lv.price:,.2f} ({lv.touches} touch(es))",
            )
        )

    out = AgentOutput(
        agent=AGENT,
        agent_version=AGENT_VERSION,
        ticker=inp.ticker,
        as_of=inp.as_of,
        knowledge_at=inp.knowledge_at,
        generated_at=datetime.now(UTC),
        status=AgentStatus.OK,
        score=result.score,
        score_basis=SCORE_BASIS,
        confidence=round(confidence, 4),
        confidence_basis="heuristic_uncalibrated",
        signals=result.signals,
        evidence=evidence,
        risks=result.risks,
        invalidation_conditions=result.invalidation_conditions,
        metrics={
            **result.metrics,
            "signal_agreement": result.agreement,
            "category_breadth": result.breadth,
        },
        data_quality=report.quality_score,
        data_snapshot_id=snap,
        config_fingerprint=cfg.fingerprint(),
        warnings=warnings + result.warnings,
    )
    return out, series


def run_and_record(
    db: Session,
    ticker: Ticker,
    as_of: datetime,
    user_id: uuid.UUID | None,
    knowledge_at: datetime | None = None,
) -> AgentOutput:
    """Run and record. knowledge_at defaults to now; pass a recorded run's
    knowledge_at to replay it exactly."""
    stock = md.get_stock(db, ticker)  # raises StockNotFoundError
    inp = AgentInput(
        ticker=str(ticker), as_of=as_of, knowledge_at=knowledge_at or datetime.now(UTC)
    )
    t0 = time.perf_counter()
    error: str | None = None
    try:
        out, series = run_technical(db, stock, inp)
    except Exception as exc:  # fail closed, but record what happened
        log.exception("technical agent failed for %s", ticker)
        db.rollback()
        error = f"{exc.__class__.__name__}: {exc}"[:2000]
        out = _empty(
            inp, AgentStatus.FAILED, [f"Agent error: {exc.__class__.__name__}"], get_config()
        )
        series = None

    run = AgentRun(
        agent=AGENT,
        agent_version=AGENT_VERSION,
        stock_id=stock.id,
        as_of=as_of,
        knowledge_at=inp.knowledge_at,
        status=out.status.value,
        data_snapshot_id=out.data_snapshot_id,
        config_fingerprint=out.config_fingerprint,
        requested_by=user_id,
        duration_ms=int((time.perf_counter() - t0) * 1000),
        error=error,
    )
    db.add(run)
    db.flush()
    db.add(
        AgentOutputRecord(
            run_id=run.id,
            score=out.score,
            confidence=out.confidence,
            output=out.model_dump(mode="json"),
        )
    )
    if out.status is AgentStatus.OK and series is not None and series.bars:
        latest = series.bars[-1]
        for name, value in out.metrics.items():
            existing = (
                db.query(TechnicalIndicator.id)
                .filter_by(
                    stock_id=stock.id,
                    feature_name=name,
                    session_date=latest.bar.session,
                    calculation_version=CALCULATION_VERSION,
                    data_snapshot_id=out.data_snapshot_id,
                )
                .first()
            )
            if existing is None:
                db.add(
                    TechnicalIndicator(
                        stock_id=stock.id,
                        feature_name=name,
                        session_date=latest.bar.session,
                        value=value,
                        source=latest.source,
                        basis=BASIS.value,
                        calculation_version=CALCULATION_VERSION,
                        availability_timestamp=latest.available_at,
                        data_snapshot_id=out.data_snapshot_id or "",
                        agent_run_id=run.id,
                    )
                )
    db.commit()
    return out
