"""Deterministic bull / bear synthesis (spec §15, §16).

Pure function of the agents' structured outputs: no model, no randomness.
The research stance summarises agent scores; it is never a trade decision.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

from app.agents.base import AgentOutput, AgentStatus
from app.core.config_file import OrchestratorRules

Stance = Literal["POSITIVE_TILT", "NEGATIVE_TILT", "NO_CLEAR_TILT", "INSUFFICIENT_DATA"]
STANCE_TEXT = {
    "POSITIVE_TILT": "Evidence tilts positive",
    "NEGATIVE_TILT": "Evidence tilts negative",
    "NO_CLEAR_TILT": "No clear tilt",
    "INSUFFICIENT_DATA": "Insufficient data for a view",
}
NO_TRADE = (
    "This is a research synthesis. Only the deterministic Trade Risk Engine "
    "can approve a trade proposal, and it requires every gate to PASS."
)


@dataclass(frozen=True)
class Point:
    agent: str
    signal: str
    detail: str
    weight: float  # signal strength x agent weight
    evidence: str | None

    def as_dict(self) -> dict[str, Any]:
        return {
            "agent": self.agent,
            "signal": self.signal,
            "detail": self.detail,
            "weight": round(self.weight, 4),
            "evidence": self.evidence,
        }


def synthesize(outputs: dict[str, AgentOutput], rules: OrchestratorRules) -> dict[str, Any]:
    ok = {a: o for a, o in outputs.items() if o.status is AgentStatus.OK and o.score is not None}
    w = {a: rules.agent_weights.get(a, 0.0) for a in outputs}

    table = [
        {
            "agent": a,
            "status": o.status.value,
            "score": o.score,
            "confidence": o.confidence,
            "data_quality": o.data_quality,
            "weight": w[a],
            "version": o.agent_version,
            "snapshot": o.data_snapshot_id,
            "warnings": o.warnings,
        }
        for a, o in outputs.items()
    ]

    wsum = sum(w[a] for a in ok)
    composite = round(sum(w[a] * (ok[a].score or 0) for a in ok) / wsum, 2) if wsum else None
    total_w = sum(w.values())
    coverage = wsum / total_w if total_w else 0.0

    missing_required = [a for a in rules.required_agents if a not in ok]
    reasons: list[str] = []
    if missing_required:
        reasons.append("Required agent(s) without a usable result: " + ", ".join(missing_required))
    if len(ok) < rules.min_agents_ok:
        reasons.append(
            f"Only {len(ok)} agent(s) produced a usable result; need {rules.min_agents_ok}"
        )

    stance: Stance
    if reasons or composite is None:
        stance = "INSUFFICIENT_DATA"
    elif composite >= 50 + rules.stance_band:
        stance = "POSITIVE_TILT"
    elif composite <= 50 - rules.stance_band:
        stance = "NEGATIVE_TILT"
    else:
        stance = "NO_CLEAR_TILT"

    bull: list[Point] = []
    bear: list[Point] = []
    for a, o in ok.items():
        ref = o.evidence[0].ref if o.evidence else None
        for s in o.signals:
            if s.direction == "neutral" or s.strength == 0:
                continue
            p = Point(a, s.name, s.detail, s.strength * w[a], ref)
            (bull if s.direction == "bullish" else bear).append(p)
    bull.sort(key=lambda p: (-p.weight, p.agent, p.signal))
    bear.sort(key=lambda p: (-p.weight, p.agent, p.signal))

    half = rules.conflict_gap / 2
    conflicts: list[dict[str, Any]] = []
    names = sorted(ok)
    for i, a in enumerate(names):
        for b in names[i + 1 :]:
            sa, sb = ok[a].score or 50.0, ok[b].score or 50.0
            (hi, s_hi), (lo, s_lo) = sorted(((a, sa), (b, sb)), key=lambda t: -t[1])
            if s_hi >= 50 + half and s_lo <= 50 - half:
                conflicts.append(
                    {
                        "agents": [hi, lo],
                        "scores": [s_hi, s_lo],
                        "detail": f"{hi} ({s_hi:.0f}) disagrees with {lo} ({s_lo:.0f})",
                    }
                )

    base_conf = sum(w[a] * ok[a].confidence for a in ok) / wsum if wsum else 0.0
    confidence = round(
        base_conf * coverage * (1 - rules.conflict_confidence_penalty) ** len(conflicts), 4
    )

    risks: list[dict[str, str]] = []
    seen: set[str] = set()
    for a, o in outputs.items():
        for r in o.risks:
            if r not in seen:
                seen.add(r)
                risks.append({"agent": a, "risk": r})
    invalidation = [
        {"agent": a, "condition": c}
        for a, o in ok.items()
        for c in o.invalidation_conditions
        if not c.startswith("No directional thesis")
    ]
    data_warnings = [
        {"agent": a, "warning": f"{o.status.value}: " + "; ".join(o.warnings or ["no detail"])}
        for a, o in outputs.items()
        if a not in ok
    ]
    for a, o in ok.items():
        for wmsg in o.warnings:
            if "unlicensed" in wmsg.lower() or "research use only" in wmsg.lower():
                data_warnings.append({"agent": a, "warning": wmsg})

    return {
        "stance": stance,
        "stance_text": STANCE_TEXT[stance],
        "composite_score": composite,
        "composite_basis": (
            "Weighted mean of usable agent scores (weights renormalised over agents with a "
            "result); 50 = no tilt. Descriptive, not a probability or expected return."
        ),
        "confidence": confidence,
        "confidence_basis": (
            "heuristic_uncalibrated (agent confidence x coverage x conflict penalty)"
        ),
        "coverage": round(coverage, 4),
        "insufficient_reasons": reasons,
        "agents": table,
        "bull_case": [p.as_dict() for p in bull[: rules.max_case_points]],
        "bear_case": [p.as_dict() for p in bear[: rules.max_case_points]],
        "conflicts": conflicts,
        "key_risks": risks,
        "invalidation": invalidation,
        "data_warnings": data_warnings,
        "decision": {"trade": "NO TRADE", "reason": NO_TRADE},
    }
