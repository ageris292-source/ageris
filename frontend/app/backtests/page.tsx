"use client";

import { useCallback, useEffect, useState } from "react";
import {
  CartesianGrid,
  Legend,
  Line,
  LineChart,
  ResponsiveContainer,
  Scatter,
  ScatterChart,
  Tooltip,
  XAxis,
  YAxis,
  ReferenceLine,
} from "recharts";
import { Login } from "@/components/Login";
import { Nav } from "@/components/Nav";
import { useSession } from "@/components/useSession";
import { api, ApiError, type BacktestDetail, type BacktestSummary, type ModelRow } from "@/lib/api";

const STRAT = "#3987e5";
const BENCH = "#d95926";
const GRID = "#263039";
const MUTED = "#8b98a5";
const pct = (v: number | null | undefined, d = 1) => (v === null || v === undefined ? "—" : `${(v * 100).toFixed(d)}%`);
const num = (v: number | null | undefined, d = 3) => (v === null || v === undefined ? "—" : v.toFixed(d));

function Panel({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section className="mb-4 rounded-lg border border-line bg-panel p-5">
      <h3 className="mb-3 text-xs font-semibold uppercase tracking-wider text-muted">{title}</h3>
      {children}
    </section>
  );
}

function Stat({ label, value, hint }: { label: string; value: string; hint?: string }) {
  return (
    <div>
      <div className="text-xs text-muted">{label}</div>
      <div className="font-mono text-lg">{value}</div>
      {hint && <div className="text-[10px] text-muted">{hint}</div>}
    </div>
  );
}

