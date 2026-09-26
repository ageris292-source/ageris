"""Orchestrator (spec §15): run every agent at one point in time, synthesise
bull and bear cases, and store an immutable, hash-stamped report.

All agents receive the SAME as_of and knowledge_at, so the report is a
consistent point-in-time snapshot that can be replayed. One agent failing
never aborts the others; its failure is part of the report.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.agents.base import AgentOutput
from app.agents.fundamental import agent as fundamental
from app.agents.macro import agent as macro
from app.agents.news import agent as news
from app.agents.portfolio import agent as portfolio
from app.agents.risk import agent as risk
from app.agents.technical import agent as technical
from app.agents.valuation import agent as valuation
from app.core.config_file import get_config
from app.core.settings import get_settings
from app.market_data import service as md
from app.market_data.types import Ticker
from app.models import AgentRun, AnalysisReport, Portfolio
from app.orchestrator import narrative as nv
from app.orchestrator.markdown import render
from app.orchestrator.synthesis import synthesize
from app.services.audit import record_audit

_VAL_KEYS = (
    "price",
    "price_date",
    "scenarios",
    "wacc",
    "beta_used",
    "dcf_reliable",
    "peer_medians",
)


def _hash(report: dict[str, Any]) -> str:
    body = {k: v for k, v in report.items() if k not in ("report_id", "report_hash")}
    return hashlib.sha256(json.dumps(body, sort_keys=True, default=str).encode()).hexdigest()


def run_analysis(
    db: Session,
    ticker: Ticker,
    as_of: datetime,
    user_id: uuid.UUID | None,
    knowledge_at: datetime | None = None,
    portfolio_id: int | None = None,
    weight: float = 0.05,
    narrator: nv.Narrator | None = None,
    use_configured_narrator: bool = True,
) -> dict[str, Any]:
    cfg = get_config()
    stock = md.get_stock(db, ticker)
    k_at = knowledge_at or datetime.now(UTC)
    outputs: dict[str, AgentOutput] = {}
    outputs["technical"] = technical.run_and_record(db, ticker, as_of, user_id, k_at)
    outputs["fundamental"] = fundamental.run_and_record(db, ticker, as_of, user_id, k_at)
    val_out, val_details = valuation.run_and_record(db, ticker, as_of, user_id, k_at)
    outputs["valuation"] = val_out
    outputs["risk"] = risk.run_and_record(db, ticker, as_of, user_id, k_at)
    outputs["news"] = news.run_and_record(db, ticker, as_of, user_id, k_at)
    outputs["macro"] = macro.run_and_record(db, ticker, as_of, user_id, k_at)
    fit: dict[str, Any] | None = None
    if portfolio_id is not None:
        pf = db.get(Portfolio, portfolio_id)
        if pf is None:
            raise LookupError(f"portfolio {portfolio_id} not found")
        pout, pdet = portfolio.run_and_record(db, pf, ticker, weight, as_of, user_id, k_at)
        outputs["portfolio"] = pout
        after = pdet.get("after") or {}
        fit = {
            "portfolio_id": pf.id,
            "portfolio": pf.name,
            "weight": weight,
            "limits_status_after": after.get("limits_status"),
            "checks_after": after.get("checks", []),
        }

    runs: dict[str, str | None] = {}
    for name, out in outputs.items():
        rid = db.scalar(
            select(AgentRun.id)
            .where(
                AgentRun.stock_id == stock.id,
                AgentRun.agent == out.agent,
                AgentRun.as_of == as_of,
                AgentRun.knowledge_at == k_at,
            )
            .order_by(AgentRun.started_at.desc())
            .limit(1)
        )
        runs[name] = str(rid) if rid else None

    regime = macro.current_regime(db, as_of, k_at)
    synthesis = synthesize(outputs, cfg.orchestrator)
    report: dict[str, Any] = {
        "ticker": str(ticker),
        "name": stock.name,
        "as_of": as_of.isoformat(),
        "knowledge_at": k_at.isoformat(),
        "system_mode": get_settings().system_mode.value,
        "config_version": cfg.config_version,
        "config_fingerprint": cfg.fingerprint(),
        "synthesis": synthesis,
        "valuation": {k: val_details.get(k) for k in _VAL_KEYS if k in val_details},
        "risk_metrics": outputs["risk"].metrics,
        "regime": {
            "label": regime.label,
            "trend": regime.trend,
            "volatility": regime.volatility,
            "risk": regime.risk,
            "evidence": regime.evidence,
        },
        "portfolio_fit": fit,
        "agent_outputs": {n: o.model_dump(mode="json") for n, o in outputs.items()},
    }
    chosen = (
        narrator
        if narrator is not None
        else (nv.configured_narrator() if use_configured_narrator else None)
    )
    report["narrative"] = nv.narrate(report, render(report, include_narrative=False), chosen)
    h = _hash(report)
    row = AnalysisReport(
        stock_id=stock.id,
        as_of=as_of,
        knowledge_at=k_at,
        requested_by=user_id,
        stance=synthesis["stance"],
        composite_score=synthesis["composite_score"],
        confidence=synthesis["confidence"],
        agent_run_ids=runs,
        report=report,
        report_hash=h,
        config_fingerprint=cfg.fingerprint(),
    )
    db.add(row)
    db.flush()
    record_audit(
        db,
        action="analysis.report",
        actor_user_id=user_id,
        entity_type="analysis_report",
        entity_id=str(row.id),
        details={"ticker": str(ticker), "stance": synthesis["stance"], "hash": h},
    )
    db.commit()
    return stored(row)


def stored(row: AnalysisReport) -> dict[str, Any]:
    return {
        **row.report,
        "report_id": row.id,
        "report_hash": row.report_hash,
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "agent_run_ids": row.agent_run_ids,
    }


def verify(row: AnalysisReport) -> bool:
    return _hash(row.report) == row.report_hash
