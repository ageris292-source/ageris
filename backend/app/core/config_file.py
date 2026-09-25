"""Strictly-validated YAML configuration for thresholds and cost schedules.

Thresholds must never be scattered through the code (spec §73). Everything
that tunes a gate, a risk limit or a cost lives here, is validated once at
startup, and is fingerprinted so every decision can record which exact
configuration produced it (spec §37-38).
"""

from __future__ import annotations

import hashlib
import json
from functools import lru_cache
from pathlib import Path
from typing import Annotated, Literal, Self

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator

Fraction = Annotated[float, Field(gt=0.0, lt=1.0)]
Probability = Annotated[float, Field(gt=0.5, lt=1.0)]  # a gate below 0.5 would be meaningless
Bps = Annotated[float, Field(ge=0.0, le=1000.0)]


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class TradeGateThresholds(_Strict):
    minimum_expected_net_return: Fraction
    minimum_edge_vs_benchmark: Annotated[float, Field(ge=0.0, lt=1.0)]
    minimum_probability_of_profit: Probability
    minimum_reward_risk_ratio: Annotated[float, Field(ge=1.0, le=20.0)]
    minimum_data_quality_score: Fraction
    maximum_calibration_error: Fraction
    minimum_out_of_sample_periods: Annotated[int, Field(ge=1, le=100)]


class FreshnessRules(_Strict):
    prices_seconds: Annotated[int, Field(gt=0, le=86_400)]
    news_minutes: Annotated[int, Field(gt=0, le=10_080)]
    financials_days: Annotated[int, Field(gt=0, le=400)]
    macro_days: Annotated[int, Field(gt=0, le=120)]
    daily_bars_max_sessions_behind: Annotated[int, Field(ge=0, le=5)]


class RiskControls(_Strict):
    daily_loss_limit: Fraction
    weekly_loss_limit: Fraction
    max_strategy_drawdown: Fraction
    max_portfolio_drawdown: Fraction
    max_single_position_weight: Fraction
    max_sector_weight: Fraction
    max_gross_exposure: Annotated[float, Field(gt=0.0, le=1.0)]  # no leverage in v1

    @model_validator(mode="after")
    def _limits_are_nested(self) -> Self:
        if not (
            self.daily_loss_limit
            <= self.weekly_loss_limit
            <= self.max_strategy_drawdown
            <= self.max_portfolio_drawdown
        ):
            raise ValueError(
                "loss limits must satisfy daily <= weekly <= strategy drawdown "
                "<= portfolio drawdown"
            )
        if self.max_single_position_weight > self.max_sector_weight:
            raise ValueError("max_single_position_weight cannot exceed max_sector_weight")
        return self


class PositionSizing(_Strict):
    method: Literal["fixed_fractional", "volatility_target", "fractional_kelly"]
    risk_per_trade: Annotated[float, Field(gt=0.0, le=0.02)]
    # Unrestricted Kelly is forbidden (spec §46): hard ceiling of half-Kelly.
    kelly_fraction_cap: Annotated[float, Field(gt=0.0, le=0.5)]
    target_annual_volatility: Annotated[float, Field(gt=0.0, le=0.5)]


class LiquidityRules(_Strict):
    minimum_average_daily_traded_value: Annotated[float, Field(gt=0.0)]
    maximum_participation_of_adv: Annotated[float, Field(gt=0.0, le=0.10)]
    maximum_spread_bps: Bps


class ExecutionRules(_Strict):
    maximum_acceptable_entry_deviation: Annotated[float, Field(gt=0.0, le=0.05)]
    require_human_approval_for_live: bool

    @model_validator(mode="after")
    def _human_approval_default(self) -> Self:
        # Phase 1-14: autonomous live trading is not supported at all.
        if not self.require_human_approval_for_live:
            raise ValueError(
                "require_human_approval_for_live=false is not supported; "
                "autonomous live trading is disabled in this build"
            )
        return self


class ProviderSettings(_Strict):
    enabled: bool
    # Unlicensed sources may feed research only; later gates reject them for paper/live.
    licensed: bool
    timeout_seconds: Annotated[float, Field(gt=0, le=60)] = 10.0


class MarketDataRules(_Strict):
    market: Literal["IN"]  # Indian equities only in this build
    calendar: Literal["XBOM"]
    eod_availability_lag_minutes: Annotated[int, Field(ge=0, le=24 * 60)]
    abnormal_move_threshold: Annotated[float, Field(gt=0.0, lt=1.0)]
    stale_price_run_sessions: Annotated[int, Field(ge=2, le=60)]
    max_missing_session_ratio: Annotated[float, Field(ge=0.0, lt=0.5)]
    provider_cache_seconds: Annotated[int, Field(ge=0, le=86_400)]
    providers: dict[Literal["yahoo", "csv_import"], ProviderSettings]


class CostSchedule(_Strict):
    brokerage_bps: Bps
    exchange_fee_bps: Bps
    regulatory_fee_bps: Bps
    stamp_duty_buy_bps: Bps
    securities_tax_bps: Bps
    gst_rate_on_fees: Annotated[float, Field(ge=0.0, lt=1.0)]
    slippage_bps: Bps
    half_spread_bps: Bps
    market_impact_bps_per_pct_adv: Bps
    annual_financing_rate: Annotated[float, Field(ge=0.0, lt=1.0)]


class AegisConfig(_Strict):
    config_version: Annotated[str, Field(min_length=1)]
    trade_gates: TradeGateThresholds
    freshness: FreshnessRules
    risk_controls: RiskControls
    position_sizing: PositionSizing
    liquidity: LiquidityRules
    execution: ExecutionRules
    market_data: MarketDataRules
    transaction_costs: Annotated[dict[str, CostSchedule], Field(min_length=1)]

    def fingerprint(self) -> str:
        """Stable SHA-256 of the effective configuration, recorded in audits."""
        canonical = json.dumps(self.model_dump(mode="json"), sort_keys=True)
        return hashlib.sha256(canonical.encode()).hexdigest()


class ConfigError(RuntimeError):
    """Raised when the configuration file is missing or invalid. Boot must abort."""


def load_config(path: str | Path) -> AegisConfig:
    p = Path(path)
    if not p.is_file():
        raise ConfigError(f"configuration file not found: {p}")
    try:
        raw = yaml.safe_load(p.read_text())
    except yaml.YAMLError as exc:
        raise ConfigError(f"configuration file is not valid YAML: {exc}") from exc
    if not isinstance(raw, dict):
        raise ConfigError("configuration root must be a mapping")
    try:
        return AegisConfig.model_validate(raw)
    except ValueError as exc:
        raise ConfigError(f"invalid configuration in {p}:\n{exc}") from exc


@lru_cache(maxsize=1)
def get_config() -> AegisConfig:
    from app.core.settings import get_settings

    return load_config(get_settings().config_path)
