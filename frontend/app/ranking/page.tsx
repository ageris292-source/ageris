"use client";

import { useCallback, useEffect, useState } from "react";
import { Bar, BarChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { Login } from "@/components/Login";
import { Nav } from "@/components/Nav";
import { useSession } from "@/components/useSession";
import { api, ApiError, type Counterfactuals, type RankingRun } from "@/lib/api";

const GRID = "#263039";
const MUTED = "#8b98a5";
const pct = (v: number | null | undefined, d = 1) =>
  v === null || v === undefined ? "—" : `${(v * 100).toFixed(d)}%`;
const inr = (v: number | undefined) =>
  v === undefined ? "—" : `₹${v.toLocaleString("en-IN", { maximumFractionDigits: 2 })}`;
const ist = (iso: string) => new Date(iso).toLocaleString("en-IN", { timeZone: "Asia/Kolkata" });

function Panel({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section className="mb-4 rounded-lg border border-line bg-panel p-5">
      <h3 className="mb-3 text-xs font-semibold uppercase tracking-wider text-muted">{title}</h3>
      {children}
    </section>
  );
}

export default function RankingPage() {
  const { token, ready, me, health, signIn, signOut, guard } = useSession();
  const [run, setRun] = useState<RankingRun | null>(null);
  const [none, setNone] = useState(false);
  const [history, setHistory] = useState<RankingRun[]>([]);
  const [cf, setCf] = useState<Counterfactuals | null>(null);
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<string | null>(null);
  const isAdmin = me?.role === "admin";

  const load = useCallback(async () => {
    try {
      const [h, c] = await Promise.all([
        guard((t) => api.rankingHistory(t)),
        guard((t) => api.counterfactuals(t)),
      ]);
      if (h) setHistory(h);
      if (c) setCf(c);
      const latest = await guard((t) => api.latestRanking(t));
      if (latest) setRun(latest);
    } catch (err) {
      if (err instanceof ApiError && err.status === 404) setNone(true);
      else setMsg(err instanceof Error ? err.message : "Request failed");
    }
  }, [guard]);

  useEffect(() => {
    if (token) void load();
  }, [token, load]);

  async function runNow() {
    setBusy(true);
    setMsg(null);
    try {
      const r = await guard((t) => api.runRanking(t));
      if (r) {
        setRun(r);
        setNone(false);
        window.dispatchEvent(new Event("aegis:alerts-changed"));
      }
      await load();
    } catch (err) {
      setMsg(err instanceof Error ? err.message : "Ranking failed");
    } finally {
      setBusy(false);
    }
  }

  if (!ready) return null;
  if (!token) return <Login onToken={signIn} />;
  const gates = Object.entries(run?.gate_failure_counts ?? {}).map(([gate, n]) => ({ gate, n }));
  const qualified = run?.qualified ?? 0;

  return (
    <main className="mx-auto max-w-6xl px-4 py-8">
      <Nav mode={health?.system_mode} email={me?.email} role={me?.role} onSignOut={signOut} />
      <div className="mb-6 flex flex-wrap items-end justify-between gap-3">
        <div>
          <h2 className="mb-1 text-2xl font-semibold">Daily ranking</h2>
          <p className="max-w-3xl text-sm text-muted">
            Every stock gets the same standardised candidate trade (entry at the last close, stop from ATR, fixed
            reward multiple), evaluated by the 24-gate Trade Risk Engine. Qualifying is not an order: it still needs
            a live quote, a proposal and human approval.
          </p>
        </div>
        {isAdmin && (
          <button className="rounded bg-ink px-3 py-1.5 text-sm text-surface disabled:opacity-40" disabled={busy} onClick={runNow}>
            {busy ? "Ranking…" : "Run ranking now"}
          </button>
        )}
      </div>
      {msg && <p className="mb-4 text-sm text-fail">{msg}</p>}
      {none && !run && <p className="text-sm text-muted">No ranking yet. {isAdmin ? "Run one now, or wait for the daily job." : "It runs daily after the close."}</p>}

      {run && (
        <>
          <section
            className={`mb-4 rounded-lg border p-5 ${qualified ? "border-pass/50 bg-pass/10" : "border-line bg-panel"}`}
          >
            <div className={`text-xl font-semibold ${qualified ? "text-pass" : ""}`}>
              <span aria-hidden>{qualified ? "✓ " : "— "}</span>
              {run.headline}
            </div>
            <div className="mt-1 text-xs text-muted">
              As of {ist(run.as_of)} · {run.evaluated} evaluated · horizon {run.horizon} trading days · config{" "}
              <span className="font-mono">{run.config_fingerprint.slice(0, 12)}</span>
            </div>
            {run.operational_blockers.length > 0 && (
              <div className="mt-3 rounded border border-unknown/50 bg-unknown/10 px-3 py-2 text-sm text-unknown">
                <b>Orders are blocked right now</b> regardless of opportunity quality:
                <ul className="mt-1 list-inside list-disc text-xs">
                  {run.operational_blockers.map((b) => <li key={b}>{b}</li>)}
                </ul>
              </div>
            )}
          </section>

          <Panel title="Ranked candidates">
            <div className="overflow-x-auto">
              <table className="w-full text-xs">
                <thead className="text-left text-muted">
                  <tr>{["#", "Ticker", "Status", "Stance", "Entry", "Stop", "Target", "Qty", "P(profit)", "Exp. net", "R:R", "First blocking gate"].map((h) => <th key={h} className="py-1 pr-3 font-normal">{h}</th>)}</tr>
                </thead>
                <tbody>
                  {(run.rows ?? []).map((r) => (
                    <tr key={r.ticker} className="border-t border-line align-top">
                      <td className="py-1 pr-3 font-mono">{r.rank}</td>
                      <td className="py-1 pr-3 font-mono" title={r.name ?? undefined}>{r.ticker}</td>
                      <td className={`py-1 pr-3 ${r.qualified ? "text-pass" : "text-fail"}`}>{r.qualified ? "✓ Qualified" : "✕ Blocked"}</td>
                      <td className="py-1 pr-3">{r.stance ?? "no report"}</td>
                      <td className="py-1 pr-3 font-mono">{inr(r.entry)}</td>
                      <td className="py-1 pr-3 font-mono">{inr(r.stop)}</td>
                      <td className="py-1 pr-3 font-mono">{inr(r.target)}</td>
                      <td className="py-1 pr-3 font-mono">{r.quantity ?? "—"}</td>
                      <td className="py-1 pr-3 font-mono">{pct(r.p_profit)}</td>
                      <td className="py-1 pr-3 font-mono">{pct(r.expected_net_return, 2)}</td>
                      <td className="py-1 pr-3 font-mono">{r.reward_risk === null || r.reward_risk === undefined ? "—" : r.reward_risk.toFixed(2)}</td>
                      <td className="py-1 text-muted" title={r.failures.join("\n")}>{r.first_failure ?? "—"}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </Panel>

          <div className="grid gap-4 md:grid-cols-2">
            <Panel title="Why not? First blocking gate (opportunity gates)">
              {gates.length === 0 ? (
                <p className="text-sm text-muted">No stock was blocked by an opportunity gate.</p>
              ) : (
                <div style={{ height: Math.max(120, gates.length * 28 + 30) }}>
                  <ResponsiveContainer>
                    <BarChart data={gates} layout="vertical" margin={{ left: 24, right: 16 }}>
                      <CartesianGrid stroke={GRID} strokeDasharray="3 3" horizontal={false} />
                      <XAxis type="number" allowDecimals={false} tick={{ fill: MUTED, fontSize: 10 }} />
                      <YAxis type="category" dataKey="gate" width={130} tick={{ fill: MUTED, fontSize: 10 }} />
                      <Tooltip contentStyle={{ background: "#161c23", border: `1px solid ${GRID}` }} cursor={{ fill: "#263039" }} />
                      <Bar dataKey="n" name="stocks" fill="#3987e5" radius={[0, 3, 3, 0]} />
                    </BarChart>
                  </ResponsiveContainer>
                </div>
              )}
            </Panel>
            <Panel title="Counterfactuals: what happened afterwards">
              {cf && cf.groups.length > 0 ? (
                <table className="w-full text-xs">
                  <thead className="text-left text-muted">
                    <tr>{["Group", "n", "Mean fwd return", "Hit rate", "vs NIFTY 50"].map((h) => <th key={h} className="py-1 pr-3 font-normal">{h}</th>)}</tr>
                  </thead>
                  <tbody>
                    {cf.groups.map((g) => (
                      <tr key={g.group} className="border-t border-line">
                        <td className="py-1 pr-3 font-mono">{g.group}</td>
                        <td className="py-1 pr-3 font-mono">{g.n}</td>
                        <td className="py-1 pr-3 font-mono">{pct(g.mean_forward_return, 2)}</td>
                        <td className="py-1 pr-3 font-mono">{pct(g.hit_rate, 0)}</td>
                        <td className="py-1 pr-3 font-mono">{pct(g.mean_excess_vs_nifty, 2)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              ) : (
                <p className="text-sm text-muted">No realised outcomes yet.</p>
              )}
              {cf && (
                <p className="mt-2 text-xs text-muted">
                  {cf.rankings} rankings · {cf.pending} candidates still inside their {run.horizon}-session window. Returns
                  run from the next session&apos;s close; they show whether the gates reject the right trades.
                </p>
              )}
            </Panel>
          </div>

          <Panel title="History">
            <ul className="space-y-1 text-xs">
              {history.map((h) => (
                <li key={h.id} className="flex flex-wrap justify-between gap-2 border-t border-line pt-1 first:border-0">
                  <span className="font-mono">#{h.id} · {ist(h.as_of)}</span>
                  <span className={h.qualified ? "text-pass" : "text-muted"}>{h.headline}</span>
                </li>
              ))}
            </ul>
          </Panel>
        </>
      )}
    </main>
  );
}
