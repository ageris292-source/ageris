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


Period = Annotated[int, Field(ge=2, le=400)]


class TechnicalRules(_Strict):
    sma_periods: Annotated[list[Period], Field(min_length=1)]
    rsi_period: Period
    rsi_overbought: Annotated[float, Field(gt=50, lt=100)]
    rsi_oversold: Annotated[float, Field(gt=0, lt=50)]
    macd_fast: Period
    macd_slow: Period
    macd_signal: Period
    bollinger_period: Period
    bollinger_std_devs: Annotated[float, Field(gt=0, le=5)]
    squeeze_lookback: Period
    atr_period: Period
    adx_period: Period
    adx_trend_threshold: Annotated[float, Field(gt=0, lt=100)]
    volatility_window: Period
    momentum_windows: Annotated[list[Period], Field(min_length=1)]
    breakout_lookback: Period
    breakout_volume_multiple: Annotated[float, Field(ge=1, le=10)]
    cross_lookback_sessions: Annotated[int, Field(ge=1, le=60)]
    divergence_lookback: Period
    pivot_window: Annotated[int, Field(ge=1, le=20)]
    sr_lookback: Period
    sr_cluster_tolerance: Annotated[float, Field(gt=0, lt=0.2)]
    sr_max_levels: Annotated[int, Field(ge=1, le=10)]
    min_history_sessions: Annotated[int, Field(ge=30, le=2000)]
    invalidation_atr_multiple: Annotated[float, Field(gt=0, le=10)]
    high_volatility_ratio: Annotated[float, Field(gt=1, le=10)]
    category_weights: dict[
        Literal["trend", "momentum", "breakout", "volume", "mean_reversion"],
        Annotated[float, Field(ge=0, le=1)],
    ]

    @model_validator(mode="after")
    def _consistent(self) -> Self:
        if self.macd_fast >= self.macd_slow:
            raise ValueError("macd_fast must be shorter than macd_slow")
        if self.min_history_sessions < max(self.sma_periods):
            raise ValueError("min_history_sessions must cover the longest SMA period")
        if abs(sum(self.category_weights.values()) - 1.0) > 1e-9:
            raise ValueError("technical.category_weights must sum to 1")
        return self


class FundamentalRules(_Strict):
    quarterly_publication_lag_days: Annotated[int, Field(ge=0, le=180)]
    annual_publication_lag_days: Annotated[int, Field(ge=0, le=365)]
    min_annual_periods: Annotated[int, Field(ge=1, le=20)]
    margin_deterioration_pts: Annotated[float, Field(gt=0, lt=1)]
    weak_cash_conversion: Annotated[float, Field(gt=0, le=2)]
    max_debt_to_equity: Annotated[float, Field(gt=0, le=20)]
    min_interest_coverage: Annotated[float, Field(gt=0, le=100)]
    strong_growth: Annotated[float, Field(gt=0, lt=5)]
    high_roe: Annotated[float, Field(gt=0, lt=5)]
    high_roce: Annotated[float, Field(gt=0, lt=5)]
    expensive_pe: Annotated[float, Field(gt=0, le=500)]
    cheap_pe: Annotated[float, Field(gt=0, le=500)]
    peer_groups: dict[str, list[str]] = Field(default_factory=dict)
    financial_sector_groups: list[str] = Field(default_factory=list)
    min_growth_for_peg: Annotated[float, Field(gt=0, lt=1)] = 0.05
    category_weights: dict[
        Literal["growth", "profitability", "balance_sheet", "cash_quality", "valuation"],
        Annotated[float, Field(ge=0, le=1)],
    ]

    @model_validator(mode="after")
    def _consistent(self) -> Self:
        if self.cheap_pe >= self.expensive_pe:
            raise ValueError("fundamentals.cheap_pe must be below expensive_pe")
        unknown = set(self.financial_sector_groups) - set(self.peer_groups)
        if unknown:
            raise ValueError(f"financial_sector_groups not in peer_groups: {sorted(unknown)}")
        if abs(sum(self.category_weights.values()) - 1.0) > 1e-9:
            raise ValueError("fundamentals.category_weights must sum to 1")
        return self


EVENT_TYPES = (
    "earnings_beat",
    "earnings_miss",
    "results",
    "regulatory",
    "lawsuit",
    "acquisition",
    "management_change",
    "dividend_buyback",
    "product_launch",
    "rating_change",
    "sector",
    "other",
)


