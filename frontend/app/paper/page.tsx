"use client";

import { useCallback, useEffect, useState } from "react";
import { CartesianGrid, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { Login } from "@/components/Login";
import { Nav } from "@/components/Nav";
import { useSession } from "@/components/useSession";
import {
  api,
  ApiError,
  type PaperOrderOut,
  type PaperPortfolioOut,
  type PortfolioSummary,
  type ProposalRow,
} from "@/lib/api";

const inr = (v: string | number | null | undefined) =>
  v === null || v === undefined ? "—" : `₹${Number(v).toLocaleString("en-IN", { maximumFractionDigits: 2 })}`;
const GRID = "#263039";
const MUTED = "#8b98a5";

function Panel({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section className="mb-4 rounded-lg border border-line bg-panel p-5">
      <h3 className="mb-3 text-xs font-semibold uppercase tracking-wider text-muted">{title}</h3>
      {children}
    </section>
  );
}

function newKey(): string {
  try {
    return crypto.randomUUID();
  } catch {
    return `k-${Date.now()}-${Math.random().toString(36).slice(2)}`;
  }
}

export default function PaperPage() {
  const { token, ready, me, health, signIn, signOut, guard } = useSession();
  const [pfs, setPfs] = useState<PortfolioSummary[]>([]);
  const [sel, setSel] = useState<number | null>(null);
  const [data, setData] = useState<PaperPortfolioOut | null>(null);
  const [orders, setOrders] = useState<PaperOrderOut[]>([]);
  const [pending, setPending] = useState<ProposalRow[]>([]);
  const [msg, setMsg] = useState<{ tone: "ok" | "fail"; text: string } | null>(null);
  const [busy, setBusy] = useState<number | null>(null);
  const isAdmin = me?.role === "admin";

  const load = useCallback(async () => {
    try {
      const all = await guard((t) => api.portfolios(t));
      const paper = (all ?? []).filter((p) => p.kind === "paper");
      setPfs(paper);
      const id = sel ?? paper[0]?.id ?? null;
      if (id === null) return;
      setSel(id);
      const [d, o, p] = await Promise.all([
        guard((t) => api.paperPortfolio(t, id)),
        guard((t) => api.paperOrders(t, id)),
        guard((t) => api.proposalsFor(t, id)),
      ]);
      if (d) setData(d);
      if (o) setOrders(o);
      if (p && o) {
        const done = new Set(o.filter((x) => x.status === "FILLED").map((x) => x.decision_id));
        setPending(p.filter((x) => x.decision === "APPROVED" && !done.has(x.decision_id) && !x.rationale?.startsWith("pre-order re-check")));
      }
    } catch (err) {
      setMsg({ tone: "fail", text: err instanceof Error ? err.message : "Request failed" });
    }
  }, [guard, sel]);

  useEffect(() => {
    if (token) void load();
  }, [token, load]);

  async function approve(decisionId: number) {
    setBusy(decisionId);
    setMsg(null);
    try {
      const o = await guard((t) => api.placePaperOrder(t, decisionId, newKey()));
      if (o) setMsg({ tone: o.status === "FILLED" ? "ok" : "fail", text: `Order #${o.id} ${o.status}: ${o.reason}` });
      await load();
    } catch (err) {
      setMsg({ tone: "fail", text: err instanceof ApiError ? err.message : "Order failed" });
    } finally {
      setBusy(null);
    }
  }

  async function monitor() {
    const r = await guard((t) => api.runMonitor(t));
    setMsg({ tone: "ok", text: r && r.events.length ? r.events.map((e) => `${e.kind}: ${e.detail}`).join(" · ") : "No new thesis events." });
    await load();
  }

  if (!ready) return null;
  if (!token) return <Login onToken={signIn} />;
  const m = data?.analysis.metrics;

  return (
    <main className="mx-auto max-w-5xl px-4 py-8">
      <Nav mode={health?.system_mode} email={me?.email} role={me?.role} onSignOut={signOut} />
      <div className="mb-6 flex flex-wrap items-end justify-between gap-3">
        <div>
          <h2 className="mb-1 text-2xl font-semibold">Paper trading</h2>
          <p className="text-sm text-muted">
            Simulated money only. An admin approves each order; the engine re-checks all 24 gates right before the fill.
          </p>
        </div>
        <div className="flex gap-2">
          {pfs.map((p) => (
            <button key={p.id} onClick={() => setSel(p.id)} aria-pressed={p.id === sel}
              className={`rounded px-3 py-1.5 text-sm ${p.id === sel ? "bg-ink text-surface" : "border border-line text-muted"}`}>
              {p.name}
            </button>
          ))}
          <button className="rounded border border-line px-3 py-1.5 text-sm" onClick={monitor}>Check theses</button>
        </div>
      </div>
      {health?.system_mode !== "paper" && (
        <div className="mb-4 rounded border border-unknown/50 bg-unknown/10 px-4 py-2 text-sm text-unknown">
          System mode is <b>{health?.system_mode ?? "unknown"}</b>: every order will be rejected by the execution-mode gate until AEGIS_SYSTEM_MODE=paper.
        </div>
      )}
      {msg && <p className={`mb-4 text-sm ${msg.tone === "ok" ? "text-pass" : "text-fail"}`}>{msg.text}</p>}
      {pfs.length === 0 && <p className="text-sm text-muted">No paper portfolio yet. Create one via the API (kind “paper”).</p>}

      {data && m && (
        <>
          <Panel title="Account">
            <div className="grid grid-cols-2 gap-4 sm:grid-cols-5">
              {[
                ["Equity", inr(m.equity)],
                ["Cash", inr(m.cash)],
                ["Total return", data.total_return === null ? "—" : `${(data.total_return * 100).toFixed(2)}%`],
                ["Realised P&L", inr(data.realised_pnl)],
                ["Fees paid", inr(data.fees_paid)],
              ].map(([k, v]) => (
                <div key={k}><div className="text-xs text-muted">{k}</div><div className="font-mono text-lg">{v}</div></div>
              ))}
            </div>
            {data.equity_curve.length > 1 && (
              <div className="mt-4 h-40">
                <ResponsiveContainer>
                  <LineChart data={data.equity_curve}>
                    <CartesianGrid stroke={GRID} strokeDasharray="3 3" />
                    <XAxis dataKey="taken_at" tick={{ fill: MUTED, fontSize: 10 }} tickFormatter={(v: string) => v.slice(0, 10)} />
                    <YAxis tick={{ fill: MUTED, fontSize: 10 }} domain={["auto", "auto"]} />
                    <Tooltip contentStyle={{ background: "#161c23", border: `1px solid ${GRID}` }} />
                    <Line dataKey="equity" stroke="#3987e5" dot={false} />
                  </LineChart>
                </ResponsiveContainer>
              </div>
            )}
          </Panel>

          <Panel title="Awaiting human approval (APPROVED by the engine)">
            <ul className="space-y-2 text-sm">
              {pending.map((p) => (
                <li key={p.decision_id} className="flex flex-wrap items-center justify-between gap-2 border-t border-line pt-2 first:border-0">
                  <span className="font-mono text-xs">#{p.proposal_id} {p.side} {p.quantity} {p.ticker} @ ≤ ₹{p.entry_price} · {new Date(p.created_at).toLocaleString("en-IN", { timeZone: "Asia/Kolkata" })}</span>
                  {isAdmin ? (
                    <button className="rounded bg-ink px-2.5 py-1 text-xs text-surface disabled:opacity-40" disabled={busy === p.decision_id} onClick={() => approve(p.decision_id)}>
                      {busy === p.decision_id ? "Re-checking…" : "Approve & place paper order"}
                    </button>
                  ) : (
                    <span className="text-xs text-muted">admin approval required</span>
                  )}
                </li>
              ))}
              {pending.length === 0 && <li className="text-muted">Nothing awaiting approval. Evaluate proposals on the Trade risk page.</li>}
            </ul>
          </Panel>

          <div className="grid gap-4 md:grid-cols-2">
            <Panel title="Positions">
              <table className="w-full font-mono text-xs">
                <thead className="text-left text-muted"><tr>{["Ticker", "Qty", "Avg cost", "Price", "P&L"].map((h) => <th key={h} className="py-1 pr-3 font-normal">{h}</th>)}</tr></thead>
                <tbody>
                  {data.analysis.holdings.map((x) => (
                    <tr key={x.ticker} className="border-t border-line">
                      <td className="py-1 pr-3">{x.ticker}</td><td className="py-1 pr-3">{x.quantity}</td>
                      <td className="py-1 pr-3">{inr(x.avg_cost)}</td><td className="py-1 pr-3">{inr(x.price)}</td>
                      <td className={`py-1 pr-3 ${x.unrealised_pnl !== null && x.unrealised_pnl < 0 ? "text-fail" : ""}`}>{inr(x.unrealised_pnl)}</td>
                    </tr>
                  ))}
                  {data.analysis.holdings.length === 0 && <tr><td colSpan={5} className="py-2 text-muted">No open positions.</td></tr>}
                </tbody>
              </table>
            </Panel>
            <Panel title="Theses">
              <ul className="space-y-2 text-xs">
                {data.theses.map((t) => (
                  <li key={t.id} className="border-t border-line pt-2 first:border-0">
                    <div className="flex justify-between"><span className="font-mono">{t.ticker} · entry {inr(t.entry_price)}</span><span className={t.status === "OPEN" ? "text-pass" : "text-muted"}>{t.status}</span></div>
                    <div className="text-muted">stop {inr(t.stop_loss)} · target {inr(t.target)} · until {t.horizon_end}</div>
                    {t.events.map((e) => (
                      <div key={e.kind + e.session} className="text-unknown">! {e.session} {e.kind}: {e.detail}{e.exit_proposal_id ? ` → exit proposal #${e.exit_proposal_id} (${e.exit_decision})` : ""}</div>
                    ))}
                  </li>
                ))}
                {data.theses.length === 0 && <li className="text-muted">No theses yet.</li>}
              </ul>
            </Panel>
          </div>

          <Panel title="Orders and fills">
            <table className="w-full text-xs">
              <thead className="text-left text-muted"><tr>{["#", "Side", "Ticker", "Qty", "Limit", "Status", "Detail"].map((h) => <th key={h} className="py-1 pr-3 font-normal">{h}</th>)}</tr></thead>
              <tbody>
                {orders.map((o) => (
                  <tr key={o.id} className="border-t border-line align-top">
                    <td className="py-1 pr-3 font-mono">{o.id}</td><td className="py-1 pr-3">{o.side}</td><td className="py-1 pr-3 font-mono">{o.ticker}</td>
                    <td className="py-1 pr-3 font-mono">{o.quantity}</td><td className="py-1 pr-3 font-mono">{inr(o.limit_price)}</td>
                    <td className={`py-1 pr-3 ${o.status === "FILLED" ? "text-pass" : "text-fail"}`}>{o.status}</td>
                    <td className="py-1 text-muted">{o.reason}</td>
                  </tr>
                ))}
                {orders.length === 0 && <tr><td colSpan={7} className="py-2 text-muted">No orders yet.</td></tr>}
              </tbody>
            </table>
          </Panel>
        </>
      )}
    </main>
  );
}
