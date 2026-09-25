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
};
