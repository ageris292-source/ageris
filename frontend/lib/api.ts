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
    let detail = res.statusText;
    try {
      const body = await res.json();
      detail = typeof body.detail === "string" ? body.detail : JSON.stringify(body.detail);
    } catch {
      /* non-JSON error body */
    }
    throw new ApiError(res.status, detail);
  }
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

export const api = {
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
  riskAgent: (token: string, ticker: string) =>
    request<AgentOutput>(`/risk-agent/${encodeURIComponent(ticker)}`, {}, token),
  portfolios: (token: string) => request<PortfolioSummary[]>("/portfolios", {}, token),
  createPortfolio: (token: string, name: string, cash: string) =>
    request<PortfolioSummary>("/portfolios", json({ name, cash, kind: "model" }), token),
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