class NewsRules(_Strict):
    provider_enabled: bool
    max_items_per_fetch: Annotated[int, Field(ge=1, le=200)]
    sentiment_model: str
    embedding_model: str
    embedding_dim: Annotated[int, Field(ge=8, le=4096)]
    duplicate_similarity: Annotated[float, Field(gt=0.5, lt=1.0)]
    duplicate_window_hours: Annotated[int, Field(ge=1, le=720)]
    lookback_days: Annotated[int, Field(ge=1, le=365)]
    recency_half_life_days: Annotated[float, Field(gt=0, le=90)]
    min_items_for_score: Annotated[int, Field(ge=1, le=100)]
    contradiction_window_days: Annotated[int, Field(ge=1, le=60)]
    chunk_chars: Annotated[int, Field(ge=200, le=8000)]
    chunk_overlap: Annotated[int, Field(ge=0, le=2000)]
    retrieval_top_k: Annotated[int, Field(ge=1, le=50)]
    importance: dict[str, Annotated[float, Field(gt=0, le=1)]]

    @model_validator(mode="after")
    def _consistent(self) -> Self:
        if self.chunk_overlap >= self.chunk_chars:
            raise ValueError("news.chunk_overlap must be smaller than chunk_chars")
        if self.embedding_dim != 384:
            # The pgvector column width is fixed by migration 0005.
            raise ValueError("news.embedding_dim must be 384 (schema column width)")
        missing = set(EVENT_TYPES) - set(self.importance)
        extra = set(self.importance) - set(EVENT_TYPES)
        if missing or extra:
            raise ValueError(f"news.importance keys mismatch: missing={missing} extra={extra}")
        return self


class MacroRules(_Strict):
    world_bank_indicators: dict[str, str]
    world_bank_publication_lag_days: Annotated[int, Field(ge=0, le=730)]
    market_series: dict[str, str]
    benchmark: str
    history_days: Annotated[int, Field(ge=300, le=4000)]
    rbi_inflation_target: Annotated[float, Field(gt=0, lt=0.2)]
    change_window_sessions: Annotated[int, Field(ge=5, le=260)]
    vix_high: Annotated[float, Field(gt=0, le=100)]
    vix_low: Annotated[float, Field(gt=0, le=100)]
    trend_band: Annotated[float, Field(ge=0, lt=0.2)]
    sector_sensitivities: dict[str, dict[str, Annotated[float, Field(ge=-1, le=1)]]]
    default_sensitivities: dict[str, Annotated[float, Field(ge=-1, le=1)]]

    @model_validator(mode="after")
    def _consistent(self) -> Self:
        if self.benchmark not in self.market_series:
            raise ValueError("macro.benchmark must be one of macro.market_series")
        if self.vix_low >= self.vix_high:
            raise ValueError("macro.vix_low must be below vix_high")
        known = set(self.market_series) | set(self.world_bank_indicators) | {"repo_rate"}
        for sector, sens in {
            **self.sector_sensitivities,
            "default": self.default_sensitivities,
        }.items():
            unknown = set(sens) - known
            if unknown:
                raise ValueError(f"macro sensitivities for {sector} use unknown series {unknown}")
        return self


class ScenarioRates(_Strict):
    bear: Annotated[float, Field(ge=0, lt=0.15)]
    base: Annotated[float, Field(ge=0, lt=0.15)]
    bull: Annotated[float, Field(ge=0, lt=0.15)]


class ValuationRules(_Strict):
    risk_free_rate: Annotated[float, Field(gt=0, lt=0.3)]
    equity_risk_premium: Annotated[float, Field(gt=0, lt=0.2)]
    projection_years: Annotated[int, Field(ge=3, le=15)]
    terminal_growth: ScenarioRates
    growth_spread: Annotated[float, Field(ge=0, lt=0.5)]
    wacc_spread: Annotated[float, Field(ge=0, lt=0.1)]
    min_growth: Annotated[float, Field(gt=-0.5, lt=0)]
    max_growth: Annotated[float, Field(gt=0, lt=1)]
    beta_lookback_weeks: Annotated[int, Field(ge=26, le=520)]
    beta_bounds: tuple[float, float]
    mos_scale: Annotated[float, Field(gt=0, le=2)]

    @model_validator(mode="after")
    def _consistent(self) -> Self:
        tg = self.terminal_growth
        if not tg.bear <= tg.base <= tg.bull:
            raise ValueError("valuation.terminal_growth must satisfy bear <= base <= bull")
        lo, hi = self.beta_bounds
        if not 0 < lo < hi:
            raise ValueError("valuation.beta_bounds must be 0 < low < high")
        return self


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


