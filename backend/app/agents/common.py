"""Shared agent helpers: composite scoring and run recording."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Literal

from sqlalchemy.orm import Session

from app.agents.base import AgentInput, AgentOutput, AgentStatus, Evidence, Signal
from app.core.config_file import AegisConfig
from app.models import AgentOutputRecord, AgentRun, Stock


@dataclass(frozen=True)
class Composite:
    score: float  # 0..100, 50 = no tilt
    agreement: float  # |net| / total directional strength
    breadth: float  # weighted share of categories with a directional view


def composite(signals: list[Signal], weights: dict[str, float]) -> Composite:
    """Same documented formula for every agent:
    category net = mean(direction x strength); composite = weighted mean of
    category nets over categories present; score = 50 + 50 x composite."""
    nets: dict[str, float] = {}
    for cat in weights:
        contribs = [
            (1 if s.direction == "bullish" else -1 if s.direction == "bearish" else 0) * s.strength
            for s in signals
            if s.category == cat
        ]
        if contribs:
            nets[cat] = sum(contribs) / len(contribs)
    wsum = sum(weights[c] for c in nets)
    comp = sum(weights[c] * nets[c] for c in nets) / wsum if wsum else 0.0
    directional = [s for s in signals if s.direction != "neutral"]
    total = sum(s.strength for s in directional)
    net = sum((1 if s.direction == "bullish" else -1) * s.strength for s in directional)
    covered = {s.category for s in directional}
    return Composite(
        score=round(50 + 50 * comp, 2),
        agreement=abs(net) / total if total else 0.0,
        breadth=sum(w for c, w in weights.items() if c in covered),
    )


def not_ok(
    agent: str,
    version: str,
    inp: AgentInput,
    status: AgentStatus,
    warnings: list[str],
    cfg: AegisConfig,
    score_basis: str,
    *,
    quality: float = 0.0,
    snapshot: str | None = None,
    evidence: list[Evidence] | None = None,
) -> AgentOutput:
    return AgentOutput(
        agent=agent,
        agent_version=version,
        ticker=inp.ticker,
        as_of=inp.as_of,
        knowledge_at=inp.knowledge_at,
        generated_at=datetime.now(UTC),
        status=status,
        score=None,
        score_basis=score_basis,
        confidence=0.0,
        confidence_basis="none",
        data_quality=quality,
        data_snapshot_id=snapshot,
        config_fingerprint=cfg.fingerprint(),
        warnings=warnings,
        evidence=evidence or [],
    )


def record_run(
    db: Session,
    stock: Stock,
    out: AgentOutput,
    knowledge_at: datetime,
    user_id: uuid.UUID | None,
    duration_ms: int,
    error: str | None = None,
) -> AgentRun:
    run = AgentRun(
        agent=out.agent,
        agent_version=out.agent_version,
        stock_id=stock.id,
        as_of=out.as_of,
        knowledge_at=knowledge_at,
        status=out.status.value,
        data_snapshot_id=out.data_snapshot_id,
        config_fingerprint=out.config_fingerprint,
        requested_by=user_id,
        duration_ms=duration_ms,
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
    return run


def new_input(ticker: str, as_of: datetime, knowledge_at: datetime | None) -> AgentInput:
    return AgentInput(ticker=ticker, as_of=as_of, knowledge_at=knowledge_at or datetime.now(UTC))


def sig(
    name: str,
    category: str,
    value: float,
    strength: float,
    detail: str,
    **values: float | str | None,
) -> Signal:
    """Signal whose direction is the sign of `value` (0 => neutral)."""
    direction: Literal["bullish", "bearish", "neutral"] = (
        "bullish" if value > 0 else "bearish" if value < 0 else "neutral"
    )
    return Signal(
        name=name,
        category=category,
        direction=direction,
        strength=max(0.0, min(1.0, strength)),
        detail=detail,
        values=values,
    )
