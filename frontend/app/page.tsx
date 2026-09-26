"use client";

import { useCallback, useEffect, useState } from "react";
import { api, ApiError, type GateStatus, type Health, type Me, type Regime, type RiskStatus } from "@/lib/api";
import { readToken, writeToken } from "@/lib/auth";
import { Login } from "@/components/Login";
import { Nav } from "@/components/Nav";

const statusColor: Record<GateStatus, string> = {
  PASS: "text-pass",
  FAIL: "text-fail",
  UNKNOWN: "text-unknown",
};

function Panel({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section className="rounded-lg border border-line bg-panel p-5">
      <h2 className="mb-4 text-xs font-semibold uppercase tracking-wider text-muted">{title}</h2>
      {children}
    </section>
  );
}

function KillSwitchControl({
  token, me, status, onChange,
}: { token: string; me: Me; status: RiskStatus; onChange: () => void }) {
  const [reason, setReason] = useState("");
  const [error, setError] = useState<string | null>(null);
  const active = status.kill_switch.active;
  const canResume = me.role === "admin";

  async function toggle(nextActive: boolean) {
    setError(null);
    try {
      await api.setKillSwitch(token, nextActive, reason);
      setReason("");
      onChange();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Request failed");
    }
  }

  return (
    <Panel title="Kill switch">
      <p className={`mb-1 text-lg font-semibold ${active ? "text-fail" : "text-pass"}`}>
        {active ? "ACTIVE — all trading halted" : "Inactive"}
      </p>
      <p className="mb-4 text-sm text-muted">{status.kill_switch.reason}</p>
      <input
        className="mb-3 w-full rounded border border-line bg-surface px-3 py-2 text-sm"
        placeholder="Reason (required, min 5 chars)"
        value={reason} onChange={(e) => setReason(e.target.value)}
      />
      <div className="flex gap-2">
        <button
          className="rounded bg-fail px-3 py-2 text-sm font-medium text-white disabled:opacity-40"
          disabled={reason.trim().length < 5}
          onClick={() => toggle(true)}
        >
          Halt trading
        </button>
        {active && canResume && (
          <button
            className="rounded border border-line px-3 py-2 text-sm disabled:opacity-40"
            disabled={reason.trim().length < 5}
            onClick={() => toggle(false)}
          >
            Resume (admin)
          </button>
        )}
      </div>
      {error && <p className="mt-3 text-sm text-fail">{error}</p>}
      <p className="mt-3 text-xs text-muted">
        Resuming only clears the halt. It does not enable live trading.
      </p>
    </Panel>
  );
}

