"""News Agent (spec §10). Every conclusion references its source headline.

Score = 50 + 50 * weighted mean of FinBERT sentiment (positive - negative),
weights = event importance x recency decay (half-life from config).
Items without sentiment are excluded, never scored as neutral.
"""

from __future__ import annotations

import hashlib
import logging
import math
import time
import uuid
from collections import defaultdict
from datetime import UTC, datetime, timedelta

from sqlalchemy.orm import Session

from app.agents.base import AgentInput, AgentOutput, AgentStatus, Evidence, Signal
from app.agents.common import new_input, not_ok, record_run
from app.core.config_file import get_config
from app.market_data import service as md
from app.market_data.types import Ticker
from app.models import NewsItem, Stock
from app.news import service as ns

log = logging.getLogger(__name__)

AGENT = "news"
AGENT_VERSION = "news-agent-1.0.0"
SCORE_BASIS = (
    "Importance- and recency-weighted FinBERT headline sentiment, 0-100; 50 = neutral. "
    "Headlines only; descriptive, not a probability."
)
OPPOSED = {("earnings_beat", "earnings_miss"), ("earnings_miss", "earnings_beat")}


def _weight(item: NewsItem, as_of: datetime, half_life: float) -> float:
    assert item.published_at is not None
    age_days = max(0.0, (as_of - item.published_at).total_seconds() / 86400)
    return item.importance * math.pow(0.5, age_days / half_life)


def contradictions(items: list[NewsItem], window_days: int) -> list[str]:
    """Same event type with opposite sentiment, or opposed event types
    (beat vs miss), within the window."""
    out: list[str] = []
    by_type: dict[str, list[NewsItem]] = defaultdict(list)
    for it in items:
        if it.sentiment_label in ("positive", "negative") and it.event_type != "other":
            by_type[it.event_type].append(it)
    win = timedelta(days=window_days)
    for event, group in by_type.items():
        pos = [i for i in group if i.sentiment_label == "positive"]
        neg = [i for i in group if i.sentiment_label == "negative"]
        for a in pos:
            b = next(
                (
                    n
                    for n in neg
                    if abs((a.published_at or a.retrieved_at) - (n.published_at or n.retrieved_at))
                    <= win
                ),
                None,
            )
            if b is not None and event not in ("sector", "rating_change"):
                out.append(
                    f"Conflicting {event.replace('_', ' ')} coverage: "
                    f"“{a.title[:80]}” ({a.publisher}) vs “{b.title[:80]}” ({b.publisher})"
                )
                break
    beats, misses = by_type.get("earnings_beat", []), by_type.get("earnings_miss", [])
    if beats and misses:
        out.append(
            f"Opposite earnings reports: “{beats[0].title[:80]}” vs “{misses[0].title[:80]}”"
        )
    return out


def run_news(db: Session, stock: Stock, inp: AgentInput) -> AgentOutput:
    cfg = get_config()
    rules = cfg.news
    items = ns.news_as_of(db, stock, inp.as_of, inp.knowledge_at, rules.lookback_days)
    scored = [i for i in items if i.sentiment_score is not None]
    unscored = len(items) - len(scored)
    if len(scored) < rules.min_items_for_score:
        why = [
            f"Need {rules.min_items_for_score} dated, de-duplicated headlines with sentiment in "
            f"the last {rules.lookback_days} days; have {len(scored)}"
        ]
        if unscored:
            why.append(f"{unscored} headline(s) have no sentiment (model unavailable at ingestion)")
        return not_ok(
            AGENT, AGENT_VERSION, inp, AgentStatus.INSUFFICIENT_DATA, why, cfg, SCORE_BASIS
        )

    weights = [_weight(i, inp.as_of, rules.recency_half_life_days) for i in scored]
    wsum = sum(weights)
    net = sum(w * (i.sentiment_score or 0) for w, i in zip(weights, scored, strict=True)) / wsum
    score = round(50 + 50 * net, 2)

    ranked = sorted(zip(weights, scored, strict=True), key=lambda t: -t[0])
    signals: list[Signal] = []
    evidence: list[Evidence] = []
    for w, it in ranked[:8]:
        direction = {"positive": "bullish", "negative": "bearish"}.get(
            it.sentiment_label or "", "neutral"
        )
        assert it.published_at is not None
        signals.append(
            Signal(
                name=f"news_{it.id}",
                category=it.event_type,
                direction=direction,
                strength=min(1.0, abs(it.sentiment_score or 0) * w / max(weights)),
                detail=f"{it.title} — {it.publisher or 'unknown'} "
                f"({it.published_at.date()}, {it.event_type.replace('_', ' ')})",
                values={"url": it.url, "sentiment": it.sentiment_score, "weight": round(w, 4)},
            )
        )
        evidence.append(
            Evidence(ref=f"news:{it.id}:{it.url}", description=f"{it.publisher}: {it.title}")
        )

    conflicts = contradictions(scored, rules.contradiction_window_days)
    risks = [
        f"Negative {i.event_type.replace('_', ' ')} news: {i.title[:100]}"
        for _, i in ranked
        if i.sentiment_label == "negative"
        and i.event_type in ("regulatory", "lawsuit", "earnings_miss", "management_change")
    ][:4]
    directional = [s for s in signals if s.direction != "neutral"]
    tot = sum(s.strength for s in directional)
    agreement = (
        abs(sum((1 if s.direction == "bullish" else -1) * s.strength for s in directional)) / tot
        if tot
        else 0.0
    )

    warnings = [
        "Unlicensed headline source (Google News RSS): research use only",
        "Sentiment from headlines only; article bodies are not read",
    ]
    if unscored:
        warnings.append(f"{unscored} headline(s) excluded: no sentiment available")
    if conflicts:
        warnings.append(f"{len(conflicts)} contradictory news cluster(s) detected")
    h = hashlib.sha256("|".join(f"{i.id}:{i.sentiment_score}" for i in scored).encode()).hexdigest()
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
        confidence=round(agreement * min(1.0, len(scored) / 10) * (0.5 if conflicts else 1.0), 4),
        confidence_basis="heuristic_uncalibrated",
        signals=signals,
        evidence=evidence,
        risks=risks + conflicts,
        invalidation_conditions=[
            "Material news of the opposite tone from an official company disclosure",
        ]
        if score != 50
        else ["No directional thesis: nothing to invalidate"],
        metrics={
            "items_scored": float(len(scored)),
            "weighted_sentiment": net,
            "negative_share": sum(1 for i in scored if i.sentiment_label == "negative")
            / len(scored),
            "contradictions": float(len(conflicts)),
        },
        data_quality=0.8,
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
        out = run_news(db, stock, inp)
    except Exception as exc:
        log.exception("news agent failed for %s", ticker)
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
