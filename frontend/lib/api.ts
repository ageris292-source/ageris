// Thin typed client for the Aegis API. The browser only ever holds a
// short-lived user JWT — never provider or broker API keys (spec §68).

export const API_URL = process.env.NEXT_PUBLIC_AEGIS_API_URL ?? "http://localhost:8000";

export type GateStatus = "PASS" | "FAIL" | "UNKNOWN";

export interface Health {
  status: "ok" | "degraded";
  version: string;
  environment: string;
  system_mode: "research" | "paper" | "live";
  demo_data: boolean;
  components: { name: string; healthy: boolean }[];
}

export interface KillSwitch {
  active: boolean;
  reason: string;
  state_known: boolean;
}

export interface RiskStatus {
  generated_at: string;
  system_mode: string;
  live_trading_enabled_flag: boolean;
  kill_switch: KillSwitch;
  live_orders_permitted: boolean;
  paper_orders_permitted: boolean;
  checks: { name: string; status: GateStatus; reason: string }[];
  blocking_reasons: string[];
  config_version: string;
  config_fingerprint: string;
  disclaimer: string;
}

export interface Me {
  email: string;
  role: "admin" | "analyst";
  id?: string;
  must_change_password?: boolean;
  created_at?: string | null;
  last_login_at?: string | null;
}

export interface UserAdmin {
  id: string;
  email: string;
  role: "admin" | "analyst";
  is_active: boolean;
  must_change_password: boolean;
  created_at: string;
  last_login_at: string | null;
}

export interface InviteResult {
  user: UserAdmin;
  temporary_password: string;
  notice: string;
}

export interface WatchlistRow {
  ticker: string;
  name: string | null;
  exchange: string;
  note: string | null;
  added_at: string;
  list_id: number;
  latest_session: string | null;
  last_close: number | null;
  prev_close: number | null;
  change_pct: number | null;
  sparkline: number[];
  freshness: GateStatus;
  stance: Stance | null;
  composite: number | null;
  report_at: string | null;
}

export interface TokenOut {
  access_token: string;
  expires_in_seconds: number;
}

export type Basis = "raw" | "split_adjusted" | "total_return";

export interface Freshness {
  status: GateStatus;
  latest_session: string | null;
  expected_session: string | null;
  sessions_behind: number | null;
  reason: string;
}

export interface StockSummary {
  ticker: string;
  symbol: string;
  exchange: "NSE" | "BSE";
  name: string | null;
  currency: string;
  latest_session: string | null;
  freshness: Freshness;
  last_run_status: string | null;
  last_close?: number | null;
  change_pct?: number | null;
  sparkline?: number[];
}

export interface BarOut {
  session: string;
  open: string;
  high: string;
  low: string;
  close: string;
  volume: number;
  source: string;
  data_version: number;
  retrieved_at: string;
  effective_at: string;
  available_at: string;
}

export interface QualityIssue {
  code: string;
  severity: "critical" | "warning" | "info";
  session: string | null;
  detail: string;
}

export interface IngestionRun {
  id: number;
  provider: string;
  licensed: boolean;
  basis: Basis | null;
  status: string;
  requested_start: string;
  requested_end: string;
  started_at: string;
  finished_at: string | null;
  retrieved_at: string | null;
  rows_received: number;
  rows_inserted: number;
  rows_unchanged: number;
  rows_revised: number;
  rows_rejected: number;
  quality_score: number | null;
  usable: boolean;
  error: string | null;
}

export interface StockDetail extends StockSummary {
  latest_bar: BarOut | null;
  stored_basis: Basis | null;
  source: string | null;
  licensed: boolean | null;
  licensing_notice: string | null;
  data_quality: {
    window_start: string | null;
    window_end: string | null;
    usable: boolean;
    quality_score: number;
    expected_sessions: number;
    missing_session_count: number;
    coverage: number;
    minimum_score_required: number;
    issues: QualityIssue[];
  } | null;
  corporate_actions: {
    kind: "split" | "dividend";
    ex_date: string;
    numerator: string | null;
    denominator: string | null;
    amount: string | null;
  }[];
  recent_runs: IngestionRun[];
  open_conflicts: number;
}

export interface PriceSeries {
  ticker: string;
  basis: Basis;
  stored_basis: Basis | null;
  derived: boolean;
  source: string | null;
  licensed: boolean | null;
  licensing_notice: string | null;
  as_of: string | null;
  currency: string;
  bars: BarOut[];
}

export interface AgentSignal {
  name: string;
  category: string;
  direction: "bullish" | "bearish" | "neutral";
  strength: number;
  detail: string;
}

