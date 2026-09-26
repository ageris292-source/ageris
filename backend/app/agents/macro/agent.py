"""Macro Agent (spec §11) + market regime (spec §42).

Each driver's recent change is mapped to the stock through its sector's
configured sensitivity (+1 benefits from a rise, -1 is hurt by it). The same
macro move therefore affects sectors differently, as §11 requires. Stocks
with no configured sector get market-wide drivers only, with a warning.
"""

from __future__ import annotations

import hashlib
import logging
import time
import uuid
from datetime import UTC, date, datetime, timedelta

from sqlalchemy.orm import Session

from app.agents.base import AgentInput, AgentOutput, AgentStatus, Evidence, Signal
from app.agents.common import new_input, not_ok, record_run, sig
from app.analysis.regime import Regime, detect
from app.analysis.stats import change_over
from app.core.config_file import get_config
from app.macro import service as ms
from app.market_data import service as md
from app.market_data.types import Ticker
from app.models import Stock

log = logging.getLogger(__name__)

AGENT = "macro"
AGENT_VERSION = "macro-agent-1.0.0"
SCORE_BASIS = (
    "Sector-sensitivity-weighted recent macro moves, 0-100; 50 = neutral. Descriptive, "
    "not a probability."
)
LABELS = {
    "usd_inr": "USD/INR",
    "brent": "Brent crude",
    "nifty50": "NIFTY 50",
    "nifty_it": "NIFTY IT",
    "nifty_bank": "NIFTY Bank",
    "india_vix": "India VIX",
    "repo_rate": "RBI repo rate",
    "gdp_growth": "GDP growth",
    "cpi_inflation": "CPI inflation",
}


def sector_of(ticker: str) -> str | None:
    cfg = get_config()
    return next(
        (g for g, members in cfg.fundamentals.peer_groups.items() if ticker in members), None
    )


def current_regime(
    db: Session, as_of: datetime | None, knowledge_at: datetime | None = None
) -> Regime:
    cfg = get_config().macro
    start = (as_of or datetime.now(UTC)).date() - timedelta(days=420)
    nifty = [v for _, v in ms.series_as_of(db, cfg.benchmark, as_of, knowledge_at, start)]
    vix = [v for _, v in ms.series_as_of(db, "india_vix", as_of, knowledge_at, start)]
    return detect(
        nifty, vix or None, vix_high=cfg.vix_high, vix_low=cfg.vix_low, band=cfg.trend_band
    )


def _change(
    db: Session, series: str, inp: AgentInput, window: int
) -> tuple[float | None, date | None]:
    """Recent change of a series: % change over `window` sessions for daily
    series; latest minus previous value for annual/event series."""
    start = inp.as_of.date() - timedelta(days=max(400, window * 3))
    obs = ms.series_as_of(
        db,
        series,
        inp.as_of,
        inp.knowledge_at,
        start if series not in ("gdp_growth", "cpi_inflation", "repo_rate") else None,
    )
    if len(obs) < 2:
        return None, obs[-1][0] if obs else None
    if series in ("gdp_growth", "cpi_inflation", "repo_rate"):
        return obs[-1][1] - obs[-2][1], obs[-1][0]
    return change_over(obs, window), obs[-1][0]