class RiskAnalysisRules(_Strict):
    lookback_sessions: Annotated[int, Field(ge=60, le=2520)]
    min_history_sessions: Annotated[int, Field(ge=30, le=2520)]
    trading_days_per_year: Annotated[int, Field(ge=200, le=366)]
    var_confidence: Annotated[list[Annotated[float, Field(gt=0.5, lt=1)]], Field(min_length=1)]
    low_volatility: Annotated[float, Field(gt=0, lt=2)]
    high_volatility: Annotated[float, Field(gt=0, lt=3)]
    high_beta: Annotated[float, Field(gt=0, lt=5)]
    low_beta: Annotated[float, Field(ge=0, lt=5)]
    drawdown_warning: Annotated[float, Field(gt=0, lt=1)]
    adv_window_sessions: Annotated[int, Field(ge=5, le=260)]
    high_correlation: Annotated[float, Field(gt=0, lt=1)]
    max_effective_positions_floor: Annotated[int, Field(ge=1, le=100)]
    category_weights: dict[str, Annotated[float, Field(gt=0, le=1)]]
    portfolio_fit_weights: dict[str, Annotated[float, Field(gt=0, le=1)]]

    @model_validator(mode="after")
    def _consistent(self) -> Self:
        for name, w in (
            ("category_weights", self.category_weights),
            ("portfolio_fit_weights", self.portfolio_fit_weights),
        ):
            if abs(sum(w.values()) - 1) > 1e-6:
                raise ValueError(f"risk_analysis.{name} must sum to 1")
        if self.min_history_sessions > self.lookback_sessions:
            raise ValueError("risk_analysis.min_history_sessions must be <= lookback_sessions")
        if self.low_volatility >= self.high_volatility:
            raise ValueError("risk_analysis.low_volatility must be below high_volatility")
        if self.low_beta >= self.high_beta:
            raise ValueError("risk_analysis.low_beta must be below high_beta")
        return self


AGENT_NAMES = ("technical", "fundamental", "valuation", "risk", "news", "macro", "portfolio")


class OrchestratorRules(_Strict):
    agent_weights: dict[str, Annotated[float, Field(gt=0, le=1)]]
    required_agents: list[str]
    min_agents_ok: Annotated[int, Field(ge=1, le=7)]
    stance_band: Annotated[float, Field(gt=0, lt=50)]
    conflict_gap: Annotated[float, Field(gt=0, le=100)]
    max_case_points: Annotated[int, Field(ge=1, le=20)]
    conflict_confidence_penalty: Annotated[float, Field(ge=0, lt=1)]

    @model_validator(mode="after")
    def _consistent(self) -> Self:
        unknown = (set(self.agent_weights) | set(self.required_agents)) - set(AGENT_NAMES)
        if unknown:
            raise ValueError(f"orchestrator references unknown agents {sorted(unknown)}")
        if abs(sum(self.agent_weights.values()) - 1) > 1e-6:
            raise ValueError("orchestrator.agent_weights must sum to 1")
        return self


class TradeEngineRules(_Strict):
    cost_schedule: str
    max_report_age_hours: Annotated[float, Field(gt=0, le=24 * 30)]
    required_stance: Literal["POSITIVE_TILT"]
    max_agent_conflicts: Annotated[int, Field(ge=0, le=10)]
    benchmark_expected_annual_return: Annotated[float, Field(ge=0, lt=0.5)]
    min_holding_days: Annotated[int, Field(ge=1, le=365)]
    max_holding_days: Annotated[int, Field(ge=1, le=3650)]
    max_order_value_fraction: Annotated[float, Field(gt=0, le=1)]

    @model_validator(mode="after")
    def _consistent(self) -> Self:
        if self.min_holding_days > self.max_holding_days:
            raise ValueError("trade_engine.min_holding_days must be <= max_holding_days")
        return self


class PaperTradingRules(_Strict):
    approver_role: Literal["admin"]
    max_decision_age_minutes: Annotated[int, Field(ge=1, le=24 * 60)]
    fill_model: Literal["reference_close_plus_costs"]


class RankingRules(_Strict):
    horizon: Annotated[int, Field(ge=1, le=250)]
    stop_atr_multiple: Annotated[float, Field(gt=0, le=10)]
    min_stop_fraction: Annotated[float, Field(gt=0, lt=0.5)]
    target_reward_multiple: Annotated[float, Field(ge=1, le=20)]
    refresh_reports: bool
    top_n: Annotated[int, Field(ge=1, le=500)]


class AlertRules(_Strict):
    telegram_enabled: bool
    email_enabled: bool
    min_severity_to_push: Literal["info", "warning", "critical"]