export interface AgentOutput {
  agent: string;
  agent_version: string;
  ticker: string;
  as_of: string;
  knowledge_at: string | null;
  generated_at: string;
  status: "ok" | "insufficient_data" | "data_unusable" | "failed";
  score: number | null;
  score_basis: string;
  confidence: number;
  confidence_basis: string;
  signals: AgentSignal[];
  evidence: { ref: string; description: string }[];
  risks: string[];
  invalidation_conditions: string[];
  metrics: Record<string, number | null>;
  data_quality: number;
  data_snapshot_id: string | null;
  config_fingerprint: string;
  warnings: string[];
}

export interface IndicatorPoint {
  session: string;
  close: number;
  sma_mid: number | null;
  sma_long: number | null;
  rsi: number | null;
  macd: number | null;
  macd_signal: number | null;
  macd_histogram: number | null;
}

export interface IndicatorSeries {
  ticker: string;
  basis: Basis;
  calculation_version: string;
  sma_mid_period: number;
  sma_long_period: number;
  rsi_overbought: number;
  rsi_oversold: number;
  points: IndicatorPoint[];
}

export interface FinancialPeriod {
  period_end: string;
  values: Record<string, number>;
  ratios: Record<string, number | null>;
}

export interface Financials {
  ticker: string;
  currency: string;
  sources: string[];
  licensed: boolean | null;
  availability_estimated: boolean;
  annual: FinancialPeriod[];
  quarterly: FinancialPeriod[];
  notice: string | null;
}

export interface NewsItem {
  id: number;
  title: string;
  publisher: string | null;
  url: string;
  published_at: string | null;
  event_type: string;
  sentiment_label: "positive" | "negative" | "neutral" | null;
  sentiment_score: number | null;
  duplicate_of: number | null;
}

export interface DcfScenario {
  per_share: number;
  margin_of_safety: number;
  enterprise_value: number;
  equity_value: number;
  terminal_share_of_ev: number;
  assumptions: {
    revenue: number;
    growth: number;
    fcf_margin: number;
    wacc: number;
    terminal_growth: number;
    years: number;
  };
  notes: string[];
}

export interface ValuationDetails {
  price?: number;
  price_date?: string;
  scenarios?: Record<"bear" | "base" | "bull", DcfScenario>;
  sensitivity?: { wacc_deltas: number[]; growth_deltas: number[]; per_share: (number | null)[][] };
  wacc?: number;
  beta_raw?: number | null;
  beta_used?: number;
  beta_weeks?: number;
  tax_rate?: number;
  revenue_cagr?: number;
  dcf_reliable?: boolean;
  peer_medians?: Record<string, number | null>;
}

export interface Valuation {
  analysis: AgentOutput;
  details: ValuationDetails;
}

export interface Regime {
  label: string;
  trend: string;
  volatility: string;
  risk: string;
  known: boolean;
  evidence: Record<string, number | null>;
}

export interface PortfolioSummary {
  id: number;
  name: string;
  kind: "model" | "paper";
  currency: string;
  cash: string;
  starting_cash: string;
  positions: { ticker: string; quantity: number; avg_cost: string }[];
}

export interface PortfolioCheck {
  name: string;
  kind: "limit" | "advisory";
  status: GateStatus;
  value: number | null;
  limit: number | null;
  reason: string;
  offenders: string[];
}

export interface PortfolioAnalysis {
  portfolio: { id: number; name: string; kind: string; currency: string };
  as_of: string;
  limits_status: GateStatus;
  holdings: {
    ticker: string;
    quantity: number;
    avg_cost: number | null;
    price: number | null;
    price_date: string | null;
    value: number | null;
    weight: number;
    sector: string;
    unrealised_pnl: number | null;
    adtv: number | null;
    candidate: boolean;
  }[];
  sector_weights: Record<string, number>;
  checks: PortfolioCheck[];
  metrics: Record<string, number | null>;
  correlation: Record<string, Record<string, number>>;
  high_correlation_pairs: { a: string; b: string; correlation: number }[];
  candidate: { ticker: string; weight: number; price: number | null; quantity: number; value: number | null } | null;
  common_sessions: number;
  warnings: string[];
}

export interface PortfolioFit {
  analysis: AgentOutput;
  details: { before: PortfolioAnalysis; after: PortfolioAnalysis };
}

export interface CasePoint {
  agent: string;
  signal: string;
  detail: string;
  weight: number;
  evidence: string | null;
}

export type Stance = "POSITIVE_TILT" | "NEGATIVE_TILT" | "NO_CLEAR_TILT" | "INSUFFICIENT_DATA";

export interface AnalysisReport {
  report_id: number;
  report_hash: string;
  created_at: string | null;
  hash_verified?: boolean;
  ticker: string;
  as_of: string;
  knowledge_at: string;
  synthesis: {
    stance: Stance;
    stance_text: string;
    composite_score: number | null;
    composite_basis: string;
    confidence: number;
    coverage: number;
    insufficient_reasons: string[];
    agents: {
      agent: string;
      status: string;
      score: number | null;
      confidence: number;
      data_quality: number;
      weight: number;
    }[];
    bull_case: CasePoint[];
    bear_case: CasePoint[];
    conflicts: { agents: string[]; scores: number[]; detail: string }[];
    key_risks: { agent: string; risk: string }[];
    data_warnings: { agent: string; warning: string }[];
    decision: { trade: string; reason: string };
  };
  narrative: { text: string; source: string; warnings: string[] };
}