export default function Dashboard() {
  const [token, setToken] = useState<string | null>(null);
  const [ready, setReady] = useState(false);
  const [health, setHealth] = useState<Health | null>(null);
  const [me, setMe] = useState<Me | null>(null);
  const [risk, setRisk] = useState<RiskStatus | null>(null);
  const [regime, setRegime] = useState<Regime | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    setToken(readToken());
    setReady(true);
  }, []);

  const signOut = useCallback(() => {
    writeToken(null);
    setToken(null);
    setMe(null);
    setRisk(null);
  }, []);

  const load = useCallback(async () => {
    setError(null);
    try {
      setHealth(await api.health());
    } catch {
      setHealth(null);
      setError("Cannot reach the Aegis API");
      return;
    }
    if (!token) return;
    try {
      const [m, r] = await Promise.all([api.me(token), api.riskStatus(token)]);
      setMe(m);
      setRisk(r);
      api.regime(token).then(setRegime).catch(() => setRegime(null));
    } catch (err) {
      if (err instanceof ApiError && err.status === 401) signOut();
      else setError(err instanceof Error ? err.message : "Request failed");
    }
  }, [token, signOut]);

  useEffect(() => {
    if (!ready) return;
    void load();
    const id = setInterval(load, 15_000);
    return () => clearInterval(id);
  }, [ready, load]);

  if (!ready) return null;
  if (!token) {
    return (
      <Login
        onToken={(t) => {
          writeToken(t);
          setToken(t);
        }}
      />
    );
  }

  return (
    <main className="mx-auto max-w-5xl px-4 py-8">
      {health?.demo_data && (
        <div className="mb-6 rounded border border-unknown bg-unknown/10 px-4 py-2 text-center text-sm font-semibold text-unknown">
          DEMO DATA — NOT FOR TRADING
        </div>
      )}
      <Nav mode={health?.system_mode} email={me?.email} role={me?.role} onSignOut={signOut} />

      {error && <p className="mb-6 text-sm text-fail">{error}</p>}

      <div className="grid gap-4 md:grid-cols-2">
        <Panel title="Execution readiness">
          {risk ? (
            <>
              <div className="mb-4 grid grid-cols-2 gap-3 text-sm">
                <div>
                  <div className="text-muted">Live orders</div>
                  <div className={risk.live_orders_permitted ? "text-pass" : "text-fail"}>
                    {risk.live_orders_permitted ? "Permitted" : "Blocked"}
                  </div>
                </div>
                <div>
                  <div className="text-muted">Paper orders</div>
                  <div className={risk.paper_orders_permitted ? "text-pass" : "text-fail"}>
                    {risk.paper_orders_permitted ? "Permitted" : "Blocked"}
                  </div>
                </div>
              </div>
              <table className="w-full text-sm">
                <tbody>
                  {risk.checks.map((c) => (
                    <tr key={c.name} className="border-t border-line">
                      <td className="py-1.5 pr-3 font-mono text-xs">{c.name}</td>
                      <td className={`py-1.5 pr-3 font-mono text-xs ${statusColor[c.status]}`}>
                        {c.status}
                      </td>
                      <td className="py-1.5 text-xs text-muted">{c.reason}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </>
          ) : (
            <p className="text-sm text-muted">Loading…</p>
          )}
        </Panel>

        {risk && me && <KillSwitchControl token={token} me={me} status={risk} onChange={load} />}

        <Panel title="Market regime">
          {regime ? (
            <>
              <p
                className={`mb-1 text-lg font-semibold ${
                  !regime.known ? "text-unknown" : regime.risk === "risk_off" ? "text-fail" : regime.risk === "risk_on" ? "text-pass" : ""
                }`}
              >
                {regime.label.replaceAll("_", " ")}
              </p>
              <p className="mb-3 text-sm text-muted">
                Trend {regime.trend} · volatility {regime.volatility} · {regime.risk.replace("_", "-")}
              </p>
              <dl className="grid grid-cols-2 gap-y-1 text-xs">
                {Object.entries(regime.evidence).map(([k, v]) => (
                  <div key={k} className="contents">
                    <dt className="text-muted">{k.replaceAll("_", " ")}</dt>
                    <dd className="font-mono">{v === null ? "—" : v.toFixed(4)}</dd>
                  </div>
                ))}
              </dl>
              {!regime.known && (
                <p className="mt-2 text-xs text-unknown">Regime unknown: macro series not ingested yet (admin: POST /macro/ingest).</p>
              )}
            </>
          ) : (
            <p className="text-sm text-muted">Loading…</p>
          )}
        </Panel>

        <Panel title="Infrastructure">
          {health ? (
            <ul className="space-y-1 text-sm">
              {health.components.map((c) => (
                <li key={c.name} className="flex justify-between">
                  <span>{c.name}</span>
                  <span className={c.healthy ? "text-pass" : "text-fail"}>
                    {c.healthy ? "healthy" : "unavailable"}
                  </span>
                </li>
              ))}
              <li className="flex justify-between text-muted">
                <span>api version</span>
                <span className="font-mono">{health.version}</span>
              </li>
            </ul>
          ) : (
            <p className="text-sm text-fail">API unreachable</p>
          )}
        </Panel>

        <Panel title="Configuration">
          {risk && (
            <dl className="space-y-1 text-sm">
              <div className="flex justify-between">
                <dt className="text-muted">version</dt>
                <dd className="font-mono">{risk.config_version}</dd>
              </div>
              <div className="flex justify-between gap-4">
                <dt className="text-muted">fingerprint</dt>
                <dd className="truncate font-mono text-xs">{risk.config_fingerprint}</dd>
              </div>
            </dl>
          )}
          <p className="mt-4 text-xs text-muted">
            Market data lives under Stocks. Agent analyses are on each stock page; rankings arrive in a later
            phase. Nothing on this page is a trade signal.
          </p>
        </Panel>
      </div>

      {risk && <p className="mt-8 text-center text-xs text-muted">{risk.disclaimer}</p>}
    </main>
  );
}
