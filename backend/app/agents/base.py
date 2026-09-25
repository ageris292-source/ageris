"""Agent input/output contract (spec §6, §19).

Every agent returns an AgentOutput. The contract itself enforces the
fail-closed rules: a non-OK output cannot carry a score, signals or
confidence, so a downstream consumer can never mistake a failed or
data-starved analysis for a neutral one.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Annotated, Literal, Self

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, model_validator

Unit = Annotated[float, Field(ge=0.0, le=1.0)]


class AgentStatus(StrEnum):
    OK = "ok"
    INSUFFICIENT_DATA = "insufficient_data"  # not enough history to compute honestly
    DATA_UNUSABLE = "data_unusable"  # stored data failed validation
    FAILED = "failed"  # unexpected error; treated like missing data


class AgentInput(BaseModel):
    model_config = ConfigDict(frozen=True)

    ticker: str
    # Market cut-off: the agent may only use data publicly available at as_of.
    as_of: AwareDatetime
    # Data vintage: only data versions Aegis had retrieved by this instant.
    # Recorded with every run so the analysis can be replayed exactly.
    knowledge_at: AwareDatetime


class Signal(BaseModel):
    model_config = ConfigDict(frozen=True)

    name: str
    category: str
    direction: Literal["bullish", "bearish", "neutral"]
    strength: Unit
    detail: str
    values: dict[str, float | str | None] = Field(default_factory=dict)


class Evidence(BaseModel):
    model_config = ConfigDict(frozen=True)

    ref: str
    description: str


class AgentOutput(BaseModel):
    model_config = ConfigDict(frozen=True)

    agent: str
    agent_version: str
    ticker: str
    as_of: datetime
    knowledge_at: datetime | None = None
    generated_at: datetime
    status: AgentStatus

    score: Annotated[float, Field(ge=0, le=100)] | None
    score_basis: str
    confidence: Unit
    confidence_basis: Literal["heuristic_uncalibrated", "empirically_calibrated", "none"]

    signals: list[Signal] = Field(default_factory=list)
    evidence: list[Evidence] = Field(default_factory=list)
    risks: list[str] = Field(default_factory=list)
    invalidation_conditions: list[str] = Field(default_factory=list)
    metrics: dict[str, float | None] = Field(default_factory=dict)

    data_quality: Unit
    data_snapshot_id: str | None
    config_fingerprint: str
    warnings: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def _fail_closed(self) -> Self:
        if self.status is not AgentStatus.OK:
            if self.score is not None or self.signals or self.confidence != 0:
                raise ValueError(
                    "a non-OK agent output may not carry a score, signals or confidence"
                )
            if not self.warnings:
                raise ValueError("a non-OK agent output must explain why in warnings")
        elif self.score is None:
            raise ValueError("an OK agent output requires a score")
        return self