export type TradeGateStatus = GateStatus | "NOT_APPLICABLE";

export interface TradeGate {
  order: number;
  name: string;
  status: TradeGateStatus;
  value: number | string | null;
  threshold: number | string | null;
  reason: string;
}

export interface TradeProposalIn {
  ticker: string;
  side: "buy" | "sell";
  quantity: number;
  entry_price: string;
  stop_loss: string | null;
  target: string | null;
  horizon_days: number;
  portfolio_id: number;
  mode: "paper" | "live";
  quoted_spread_bps: number | null;
  rationale?: string;
}

export interface TradeDecision {
  proposal_id: number;
  decision_id: number;
  decision: "APPROVED" | "REJECTED";
  engine_version: string;
  evaluated_at: string;
  gates: TradeGate[];
  failed_gates: string[];
  first_failure: string | null;
  requires_human_approval: boolean;
  costs: { round_trip_fraction: number; buy_bps: number; sell_bps: number; participation_pct_of_adv: number | null } | null;
  metrics: Record<string, number | null>;
  decision_hash: string;
}

export interface GateCatalog {
  engine_version: string;
  self_test: { passed: boolean; detail: string };
  rule: string;
  gates: { order: number; name: string; applies_to_exits: boolean; description: string }[];
}

export interface ProposalRow {
  proposal_id: number;
  decision_id: number;
  created_at: string;
  ticker: string;
  side: string;
  mode: string;
  quantity: number;
  entry_price: string;
  portfolio_id: number;
  decision: "APPROVED" | "REJECTED";
  first_failure: string | null;
  rationale?: string;
}

export interface BacktestSummary {
  id: number;
  created_at: string | null;
  status: "running" | "completed" | "failed";
  horizon: number;
  as_of: string;
  universe_size: number;
  survivorship_bias: string;
  duration_ms: number | null;
  error: string | null;
  headline: {
    auc_profit: number | null;
    ece_profit: number | null;
    folds: number | null;
    total_return: number | null;
    benchmark_total_return: number | null;
  };
}

export interface ClassMetrics {
  n: number;
  base_rate: number | null;
  auc: number | null;
  brier: number | null;
  log_loss: number | null;
  ece: number | null;
}

export interface BacktestDetail extends BacktestSummary {
  universe: string[];
  reproducibility: Record<string, unknown> & { libraries?: Record<string, string>; seed?: number };
  data_hash: string | null;
  config_fingerprint: string;
  warnings: string[];
  metrics: {
    profit: ClassMetrics;
    outperform: ClassMetrics;
    calibration_curve_profit: { mean_predicted: number; observed_rate: number; count: number }[];
    oos_start: string;
    oos_end: string;
    folds_trained: number;
    folds_skipped: number;
    oos_rows: number;
  } | null;
  folds: (Record<string, unknown> & { fold: number; test_start: string; test_end: string; skipped?: boolean; reason?: string; profit?: ClassMetrics })[] | null;
  simulation: {
    periods: { date: string; names: string[]; strategy_return: number; benchmark_return: number; equity: number; benchmark_equity: number }[];
    summary: Record<string, number | null>;
  } | null;
}

export interface ModelRow {
  id: number;
  name: string;
  horizon: number;
  status: "candidate" | "active" | "retired";
  valid_from: string;
  calibration_error: number;
  oos_periods: number;
  auc: number | null;
  passes_calibration_gate: boolean;
  passes_oos_gate: boolean;
  backtest_run_id: number;
}

export interface PaperOrderOut {
  id: number;
  created_at: string | null;
  decision_id: number;
  recheck_decision_id: number | null;
  portfolio_id: number;
  ticker: string;
  side: string;
  quantity: number;
  limit_price: string;
  status: "FILLED" | "REJECTED";
  reason: string;
  replayed?: boolean;
}

export interface PaperPortfolioOut {
  analysis: PortfolioAnalysis;
  starting_cash: string;
  total_return: number | null;
  realised_pnl: string;
  fees_paid: string;
  executions: {
    id: number;
    order_id: number;
    executed_at: string;
    side: string;
    quantity: number;
    reference_price: string;
    fill_price: string;
    notional: string;
    fees: string;
    realised_pnl: string | null;
    cash_after: string;
    ticker: string;
  }[];
  theses: {
    id: number;
    ticker: string;
    status: string;
    opened_at: string;
    entry_price: string;
    stop_loss: string;
    target: string;
    horizon_end: string;
    invalidation: string[];
    events: { session: string; kind: string; detail: string; exit_proposal_id: number | null; exit_decision: string | null }[];
  }[];
  equity_curve: { taken_at: string; equity: number; source: string }[];
}