export default function BacktestsPage() {
  const { token, ready, me, health, signIn, signOut, guard } = useSession();
  const [runs, setRuns] = useState<BacktestSummary[]>([]);
  const [models, setModels] = useState<ModelRow[]>([]);
  const [sel, setSel] = useState<BacktestDetail | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const isAdmin = me?.role === "admin";

  const load = useCallback(async () => {
    try {
      const [r, m] = await Promise.all([guard((t) => api.backtests(t)), guard((t) => api.models(t))]);
      if (r) setRuns(r);
      if (m) setModels(m);
      if (r && r[0]) {
        const d = await guard((t) => api.backtest(t, r[0].id));
        if (d) setSel((s) => s ?? d);
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : "Request failed");
    }
  }, [guard]);

  useEffect(() => {
    if (token) void load();
  }, [token, load]);

  async function run() {
    setBusy(true);
    setError(null);
    try {
      const d = await guard((t) => api.runBacktest(t, 20));
      if (d) setSel(d);
      await load();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Backtest failed");
    } finally {
      setBusy(false);
    }
  }

  async function open(id: number) {
    const d = await guard((t) => api.backtest(t, id));
    if (d) setSel(d);
  }

  async function setModel(id: number, action: "activate" | "retire") {
    try {
      await guard((t) => api.setModel(t, id, action));
      await load();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Request failed");
    }
  }

  if (!ready) return null;
  if (!token) return <Login onToken={signIn} />;
  const m = sel?.metrics;
  const sum = sel?.simulation?.summary;

  return (
    <main className="mx-auto max-w-5xl px-4 py-8">
      <Nav mode={health?.system_mode} email={me?.email} role={me?.role} onSignOut={signOut} />
      <div className="mb-6 flex flex-wrap items-end justify-between gap-3">
        <div>
          <h2 className="mb-1 text-2xl font-semibold">Backtests &amp; model</h2>
          <p className="text-sm text-muted">
            Walk-forward LightGBM with purged folds and isotonic calibration. Past results do not predict future results.
          </p>
        </div>
        {isAdmin && (
          <button className="rounded bg-ink px-3 py-1.5 text-sm text-surface disabled:opacity-40" onClick={run} disabled={busy}>
            {busy ? "Running walk-forward…" : "Run backtest (20-day horizon)"}
          </button>
        )}
      </div>
      {error && <p className="mb-4 text-sm text-fail">{error}</p>}

      {sel && (
        <>
          <div className="mb-4 rounded border border-unknown/50 bg-unknown/10 px-4 py-2 text-sm text-unknown">
            <span aria-hidden>⚠ </span>Survivorship bias: <b>{sel.survivorship_bias}</b>. {sel.warnings.filter((w) => !w.startsWith("Universe")).join(" · ")}
          </div>
          {sel.status === "failed" && <p className="mb-4 text-sm text-fail">Run #{sel.id} failed: {sel.error}</p>}
          {m && sum && (
            <>
              <Panel title={`Run #${sel.id} · out of sample ${m.oos_start} → ${m.oos_end} · ${sel.universe.length} stocks`}>
                <div className="grid grid-cols-2 gap-4 sm:grid-cols-4">
                  <Stat label="AUC, P(profit)" value={num(m.profit.auc)} hint="0.5 = no skill" />
                  <Stat label="Calibration error" value={num(m.profit.ece)} hint="gate max 0.050" />
                  <Stat label="AUC, P(outperform)" value={num(m.outperform.auc)} />
                  <Stat label="Folds" value={`${m.folds_trained} (+${m.folds_skipped} skipped)`} hint={`${m.oos_rows} OOS rows`} />
                  <Stat label="Strategy total" value={pct(sum.total_return)} hint={`CAGR ${pct(sum.cagr)}`} />
                  <Stat label="NIFTY 50 total" value={pct(sum.benchmark_total_return)} hint={`CAGR ${pct(sum.benchmark_cagr)}`} />
                  <Stat label="Max drawdown" value={pct(sum.max_drawdown)} hint={`benchmark ${pct(sum.benchmark_max_drawdown)}`} />
                  <Stat label="Trades / no-trade periods" value={`${sum.trades} / ${sum.no_trade_periods}`} hint={`win rate ${pct(sum.win_rate, 0)}`} />
                </div>
              </Panel>
              <div className="grid gap-4 md:grid-cols-2">
                <Panel title="Equity: strategy vs NIFTY 50 (after costs)">
                  <div className="h-64">
                    <ResponsiveContainer>
                      <LineChart data={sel.simulation!.periods} margin={{ top: 5, right: 10, left: 0, bottom: 0 }}>
                        <CartesianGrid stroke={GRID} strokeDasharray="3 3" />
                        <XAxis dataKey="date" tick={{ fill: MUTED, fontSize: 10 }} minTickGap={30} />
                        <YAxis tick={{ fill: MUTED, fontSize: 10 }} domain={["auto", "auto"]} tickFormatter={(v: number) => v.toFixed(2)} />
                        <Tooltip contentStyle={{ background: "#161c23", border: `1px solid ${GRID}` }} formatter={(v: number) => v.toFixed(3)} />
                        <Legend wrapperStyle={{ fontSize: 11 }} />
                        <Line type="stepAfter" dataKey="equity" name="Strategy" stroke={STRAT} dot={false} strokeWidth={2} />
                        <Line type="stepAfter" dataKey="benchmark_equity" name="NIFTY 50" stroke={BENCH} dot={false} strokeDasharray="5 3" />
                      </LineChart>
                    </ResponsiveContainer>
                  </div>
                </Panel>
                <Panel title="Calibration: predicted vs observed P(profit)">
                  <div className="h-64">
                    <ResponsiveContainer>
                      <ScatterChart margin={{ top: 5, right: 10, left: 0, bottom: 0 }}>
                        <CartesianGrid stroke={GRID} strokeDasharray="3 3" />
                        <XAxis type="number" dataKey="mean_predicted" domain={[0, 1]} name="predicted" tick={{ fill: MUTED, fontSize: 10 }} />
                        <YAxis type="number" dataKey="observed_rate" domain={[0, 1]} name="observed" tick={{ fill: MUTED, fontSize: 10 }} />
                        <ReferenceLine segment={[{ x: 0, y: 0 }, { x: 1, y: 1 }]} stroke={MUTED} strokeDasharray="4 4" />
                        <Tooltip contentStyle={{ background: "#161c23", border: `1px solid ${GRID}` }} />
                        <Scatter data={m.calibration_curve_profit} fill={STRAT} name="bins" />
                      </ScatterChart>
                    </ResponsiveContainer>
                  </div>
                  <p className="text-xs text-muted">Points on the dashed diagonal = well calibrated.</p>
                </Panel>
              </div>
              <Panel title="Walk-forward folds">
                <div className="overflow-x-auto">
                  <table className="w-full font-mono text-xs">
                    <thead className="text-left text-muted">
                      <tr>{["Fold", "Test window", "Train rows", "Train labels end", "AUC", "ECE", "Note"].map((h) => <th key={h} className="py-1 pr-3 font-normal">{h}</th>)}</tr>
                    </thead>
                    <tbody>
                      {sel.folds?.map((f) => (
                        <tr key={f.fold} className="border-t border-line">
                          <td className="py-1 pr-3">{f.fold}</td>
                          <td className="py-1 pr-3">{f.test_start} → {f.test_end}</td>
                          <td className="py-1 pr-3">{String(f.train_rows)}</td>
                          <td className="py-1 pr-3">{String(f.train_last_label_end ?? "—")}</td>
                          <td className="py-1 pr-3">{num(f.profit?.auc)}</td>
                          <td className="py-1 pr-3">{num(f.profit?.ece)}</td>
                          <td className="py-1 pr-3 text-muted">{f.skipped ? `skipped: ${f.reason}` : ""}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </Panel>
              <Panel title="Reproducibility">
                <dl className="grid grid-cols-[auto_1fr] gap-x-4 gap-y-1 text-xs">
                  <dt className="text-muted">Data hash</dt><dd className="font-mono break-all">{sel.data_hash}</dd>
                  <dt className="text-muted">Config</dt><dd className="font-mono break-all">{sel.config_fingerprint}</dd>
                  <dt className="text-muted">Seed</dt><dd className="font-mono">{String(sel.reproducibility.seed)}</dd>
                  <dt className="text-muted">Libraries</dt><dd className="font-mono">{Object.entries(sel.reproducibility.libraries ?? {}).map(([k, v]) => `${k} ${v}`).join(" · ")}</dd>
                  <dt className="text-muted">Universe</dt><dd className="font-mono">{sel.universe.join(" ")}</dd>
                </dl>
              </Panel>
            </>
          )}
        </>
      )}

      <div className="grid gap-4 md:grid-cols-2">
        <Panel title="Runs">
          <ul className="space-y-1 text-xs">
            {runs.map((r) => (
              <li key={r.id} className="flex justify-between gap-2 border-t border-line pt-1 first:border-0">
                <button className="font-mono underline" onClick={() => open(r.id)}>#{r.id} h{r.horizon} · {r.universe_size} stocks</button>
                <span className={r.status === "failed" ? "text-fail" : ""}>
                  {r.status} · AUC {num(r.headline.auc_profit)} · ECE {num(r.headline.ece_profit)}
                </span>
              </li>
            ))}
            {runs.length === 0 && <li className="text-muted">No backtests yet.</li>}
          </ul>
        </Panel>
        <Panel title="Model registry">
          <ul className="space-y-2 text-xs">
            {models.map((mo) => (
              <li key={mo.id} className="border-t border-line pt-2 first:border-0">
                <div className="flex flex-wrap justify-between gap-2">
                  <span className="font-mono">{mo.name}</span>
                  <span className={mo.status === "active" ? "text-pass" : "text-muted"}>{mo.status}</span>
                </div>
                <div className="text-muted">
                  ECE {mo.calibration_error.toFixed(3)} {mo.passes_calibration_gate ? "✓" : "✕ fails gate 12"} · folds {mo.oos_periods} {mo.passes_oos_gate ? "✓" : "✕ fails gate 13"} · AUC {num(mo.auc)}
                </div>
                {isAdmin && mo.status !== "retired" && (
                  <div className="mt-1 flex gap-2">
                    {mo.status === "candidate" && <button className="underline" onClick={() => setModel(mo.id, "activate")}>Activate</button>}
                    <button className="underline" onClick={() => setModel(mo.id, "retire")}>Retire</button>
                  </div>
                )}
              </li>
            ))}
            {models.length === 0 && <li className="text-muted">No models yet.</li>}
          </ul>
          <p className="mt-3 text-xs text-muted">Activating a model lets the Trade Risk Engine query it. The engine still rejects any estimate that fails the calibration or out-of-sample gates.</p>
        </Panel>
      </div>
    </main>
  );
}