def run_macro(db: Session, stock: Stock, inp: AgentInput) -> AgentOutput:
    cfg = get_config()
    rules = cfg.macro
    ticker = str(md.ticker_of(stock))
    sector = sector_of(ticker)
    sens = rules.sector_sensitivities.get(sector or "", rules.default_sensitivities)
    regime = current_regime(db, inp.as_of, inp.knowledge_at)

    signals: list[Signal] = []
    evidence: list[Evidence] = []
    risks: list[str] = []
    metrics: dict[str, float | None] = {}
    missing: list[str] = []
    for series, weight in sens.items():
        chg, last = _change(db, series, inp, rules.change_window_sessions)
        metrics[f"{series}_change"] = chg
        if chg is None:
            missing.append(LABELS.get(series, series))
            continue
        # Scale: 10% for market series, 1 percentage point for rates/growth.
        scale = 0.01 if series in ("gdp_growth", "cpi_inflation", "repo_rate") else 0.10
        effect = weight * chg
        what = f"{chg * 100:+.2f} pts" if scale == 0.01 else f"{chg:+.1%}"
        signals.append(
            sig(
                f"macro_{series}",
                "macro",
                effect,
                min(1.0, abs(chg) / scale) * abs(weight),
                f"{LABELS.get(series, series)} {what} (to {last}); sector sensitivity {weight:+g} "
                f"=> {'tailwind' if effect > 0 else 'headwind' if effect < 0 else 'neutral'}",
                change=chg,
            )
        )
        evidence.append(
            Evidence(ref=f"macro:{series}:{last}", description=f"{series} as of {last}")
        )

    # Market-wide context (not sector specific).
    cpi = ms.series_as_of(db, "cpi_inflation", inp.as_of, inp.knowledge_at)
    if cpi:
        metrics["cpi_inflation"] = cpi[-1][1]
        gap = cpi[-1][1] - rules.rbi_inflation_target
        if gap > 0.02:
            risks.append(
                f"Inflation {cpi[-1][1]:.1%} well above the RBI 4% target (rate-hike risk)"
            )
    metrics.update({f"regime_{k}": v for k, v in regime.evidence.items()})
    if regime.risk == "risk_off":
        risks.append(f"Market regime {regime.label}: risk-off")
    signals.append(
        sig(
            "market_regime",
            "regime",
            {"risk_on": 1, "risk_off": -1}.get(regime.risk, 0),
            0.6,
            f"Market regime {regime.label} (trend {regime.trend}, volatility {regime.volatility})",
        )
    )

    directional = [s for s in signals if s.direction != "neutral"]
    if not [s for s in signals if s.name != "market_regime"]:
        return not_ok(
            AGENT,
            AGENT_VERSION,
            inp,
            AgentStatus.INSUFFICIENT_DATA,
            ["No macro series available as of this date: " + ", ".join(missing)],
            cfg,
            SCORE_BASIS,
        )
    net = sum((1 if s.direction == "bullish" else -1) * s.strength for s in directional)
    # Same convention as the other agents: mean signed contribution per signal.
    score = round(50 + 50 * net / len(signals), 2)
    warnings = ["Market series from Yahoo are unlicensed: research use only"]
    if sector is None:
        warnings.append("No sector configured for this stock: market-wide drivers only")
    if missing:
        warnings.append("Unavailable drivers: " + ", ".join(missing))
    if not regime.known:
        warnings.append("Market regime UNKNOWN (insufficient NIFTY/VIX history)")
    agreement = abs(net) / sum(s.strength for s in directional) if directional else 0.0
    h = hashlib.sha256(repr(sorted(metrics.items())).encode()).hexdigest()
    return AgentOutput(
        agent=AGENT,
        agent_version=AGENT_VERSION,
        ticker=inp.ticker,
        as_of=inp.as_of,
        knowledge_at=inp.knowledge_at,
        generated_at=datetime.now(UTC),
        status=AgentStatus.OK,
        score=score,
        score_basis=SCORE_BASIS,
        confidence=round(
            agreement * (0.5 if sector is None else 1.0) * (1 - len(missing) / max(1, len(sens))), 4
        ),
        confidence_basis="heuristic_uncalibrated",
        signals=signals,
        evidence=evidence,
        risks=risks,
        invalidation_conditions=["Reversal of the dominant macro driver over the next quarter"]
        if score != 50
        else ["No directional thesis: nothing to invalidate"],
        metrics={**metrics, "sector_known": 1.0 if sector else 0.0},
        data_quality=1.0 - len(missing) / max(1, len(sens)),
        data_snapshot_id=h,
        config_fingerprint=cfg.fingerprint(),
        warnings=warnings,
    )


def run_and_record(
    db: Session,
    ticker: Ticker,
    as_of: datetime,
    user_id: uuid.UUID | None,
    knowledge_at: datetime | None = None,
) -> AgentOutput:
    stock = md.get_stock(db, ticker)
    inp = new_input(str(ticker), as_of, knowledge_at)
    t0, error = time.perf_counter(), None
    try:
        out = run_macro(db, stock, inp)
    except Exception as exc:
        log.exception("macro agent failed for %s", ticker)
        db.rollback()
        error = f"{exc.__class__.__name__}: {exc}"[:2000]
        out = not_ok(
            AGENT,
            AGENT_VERSION,
            inp,
            AgentStatus.FAILED,
            [f"Agent error: {exc.__class__.__name__}"],
            get_config(),
            SCORE_BASIS,
        )
    record_run(
        db, stock, out, inp.knowledge_at, user_id, int((time.perf_counter() - t0) * 1000), error
    )
    db.commit()
    return out