export interface RankingRow {
  rank: number;
  ticker: string;
  name: string | null;
  stance: Stance | null;
  composite: number | null;
  report_id: number | null;
  qualified: boolean;
  first_failure: string | null;
  failures: string[];
  entry?: number;
  stop?: number;
  target?: number;
  quantity?: number;
  p_profit?: number | null;
  p_outperform?: number | null;
  expected_net_return?: number | null;
  reward_risk?: number | null;
  round_trip_cost?: number | null;
  needs_live_quote?: boolean;
}

export interface RankingRun {
  id: number;
  created_at: string | null;
  as_of: string;
  horizon: number;
  portfolio_id: number | null;
  headline: string;
  qualified: number;
  evaluated: number;
  gate_failure_counts: Record<string, number>;
  operational_blockers: string[];
  config_fingerprint: string;
  rows?: RankingRow[];
}

export interface Counterfactuals {
  groups: { group: string; n: number; mean_forward_return: number; hit_rate: number; mean_excess_vs_nifty: number | null }[];
  pending: number;
  rankings: number;
}

export type AlertSeverity = "info" | "warning" | "critical";

export interface AlertOut {
  id: number;
  created_at: string | null;
  kind: string;
  severity: AlertSeverity;
  title: string;
  body: string;
  link: string | null;
  deliveries: Record<string, string>;
  read_at: string | null;
  personal?: boolean;
}

export interface AlertChannels {
  in_app: { available: boolean; reason: string | null };
  telegram: { available: boolean; reason: string | null };
  email: { available: boolean; reason: string | null };
  min_severity_to_push: AlertSeverity;
}

export type MonitorStatus = "PASS" | "WARN" | "FAIL" | "UNKNOWN";

export interface DriftFeature {
  feature: string;
  psi: number | null;
  status: MonitorStatus;
  warn_at?: number;
  fail_at?: number;
}

export interface MonitorRun {
  id: number;
  created_at: string | null;
  as_of: string;
  model_id: number;
  model_name: string | null;
  model_status: string | null;
  horizon: number | null;
  status: MonitorStatus;
  action: "none" | "retired";
  reasons: string[];
  predictions_logged: number;
  max_psi: number | null;
  drift_status: MonitorStatus;
  calibration_status: MonitorStatus;
  live_ece: number | null;
  backtest_ece: number | null;
  config_fingerprint: string;
  drift?: { status: MonitorStatus; reasons: string[]; samples: number; max_psi?: number | null; features: DriftFeature[] };
  calibration?: {
    status: MonitorStatus;
    reasons: string[];
    matured: number;
    pending: number;
    evaluated: number;
    backtest_ece: number;
    live_ece?: number;
    decay?: number;
    brier?: number | null;
    auc?: number | null;
    base_rate?: number | null;
    mean_predicted?: number;
    window_start?: string;
    window_end?: string;
    curve?: { bin_low: number; bin_high: number; mean_predicted: number; observed_rate: number; count: number }[];
  };
}

export interface MonitoringOverview {
  as_of: string;
  rules: Record<string, number | boolean>;
  models: {
    model_id: number;
    name: string;
    status: string;
    horizon: number;
    valid_from: string;
    monitorable: boolean;
    predictions: number;
    latest: MonitorRun | null;
  }[];
}

export interface ProviderInfo {
  name: string;
  enabled: boolean;
  licensed: boolean;
  available: boolean;
  reason: string;
}

export interface LiveStatus {
  available: boolean;
  broker: string;
  broker_reason: string;
  live_orders_permitted: boolean;
  blocking_reasons: string[];
}

export interface MacroRow {
  series: string;
  latest_date: string | null;
  latest_value: number | null;
  observations: number;
  licensed: boolean | null;
  retrieved_at: string | null;
}

export interface MacroManualIn {
  series: string;
  period_date: string;
  value: number;
  unit: string;
  source: string;
  published_at: string;
}

export interface ModelEstimate {
  available: boolean;
  reason?: string;
  model_id?: string;
  horizon_days?: number;
  as_of_date?: string;
  p_profit?: number;
  p_outperform?: number;
  expected_return?: number;
  calibration_error?: number;
  oos_periods?: number;
}

export interface ReportHistoryRow {
  report_id: number;
  created_at: string;
  as_of: string;
  stance: Stance;
  composite_score: number | null;
  confidence: number | null;
}

export interface CostResult {
  schedule: string;
  buy_bps: number;
  sell_bps: number;
  impact_bps_each_side: number;
  financing_fraction: number;
  round_trip_fraction: number;
  order_value: number;
  participation_pct_of_adv: number | null;
  items_bps: Record<string, number>;
  adtv: number | null;
  notice: string;
}

// ---------------------------------------------------------------- user features

export interface WatchlistList {
  id: number;
  name: string;
  position: number;
  count: number;
  created_at: string;
}

