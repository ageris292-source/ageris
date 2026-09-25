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
};