class MonitoringRules(_Strict):
    psi_bins: Annotated[int, Field(ge=4, le=50)]
    psi_warn: Annotated[float, Field(gt=0, le=1)]
    psi_fail: Annotated[float, Field(gt=0, le=2)]
    min_drifted_features_to_fail: Annotated[int, Field(ge=1, le=50)]
    drift_window_sessions: Annotated[int, Field(ge=1, le=250)]
    min_drift_samples: Annotated[int, Field(ge=10, le=100_000)]
    calibration_window_predictions: Annotated[int, Field(ge=20, le=100_000)]
    min_matured_predictions: Annotated[int, Field(ge=10, le=100_000)]
    max_live_calibration_error: Fraction
    max_calibration_decay: Fraction
    auto_disable: bool

    @model_validator(mode="after")
    def _consistent(self) -> Self:
        if self.psi_warn >= self.psi_fail:
            raise ValueError("monitoring.psi_warn must be below psi_fail")
        if self.min_matured_predictions > self.calibration_window_predictions:
            raise ValueError(
                "monitoring.min_matured_predictions must be <= calibration_window_predictions"
            )
        return self


class SecurityRules(_Strict):
    rate_limit_window_seconds: Annotated[int, Field(ge=1, le=3600)]
    rate_limit_requests: Annotated[int, Field(ge=1, le=100_000)]
    rate_limit_writes: Annotated[int, Field(ge=1, le=100_000)]
    rate_limit_exempt_paths: list[str]
    max_request_bytes: Annotated[int, Field(ge=1024, le=100 * 1024 * 1024)]
    hsts_max_age_seconds: Annotated[int, Field(ge=0, le=2 * 365 * 86_400)]

    @model_validator(mode="after")
    def _consistent(self) -> Self:
        if self.rate_limit_writes > self.rate_limit_requests:
            raise ValueError("security.rate_limit_writes must be <= rate_limit_requests")
        if any(not p.startswith("/") for p in self.rate_limit_exempt_paths):
            raise ValueError("security.rate_limit_exempt_paths must be absolute paths")
        return self


class LightGbmParams(_Strict):
    n_estimators: Annotated[int, Field(ge=10, le=5000)]
    learning_rate: Annotated[float, Field(gt=0, le=1)]
    num_leaves: Annotated[int, Field(ge=2, le=1024)]
    min_child_samples: Annotated[int, Field(ge=1, le=10000)]
    subsample: Annotated[float, Field(gt=0, le=1)]
    colsample_bytree: Annotated[float, Field(gt=0, le=1)]
    reg_lambda: Annotated[float, Field(ge=0, le=100)]


class BacktestRules(_Strict):
    horizons: Annotated[list[Annotated[int, Field(ge=1, le=250)]], Field(min_length=1)]
    min_train_sessions: Annotated[int, Field(ge=100, le=5000)]
    test_fold_sessions: Annotated[int, Field(ge=5, le=500)]
    embargo_sessions: Annotated[int, Field(ge=0, le=250)]
    calibration_fraction: Annotated[float, Field(gt=0, lt=0.5)]
    calibration_bins: Annotated[int, Field(ge=5, le=50)]
    min_train_samples: Annotated[int, Field(ge=100)]
    seed: int
    top_k: Annotated[int, Field(ge=1, le=100)]
    lightgbm: LightGbmParams


class AegisConfig(_Strict):
    config_version: Annotated[str, Field(min_length=1)]
    trade_gates: TradeGateThresholds
    freshness: FreshnessRules
    risk_controls: RiskControls
    position_sizing: PositionSizing
    liquidity: LiquidityRules
    execution: ExecutionRules
    market_data: MarketDataRules
    technical: TechnicalRules
    fundamentals: FundamentalRules
    news: NewsRules
    macro: MacroRules
    valuation: ValuationRules
    risk_analysis: RiskAnalysisRules
    orchestrator: OrchestratorRules
    trade_engine: TradeEngineRules
    backtest: BacktestRules
    paper_trading: PaperTradingRules
    ranking: RankingRules
    alerts: AlertRules
    monitoring: MonitoringRules
    security: SecurityRules
    transaction_costs: Annotated[dict[str, CostSchedule], Field(min_length=1)]

    @model_validator(mode="after")
    def _cross_section(self) -> Self:
        if self.ranking.horizon not in self.backtest.horizons:
            raise ValueError("ranking.horizon must be one of backtest.horizons")
        if self.trade_engine.cost_schedule not in self.transaction_costs:
            raise ValueError("trade_engine.cost_schedule must name a transaction_costs schedule")
        return self

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