export type PriceCondition =
  | "price_above"
  | "price_below"
  | "day_change_up"
  | "day_change_down"
  | "rsi_above"
  | "rsi_below";

export interface PriceAlertRule {
  id: number;
  ticker: string;
  name: string | null;
  condition: PriceCondition;
  threshold: number;
  description: string;
  note: string | null;
  repeat: boolean;
  importance: "normal" | "high";
  is_active: boolean;
  armed: boolean;
  created_at: string;
  last_checked_at: string | null;
  last_session: string | null;
  last_value: number | null;
  last_status: string | null;
  last_triggered_at: string | null;
  trigger_count: number;
}

export interface PriceAlertIn {
  ticker: string;
  condition: PriceCondition;
  threshold: number;
  note?: string | null;
  repeat?: boolean;
  importance?: "normal" | "high";
}

export type JournalKind = "note" | "entry" | "exit" | "review";

export interface JournalEntryOut {
  id: number;
  kind: JournalKind;
  title: string | null;
  body: string;
  tags: string[];
  ticker: string | null;
  stock_name: string | null;
  order: {
    id: number;
    side: "buy" | "sell";
    quantity: number;
    limit_price: string;
    status: string;
    created_at: string | null;
  } | null;
  created_at: string;
  updated_at: string;
}

export interface JournalIn {
  ticker?: string | null;
  order_id?: number | null;
  kind?: JournalKind;
  title?: string | null;
  body: string;
  tags?: string[];
}

export interface ActivityItem {
  id: number;
  occurred_at: string;
  action: string;
  actor_id: string | null;
  actor_email: string | null;
  entity_type: string | null;
  entity_id: string | null;
  system_mode: string;
  details: Record<string, unknown>;
}

export interface ActivityPage {
  scope: "all" | "me";
  items: ActivityItem[];
  next_before_id: number | null;
  groups: Record<string, string>;
}

export interface SignInItem {
  id: number;
  occurred_at: string;
  action: string;
  client: string | null;
  agent: string | null;
}

export interface PaperPerformance {
  portfolio: { id: number; name: string; starting_cash: number };
  as_of: string;
  trades: {
    fills: number;
    closed: number;
    wins: number;
    losses: number;
    win_rate: number | null;
    avg_win: number | null;
    avg_loss: number | null;
    profit_factor: number | null;
    best: number | null;
    worst: number | null;
    realised_pnl: number;
    fees_paid: number;
  };
  equity: {
    points: number;
    last_equity: number | null;
    total_return: number | null;
    max_drawdown: number | null;
  };
  benchmark: {
    series: string;
    available: boolean;
    return: number | null;
    excess_return: number | null;
  };
  curve: { date: string; equity: number; portfolio_index: number | null; benchmark_index: number | null }[];
  by_ticker: { ticker: string; trades: number; wins: number; realised_pnl: number }[];
}

export type ExportKind =
  | "orders"
  | "fills"
  | "positions"
  | "equity"
  | "watchlist"
  | "journal"
  | "price-alerts"
  | "activity";

export class ApiError extends Error {
  constructor(public status: number, message: string) {
    super(message);
  }
}

async function request<T>(path: string, init: RequestInit = {}, token?: string): Promise<T> {
  const headers = new Headers(init.headers);
  if (token) headers.set("Authorization", `Bearer ${token}`);
  const res = await fetch(`${API_URL}${path}`, { ...init, headers, cache: "no-store" });
  if (!res.ok) {
    let detail = res.statusText || `HTTP ${res.status}`;
    try {
      const body = await res.json();
      detail = typeof body.detail === "string" ? body.detail : JSON.stringify(body.detail);
    } catch {
      /* non-JSON error body */
    }
    throw new ApiError(res.status, detail);
  }
  if (res.status === 204) return undefined as T;
  return (await res.json()) as T;
}

async function requestText(path: string, token: string): Promise<string> {
  const res = await fetch(`${API_URL}${path}`, {
    headers: { Authorization: `Bearer ${token}` },
    cache: "no-store",
  });
  if (!res.ok) throw new ApiError(res.status, res.statusText);
  return res.text();
}

const json = (body: unknown): RequestInit => ({
  method: "POST",
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify(body),
});

/** Download a CSV export (the API needs the bearer token, so no plain link). */
async function downloadCsv(path: string, token: string, fallbackName: string): Promise<void> {
  const res = await fetch(`${API_URL}${path}`, {
    headers: { Authorization: `Bearer ${token}` },
    cache: "no-store",
  });
  if (!res.ok) {
    let detail = res.statusText || `HTTP ${res.status}`;
    try {
      const b = await res.json();
      detail = typeof b.detail === "string" ? b.detail : detail;
    } catch {
      /* not JSON */
    }
    throw new ApiError(res.status, detail);
  }
  const cd = res.headers.get("content-disposition") ?? "";
  const name = /filename="([^"]+)"/.exec(cd)?.[1] ?? fallbackName;
  const url = URL.createObjectURL(await res.blob());
  const a = document.createElement("a");
  a.href = url;
  a.download = name;
  document.body.appendChild(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

const qs = (params: Record<string, string | number | boolean | null | undefined>) => {
  const u = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) if (v !== null && v !== undefined && v !== "") u.set(k, String(v));
  const t = u.toString();
  return t ? `?${t}` : "";
};

