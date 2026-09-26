"use client";

import { useCallback, useEffect, useState } from "react";
import {
  CartesianGrid,
  ReferenceLine,
  ResponsiveContainer,
  Scatter,
  ScatterChart,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { Login } from "@/components/Login";
import { Nav } from "@/components/Nav";
import { useSession } from "@/components/useSession";
import { api, type MonitoringOverview, type MonitorRun, type MonitorStatus } from "@/lib/api";

const GRID = "#263039";
const MUTED = "#8b98a5";
const n3 = (v: number | null | undefined) => (v === null || v === undefined ? "—" : v.toFixed(3));
const ist = (iso: string) => new Date(iso).toLocaleString("en-IN", { timeZone: "Asia/Kolkata" });

// Status is never color alone: icon + word + color.
const BADGE: Record<MonitorStatus, { cls: string; icon: string }> = {
  PASS: { cls: "border-pass/40 text-pass", icon: "✓" },
  WARN: { cls: "border-unknown/40 text-unknown", icon: "!" },
  UNKNOWN: { cls: "border-unknown/40 text-unknown", icon: "?" },
  FAIL: { cls: "border-fail/40 text-fail", icon: "✕" },
};

function Badge({ s }: { s: MonitorStatus | undefined | null }) {
  if (!s) return <span className="text-xs text-muted">not checked</span>;
  const b = BADGE[s];
  return (
    <span className={`inline-flex items-center gap-1 rounded border px-1.5 py-0.5 text-xs ${b.cls}`}>
      <span aria-hidden>{b.icon}</span>
      {s}
    </span>
  );
}

function Panel({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section className="mb-4 rounded-lg border border-line bg-panel p-5">
      <h3 className="mb-3 text-xs font-semibold uppercase tracking-wider text-muted">{title}</h3>
      {children}
    </section>
  );
}

function RunDetail({ r }: { r: MonitorRun }) {
  const d = r.drift;
  const c = r.calibration;
  return (
    <div className="grid gap-4 md:grid-cols-2">
      <div>
        <div className="mb-2 flex items-center gap-2 text-sm">
          Feature drift <Badge s={d?.status} />
          <span className="text-xs text-muted">{d?.samples ?? 0} current rows</span>
        </div>
        <div className="overflow-x-auto">
        <table className="w-full font-mono text-xs">
          <thead className="text-left text-muted">
            <tr>{["Feature", "PSI", "Warn at", "Fail at", ""].map((h) => <th key={h} className="py-1 pr-3 font-normal">{h}</th>)}</tr>
          </thead>
          <tbody>
            {(d?.features ?? []).map((f) => (
              <tr key={f.feature} className="border-t border-line">
                <td className="py-1 pr-3">{f.feature}</td>
                <td className="py-1 pr-3">{n3(f.psi)}</td>
                <td className="py-1 pr-3 text-muted">{n3(f.warn_at)}</td>
                <td className="py-1 pr-3 text-muted">{n3(f.fail_at)}</td>
                <td className="py-1"><Badge s={f.status} /></td>
              </tr>
            ))}
            {(d?.features ?? []).length === 0 && <tr><td colSpan={5} className="py-2 font-sans text-muted">{d?.reasons.join("; ")}</td></tr>}
          </tbody>
        </table>
        </div>
        <p className="mt-2 text-xs text-muted">
          Thresholds come from the model&apos;s own training history (95th/99th percentile of PSI for windows of the same
          length), floored by the configured absolute levels.
        </p>
      </div>
      <div>
        <div className="mb-2 flex items-center gap-2 text-sm">
          Calibration on realised outcomes <Badge s={c?.status} />
        </div>
        <div className="mb-3 grid grid-cols-3 gap-3 text-xs">
          {[
            ["Live ECE", n3(c?.live_ece)],
            ["Backtest ECE", n3(c?.backtest_ece)],
            ["Decay", c?.decay === undefined ? "—" : (c.decay >= 0 ? "+" : "") + c.decay.toFixed(3)],
            ["Evaluated", String(c?.evaluated ?? 0)],
            ["Matured", String(c?.matured ?? 0)],
            ["Pending", String(c?.pending ?? 0)],
          ].map(([k, v]) => (
            <div key={k}><div className="text-muted">{k}</div><div className="font-mono text-base">{v}</div></div>
          ))}
        </div>
        {c?.curve && c.curve.length > 0 ? (
          <div className="h-52">
            <ResponsiveContainer>
              <ScatterChart margin={{ left: 0, right: 12, top: 8, bottom: 4 }}>
                <CartesianGrid stroke={GRID} strokeDasharray="3 3" />
                <XAxis type="number" dataKey="mean_predicted" name="Predicted" domain={[0, 1]} tick={{ fill: MUTED, fontSize: 10 }} />
                <YAxis type="number" dataKey="observed_rate" name="Observed" domain={[0, 1]} tick={{ fill: MUTED, fontSize: 10 }} />
                <ReferenceLine segment={[{ x: 0, y: 0 }, { x: 1, y: 1 }]} stroke={MUTED} strokeDasharray="4 4" />
                <Tooltip contentStyle={{ background: "#161c23", border: `1px solid ${GRID}` }} />
                <Scatter data={c.curve} fill="#3987e5" />
              </ScatterChart>
            </ResponsiveContainer>
          </div>
        ) : (
          <p className="text-xs text-muted">{c?.reasons.join("; ") || "No matured predictions yet."}</p>
        )}
      </div>
    </div>
  );
}

export default function MonitoringPage() {
  const { token, ready, me, health, signIn, signOut, guard } = useSession();
  const [ov, setOv] = useState<MonitoringOverview | null>(null);
  const [runs, setRuns] = useState<MonitorRun[]>([]);
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<{ tone: "ok" | "fail"; text: string } | null>(null);

  const load = useCallback(async () => {
    try {
      const [o, r] = await Promise.all([guard((t) => api.monitoringOverview(t)), guard((t) => api.monitoringRuns(t))]);
      if (o) setOv(o);
      if (r) setRuns(r);
    } catch (err) {
      setMsg({ tone: "fail", text: err instanceof Error ? err.message : "Request failed" });
    }
  }, [guard]);

  useEffect(() => {
    if (token && me?.role === "admin") void load();
  }, [token, me, load]);

  async function runNow() {
    setBusy(true);
    setMsg(null);
    try {
      const r = await guard((t) => api.runMonitoring(t));
      if (r) {
        setMsg({
          tone: r.some((x) => x.status === "FAIL") ? "fail" : "ok",
          text: r.length ? r.map((x) => `${x.model_name}: ${x.status}${x.action === "retired" ? " → retired" : ""}`).join(" · ") : "No active model to monitor.",
        });
        window.dispatchEvent(new Event("aegis:alerts-changed"));
      }
      await load();
    } catch (err) {
      setMsg({ tone: "fail", text: err instanceof Error ? err.message : "Monitoring failed" });
    } finally {
      setBusy(false);
    }
  }

  if (!ready) return null;
  if (!token) return <Login onToken={signIn} />;

  return (
    <main className="mx-auto max-w-6xl px-4 py-8">
      <Nav mode={health?.system_mode} email={me?.email} role={me?.role} onSignOut={signOut} />
      <div className="mb-6 flex flex-wrap items-end justify-between gap-3">
        <div>
          <h2 className="mb-1 text-2xl font-semibold">Model monitoring</h2>
          <p className="max-w-3xl text-sm text-muted">
            Each active model is checked daily against its own training data (feature drift) and against the realised
            outcomes of its own logged predictions (calibration decay). A FAIL retires the model and raises a critical
            alert; the engine then rejects every entry for that horizon until an admin activates a healthy model.
          </p>
        </div>
        {me?.role === "admin" && (
          <button className="rounded bg-ink px-3 py-1.5 text-sm text-surface disabled:opacity-40" disabled={busy} onClick={runNow}>
            {busy ? "Checking…" : "Run monitoring now"}
          </button>
        )}
      </div>
      {me && me.role !== "admin" && <p className="text-sm text-muted">Model monitoring is available to admins only.</p>}
      {msg && <p className={`mb-4 text-sm ${msg.tone === "ok" ? "text-pass" : "text-fail"}`}>{msg.text}</p>}

      {ov && ov.models.length === 0 && (
        <p className="text-sm text-muted">No active or monitored model. Activate a model on the Backtests page.</p>
      )}
      {ov?.models.map((m) => (
        <Panel key={m.model_id} title={`${m.name} · horizon ${m.horizon} · ${m.status}`}>
          <div className="mb-4 flex flex-wrap items-center gap-3 text-sm">
            <Badge s={m.latest?.status} />
            {m.latest?.action === "retired" && <span className="text-fail">✕ retired automatically</span>}
            {!m.monitorable && <span className="text-fail">✕ no training reference: cannot be monitored</span>}
            <span className="text-xs text-muted">
              {m.predictions} predictions logged · valid from {ist(m.valid_from)}
              {m.latest && ` · last check ${ist(m.latest.as_of)}`}
            </span>
          </div>
          {m.latest && m.latest.reasons.length > 0 && (
            <ul className="mb-4 list-inside list-disc text-xs text-unknown">
              {m.latest.reasons.map((r) => <li key={r}>{r}</li>)}
            </ul>
          )}
          {m.latest && <RunDetail r={m.latest} />}
        </Panel>
      ))}

      {runs.length > 0 && (
        <Panel title="History">
          <div className="overflow-x-auto">
          <table className="w-full text-xs">
            <thead className="text-left text-muted">
              <tr>{["#", "As of", "Model", "Status", "Drift", "Calibration", "Max PSI", "Live ECE", "Action"].map((h) => <th key={h} className="py-1 pr-3 font-normal">{h}</th>)}</tr>
            </thead>
            <tbody>
              {runs.map((r) => (
                <tr key={r.id} className="border-t border-line">
                  <td className="py-1 pr-3 font-mono">{r.id}</td>
                  <td className="py-1 pr-3">{ist(r.as_of)}</td>
                  <td className="py-1 pr-3 font-mono">{r.model_name}</td>
                  <td className="py-1 pr-3"><Badge s={r.status} /></td>
                  <td className="py-1 pr-3"><Badge s={r.drift_status} /></td>
                  <td className="py-1 pr-3"><Badge s={r.calibration_status} /></td>
                  <td className="py-1 pr-3 font-mono">{n3(r.max_psi)}</td>
                  <td className="py-1 pr-3 font-mono">{n3(r.live_ece)}</td>
                  <td className={`py-1 pr-3 ${r.action === "retired" ? "text-fail" : "text-muted"}`}>{r.action}</td>
                </tr>
              ))}
            </tbody>
          </table>
          </div>
        </Panel>
      )}
    </main>
  );
}