const patch = (body: unknown): RequestInit => ({
  method: "PATCH",
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify(body),
});

export const api = {
  changePassword: (token: string, current_password: string, new_password: string) =>
    request<TokenOut>("/auth/change-password", json({ current_password, new_password }), token),
  users: (token: string) => request<UserAdmin[]>("/users", {}, token),
  inviteUser: (token: string, email: string, role: "admin" | "analyst") =>
    request<InviteResult>("/users", json({ email, role }), token),
  updateUser: (token: string, id: string, body: { role?: "admin" | "analyst"; is_active?: boolean }) =>
    request<UserAdmin>(`/users/${id}`, patch(body), token),
  resetUserPassword: (token: string, id: string) =>
    request<InviteResult>(`/users/${id}/reset-password`, { method: "POST" }, token),
  watchlist: (token: string, listId?: number | null) =>
    request<WatchlistRow[]>(`/watchlist${qs({ list_id: listId })}`, {}, token),
  watch: (token: string, ticker: string, note?: string, listId?: number | null) =>
    request<WatchlistRow>("/watchlist", json({ ticker, note: note || null, list_id: listId ?? null }), token),
  unwatch: (token: string, ticker: string, listId?: number | null) =>
    request<void>(`/watchlist/${encodeURIComponent(ticker)}${qs({ list_id: listId })}`, { method: "DELETE" }, token),
  watchMembership: (token: string, ticker: string) =>
    request<number[]>(`/watchlist/membership/${encodeURIComponent(ticker)}`, {}, token),
  watchlists: (token: string) => request<WatchlistList[]>("/watchlists", {}, token),
  createWatchlist: (token: string, name: string) => request<WatchlistList>("/watchlists", json({ name }), token),
  updateWatchlist: (token: string, id: number, body: { name?: string; position?: number }) =>
    request<WatchlistList>(`/watchlists/${id}`, patch(body), token),
  deleteWatchlist: (token: string, id: number) => request<void>(`/watchlists/${id}`, { method: "DELETE" }, token),

  priceAlerts: (token: string, ticker?: string) =>
    request<PriceAlertRule[]>(`/price-alerts${qs({ ticker })}`, {}, token),
  createPriceAlert: (token: string, body: PriceAlertIn) =>
    request<PriceAlertRule>("/price-alerts", json(body), token),
  updatePriceAlert: (
    token: string,
    id: number,
    body: Partial<Pick<PriceAlertRule, "threshold" | "note" | "repeat" | "importance" | "is_active">>,
  ) => request<PriceAlertRule>(`/price-alerts/${id}`, patch(body), token),
  deletePriceAlert: (token: string, id: number) =>
    request<void>(`/price-alerts/${id}`, { method: "DELETE" }, token),
  checkPriceAlerts: (token: string) =>
    request<{ checked: number; fired: number }>("/price-alerts/check", { method: "POST" }, token),

  journal: (
    token: string,
    f: { ticker?: string; kind?: JournalKind; order_id?: number; tag?: string; q?: string; limit?: number } = {},
  ) => request<JournalEntryOut[]>(`/journal${qs(f)}`, {}, token),
  createJournal: (token: string, body: JournalIn) => request<JournalEntryOut>("/journal", json(body), token),
  updateJournal: (token: string, id: number, body: Partial<Omit<JournalIn, "ticker" | "order_id">>) =>
    request<JournalEntryOut>(`/journal/${id}`, patch(body), token),
  deleteJournal: (token: string, id: number) => request<void>(`/journal/${id}`, { method: "DELETE" }, token),

  activity: (token: string, f: { actor?: string; action?: string; before_id?: number; limit?: number } = {}) =>
    request<ActivityPage>(`/activity${qs(f)}`, {}, token),
  signIns: (token: string) =>
    request<{ items: SignInItem[]; failed_recent: number }>("/auth/sessions", {}, token),
  logoutEverywhere: (token: string) => request<TokenOut>("/auth/logout-all", { method: "POST" }, token),
  exportCsv: (token: string, kind: ExportKind, params: { portfolio_id?: number; list_id?: number } = {}) =>
    downloadCsv(`/export/${kind}.csv${qs(params)}`, token, `aegis-${kind}.csv`),
  paperPerformance: (token: string, id: number) =>
    request<PaperPerformance>(`/paper/portfolios/${id}/performance`, {}, token),
  health: () => request<Health>("/health"),
  login: (email: string, password: string) =>
    request<{ access_token: string; expires_in_seconds: number }>("/auth/token", {
      method: "POST",
      body: new URLSearchParams({ username: email, password }),
    }),
  me: (token: string) => request<Me>("/auth/me", {}, token),
  riskStatus: (token: string) => request<RiskStatus>("/risk/status", {}, token),
  setKillSwitch: (token: string, active: boolean, reason: string) =>
    request<KillSwitch>(
      "/trading/kill-switch",
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ active, reason }),
      },
      token,
    ),
  stocks: (token: string) => request<StockSummary[]>("/stocks", {}, token),
  addStock: (token: string, ticker: string) =>
    request<StockSummary>("/stocks", json({ ticker }), token),
  stock: (token: string, ticker: string) =>
    request<StockDetail>(`/stocks/${encodeURIComponent(ticker)}`, {}, token),
  prices: (token: string, ticker: string, basis: Basis, start: string, end: string) =>
    request<PriceSeries>(
      `/stocks/${encodeURIComponent(ticker)}/prices?` +
        new URLSearchParams({ basis, start, end }).toString(),
      {},
      token,
    ),
  ingest: (token: string, ticker: string) =>
    request<IngestionRun>(`/stocks/${encodeURIComponent(ticker)}/ingest`, json({}), token),
  technical: (token: string, ticker: string) =>
    request<AgentOutput>(`/technical/${encodeURIComponent(ticker)}`, {}, token),
  indicators: (token: string, ticker: string, start: string, end: string) =>
    request<IndicatorSeries>(
      `/technical/${encodeURIComponent(ticker)}/indicators?` +
        new URLSearchParams({ start, end }).toString(),
      {},
      token,
    ),
  fundamental: (token: string, ticker: string) =>
    request<AgentOutput>(`/fundamental/${encodeURIComponent(ticker)}`, {}, token),
  financials: (token: string, ticker: string) =>
    request<Financials>(`/financials/${encodeURIComponent(ticker)}`, {}, token),
  ingestFinancials: (token: string, ticker: string) =>
    request<IngestionRun>(`/financials/${encodeURIComponent(ticker)}/ingest`, json({}), token),
  news: (token: string, ticker: string) =>
    request<NewsItem[]>(`/news/${encodeURIComponent(ticker)}?limit=30`, {}, token),
  ingestNews: (token: string, ticker: string) =>
    request<IngestionRun>(`/news/${encodeURIComponent(ticker)}/ingest`, json({}), token),
  newsAgent: (token: string, ticker: string) =>
    request<AgentOutput>(`/news-agent/${encodeURIComponent(ticker)}`, {}, token),
  macroAgent: (token: string, ticker: string) =>
    request<AgentOutput>(`/macro-agent/${encodeURIComponent(ticker)}`, {}, token),
  valuation: (token: string, ticker: string) =>
    request<Valuation>(`/valuation/${encodeURIComponent(ticker)}`, {}, token),
  regime: (token: string) => request<Regime>("/regime", {}, token),
  runAnalysis: (token: string, ticker: string) =>
    request<AnalysisReport>(`/analysis/${encodeURIComponent(ticker)}`, json({}), token),
  latestAnalysis: (token: string, ticker: string) =>
    request<AnalysisReport>(`/analysis/${encodeURIComponent(ticker)}/latest`, {}, token),
  reportMarkdown: (token: string, id: number) => requestText(`/reports/${id}/markdown`, token),
  tradeGates: (token: string) => request<GateCatalog>("/trade/gates", {}, token),
  submitProposal: (token: string, body: TradeProposalIn) =>
    request<TradeDecision>("/trade/proposals", json(body), token),
  proposals: (token: string) => request<ProposalRow[]>("/trade/proposals?limit=30", {}, token),
  decision: (token: string, id: number) => request<TradeDecision>(`/trade/decisions/${id}`, {}, token),
  backtests: (token: string) => request<BacktestSummary[]>("/backtests", {}, token),
  backtest: (token: string, id: number) => request<BacktestDetail>(`/backtests/${id}`, {}, token),
  runBacktest: (token: string, horizon: number) =>
    request<BacktestDetail>("/backtests", json({ horizon }), token),
  models: (token: string) => request<ModelRow[]>("/models", {}, token),
  setModel: (token: string, id: number, action: "activate" | "retire") =>
    request<ModelRow>(`/models/${id}/${action}`, { method: "POST" }, token),
  placePaperOrder: (token: string, decisionId: number, key: string) =>
    request<PaperOrderOut>(
      "/paper/orders",
      { ...json({ decision_id: decisionId }), headers: { "Content-Type": "application/json", "Idempotency-Key": key } },
      token,
    ),
  paperOrders: (token: string, portfolioId: number) =>
    request<PaperOrderOut[]>(`/paper/orders?portfolio_id=${portfolioId}`, {}, token),
  paperPortfolio: (token: string, id: number) => request<PaperPortfolioOut>(`/paper/portfolios/${id}`, {}, token),
  runMonitor: (token: string) =>
    request<{ events: { thesis_id: number; kind: string; detail: string }[] }>("/paper/monitor", { method: "POST" }, token),
  proposalsFor: (token: string, portfolioId: number) =>
    request<ProposalRow[]>(`/trade/proposals?portfolio_id=${portfolioId}&limit=100`, {}, token),
  runRanking: (token: string, refresh?: boolean) =>
    request<RankingRun>("/ranking/run", json(refresh === undefined ? {} : { refresh }), token),
  latestRanking: (token: string) => request<RankingRun>("/ranking/latest", {}, token),
  rankingHistory: (token: string) => request<RankingRun[]>("/ranking/history?limit=30", {}, token),
  counterfactuals: (token: string) => request<Counterfactuals>("/ranking/counterfactuals", {}, token),
  alerts: (token: string, unreadOnly = false, limit = 100) =>
    request<{ unread: number; alerts: AlertOut[] }>(
      `/alerts?unread_only=${unreadOnly}&limit=${limit}`,
      {},
      token,
    ),
  readAlert: (token: string, id: number) =>
    request<AlertOut>(`/alerts/${id}/read`, { method: "POST" }, token),
  readAllAlerts: (token: string) =>
    request<{ marked: number }>("/alerts/read-all", { method: "POST" }, token),
  alertChannels: (token: string) => request<AlertChannels>("/alerts/channels", {}, token),
  monitoringOverview: (token: string) => request<MonitoringOverview>("/monitoring/overview", {}, token),
  monitoringRuns: (token: string, modelId?: number) =>
    request<MonitorRun[]>(`/monitoring/runs?limit=60${modelId ? `&model_id=${modelId}` : ""}`, {}, token),
  runMonitoring: (token: string) => request<MonitorRun[]>("/monitoring/run", { method: "POST" }, token),
  providers: (token: string) => request<ProviderInfo[]>("/data/providers", {}, token),
  liveStatus: (token: string) => request<LiveStatus>("/live/status", {}, token),
  nlpStatus: (token: string) => request<Record<string, string>>("/nlp/status", {}, token),
  narratorStatus: (token: string) =>
    request<{ available: boolean; reason?: string; provider?: string; model?: string | null }>("/narrator/status", {}, token),
  macroSummary: (token: string) => request<MacroRow[]>("/macro", {}, token),
  macroIngest: (token: string) => request<Record<string, string>>("/macro/ingest", { method: "POST" }, token),
  macroManual: (token: string, body: MacroManualIn) =>
    request<{ id: number; series: string; version: number }>("/macro/manual", json(body), token),
  modelEstimate: (token: string, ticker: string) =>
    request<ModelEstimate>(`/models/estimate/${encodeURIComponent(ticker)}`, {}, token),
  analysisHistory: (token: string, ticker: string) =>
    request<ReportHistoryRow[]>(`/analysis/${encodeURIComponent(ticker)}/history`, {}, token),
  importCsv: (token: string, ticker: string, file: File, source: string, basis: Basis) => {
    const form = new FormData();
    form.set("file", file);
    form.set("source", source);
    form.set("basis", basis);
    return request<IngestionRun>(`/stocks/${encodeURIComponent(ticker)}/import-csv`, { method: "POST", body: form }, token);
  },
  tradeCosts: (token: string, body: { ticker: string; quantity: number; entry_price: string; horizon_days: number; quoted_spread_bps?: number | null }) =>
    request<CostResult>("/trade/costs", json(body), token),
  monitoringRun: (token: string, id: number) => request<MonitorRun>(`/monitoring/runs/${id}`, {}, token),
  riskAgent: (token: string, ticker: string) =>
    request<AgentOutput>(`/risk-agent/${encodeURIComponent(ticker)}`, {}, token),
  portfolios: (token: string) => request<PortfolioSummary[]>("/portfolios", {}, token),
  createPortfolio: (token: string, name: string, cash: string, kind: "model" | "paper" = "model") =>
    request<PortfolioSummary>("/portfolios", json({ name, cash, kind }), token),
  setPosition: (token: string, id: number, ticker: string, quantity: number, avg_cost: string) =>
    request<PortfolioSummary>(
      `/portfolios/${id}/positions`,
      { ...json({ ticker, quantity, avg_cost }), method: "PUT" },
      token,
    ),
  setCash: (token: string, id: number, cash: string) =>
    request<PortfolioSummary>(`/portfolios/${id}/cash`, { ...json({ cash }), method: "PUT" }, token),
  portfolioAnalysis: (token: string, id: number) =>
    request<PortfolioAnalysis>(`/portfolios/${id}/analysis`, {}, token),
  portfolioFit: (token: string, id: number, ticker: string, weight: number) =>
    request<PortfolioFit>(
      `/portfolio-agent/${id}/${encodeURIComponent(ticker)}?weight=${weight}`,
      {},
      token,
    ),
};
