"use client";

import { useCallback, useEffect, useState } from "react";
import { Login } from "@/components/Login";
import { Nav } from "@/components/Nav";
import { useSession } from "@/components/useSession";
import {
  api,
  ApiError,
  type GateCatalog,
  type PortfolioSummary,
  type ProposalRow,
  type TradeDecision,
  type TradeGateStatus,
} from "@/lib/api";

const tone: Record<TradeGateStatus, string> = {
  PASS: "text-pass",
  FAIL: "text-fail",
  UNKNOWN: "text-unknown",
  NOT_APPLICABLE: "text-muted",
};
const icon: Record<TradeGateStatus, string> = { PASS: "✓", FAIL: "✕", UNKNOWN: "?", NOT_APPLICABLE: "–" };

function fmt(v: number | string | null): string {
  if (v === null) return "—";
  if (typeof v === "string") return v;
  if (Math.abs(v) >= 1e5) return v.toLocaleString("en-IN", { maximumFractionDigits: 0 });
  if (Math.abs(v) < 1 && v !== 0) return v.toFixed(4);
  return v.toLocaleString("en-IN", { maximumFractionDigits: 2 });
}

function Panel({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section className="mb-4 rounded-lg border border-line bg-panel p-5">
      <h3 className="mb-3 text-xs font-semibold uppercase tracking-wider text-muted">{title}</h3>
      {children}
    </section>
  );
}

export default function TradePage() {
  const { token, ready, me, health, signIn, signOut, guard } = useSession();
  const [catalog, setCatalog] = useState<GateCatalog | null>(null);
  const [portfolios, setPortfolios] = useState<PortfolioSummary[]>([]);
  const [rows, setRows] = useState<ProposalRow[]>([]);
  const [result, setResult] = useState<TradeDecision | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [f, setF] = useState({
    portfolio_id: "",
    ticker: "",
    side: "buy" as "buy" | "sell",
    quantity: "",
    entry_price: "",
    stop_loss: "",
    target: "",
    horizon_days: "20",
    quoted_spread_bps: "",
  });

  const load = useCallback(async () => {
    try {
      const [c, p, r] = await Promise.all([
        guard((t) => api.tradeGates(t)),
        guard((t) => api.portfolios(t)),
        guard((t) => api.proposals(t)),
      ]);
      if (c) setCatalog(c);
      if (p) {
        setPortfolios(p);
        setF((x) => (x.portfolio_id || !p[0] ? x : { ...x, portfolio_id: String(p[0].id) }));
      }
      if (r) setRows(r);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Request failed");
    }
  }, [guard]);

  useEffect(() => {
    if (token) void load();
  }, [token, load]);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const d = await guard((t) =>
        api.submitProposal(t, {
          ticker: f.ticker.trim().toUpperCase(),
          side: f.side,
          quantity: Number(f.quantity),
          entry_price: f.entry_price,
          stop_loss: f.stop_loss || null,
          target: f.target || null,
          horizon_days: Number(f.horizon_days),
          portfolio_id: Number(f.portfolio_id),
          mode: "paper",
          quoted_spread_bps: f.quoted_spread_bps === "" ? null : Number(f.quoted_spread_bps),
        }),
      );
      if (d) setResult(d);
      await load();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Request failed");
    } finally {
      setBusy(false);
    }
  }

  async function open(id: number) {
    try {
      const d = await guard((t) => api.decision(t, id));
      if (d) setResult(d);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Request failed");
    }
  }

  if (!ready) return null;
  if (!token) return <Login onToken={signIn} />;
  const input = "rounded border border-line bg-surface px-2 py-1.5 text-sm font-mono";
  const set = (k: keyof typeof f) => (e: React.ChangeEvent<HTMLInputElement | HTMLSelectElement>) =>
    setF({ ...f, [k]: e.target.value });

  return (
    <main className="mx-auto max-w-5xl px-4 py-8">
      <Nav mode={health?.system_mode} email={me?.email} role={me?.role} onSignOut={signOut} />
      <h2 className="mb-1 text-2xl font-semibold">Trade Risk Engine</h2>
      <p className="mb-6 text-sm text-muted">
        {catalog?.rule ?? "Deterministic gates."} The engine decides; no agent, person or language model can override a
        gate. Approved proposals still need human approval before any order.
      </p>
      {error && <p className="mb-4 text-sm text-fail">{error}</p>}

      <Panel title="Evaluate a proposal">
        <form onSubmit={submit} className="grid gap-2 sm:grid-cols-3 lg:grid-cols-5">
          <label className="text-xs text-muted">Portfolio
            <select className={`${input} mt-1 w-full`} value={f.portfolio_id} onChange={set("portfolio_id")}>
              {portfolios.map((p) => (
                <option key={p.id} value={p.id}>{p.name} ({p.kind})</option>
              ))}
            </select>
          </label>
          <label className="text-xs text-muted">Ticker
            <input className={`${input} mt-1 w-full`} placeholder="TCS.NS" value={f.ticker} onChange={set("ticker")} />
          </label>
          <label className="text-xs text-muted">Side
            <select className={`${input} mt-1 w-full`} value={f.side} onChange={set("side")}>
              <option value="buy">buy (entry)</option>
              <option value="sell">sell (exit)</option>
            </select>
          </label>
          <label className="text-xs text-muted">Quantity
            <input className={`${input} mt-1 w-full`} value={f.quantity} onChange={set("quantity")} />
          </label>
          <label className="text-xs text-muted">Limit price ₹
            <input className={`${input} mt-1 w-full`} value={f.entry_price} onChange={set("entry_price")} />
          </label>
          <label className="text-xs text-muted">Stop-loss ₹
            <input className={`${input} mt-1 w-full`} value={f.stop_loss} onChange={set("stop_loss")} />
          </label>
          <label className="text-xs text-muted">Target ₹
            <input className={`${input} mt-1 w-full`} value={f.target} onChange={set("target")} />
          </label>
          <label className="text-xs text-muted">Horizon (days)
            <input className={`${input} mt-1 w-full`} value={f.horizon_days} onChange={set("horizon_days")} />
          </label>
          <label className="text-xs text-muted">Quoted spread (bps)
            <input className={`${input} mt-1 w-full`} placeholder="from a live quote" value={f.quoted_spread_bps} onChange={set("quoted_spread_bps")} />
          </label>
          <div className="flex items-end">
            <button className="w-full rounded bg-ink px-3 py-1.5 text-sm text-surface disabled:opacity-40" disabled={busy || !f.ticker || !f.quantity || !f.entry_price || !f.portfolio_id}>
              {busy ? "Evaluating…" : "Evaluate"}
            </button>
          </div>
        </form>
        {portfolios.length === 0 && <p className="mt-2 text-xs text-unknown">Create a paper portfolio on the Portfolios page first.</p>}
      </Panel>

      {result && (
        <Panel title={`Decision · proposal #${result.proposal_id}`}>
          <div className="mb-3 flex flex-wrap items-end gap-6">
            <div className={`text-2xl font-semibold ${result.decision === "APPROVED" ? "text-pass" : "text-fail"}`}>
              {result.decision}
            </div>
            {result.first_failure && (
              <div className="text-sm text-muted">first failure: <span className="font-mono text-ink">{result.first_failure}</span> · {result.failed_gates.length} gate(s) not passed</div>
            )}
            {result.decision === "APPROVED" && <div className="text-sm text-unknown">Needs human approval before any order.</div>}
            {result.costs && (
              <div className="text-sm text-muted">round-trip costs <span className="font-mono text-ink">{(result.costs.round_trip_fraction * 100).toFixed(2)}%</span></div>
            )}
          </div>
          <div className="overflow-x-auto">
            <table className="w-full text-xs">
              <thead className="text-left text-muted">
                <tr>
                  {["#", "Gate", "Status", "Value", "Threshold", "Reason"].map((h) => (
                    <th key={h} className="py-1 pr-3 font-normal">{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {result.gates.map((g) => (
                  <tr key={g.order} className="border-t border-line align-top">
                    <td className="py-1 pr-3 font-mono text-muted">{g.order}</td>
                    <td className="py-1 pr-3 font-mono">{g.name}</td>
                    <td className={`whitespace-nowrap py-1 pr-3 font-mono ${tone[g.status]}`}>{icon[g.status]} {g.status.replace("_", " ")}</td>
                    <td className="py-1 pr-3 font-mono">{fmt(g.value)}</td>
                    <td className="py-1 pr-3 font-mono">{fmt(g.threshold)}</td>
                    <td className="py-1 text-muted">{g.reason}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <p className="mt-2 font-mono text-[11px] text-muted">{result.engine_version} · hash {result.decision_hash.slice(0, 16)}</p>
        </Panel>
      )}

      <div className="grid gap-4 md:grid-cols-2">
        <Panel title="Recent proposals">
          <ul className="space-y-1 text-xs">
            {rows.map((r) => (
              <li key={r.proposal_id} className="flex flex-wrap justify-between gap-2 border-t border-line pt-1 first:border-0">
                <button className="font-mono underline" onClick={() => open(r.decision_id)}>
                  #{r.proposal_id} {r.side} {r.quantity} {r.ticker} @ ₹{r.entry_price}
                </button>
                <span className={r.decision === "APPROVED" ? "text-pass" : "text-fail"}>
                  {r.decision}{r.first_failure ? ` · ${r.first_failure}` : ""}
                </span>
              </li>
            ))}
            {rows.length === 0 && <li className="text-muted">None yet.</li>}
          </ul>
        </Panel>
        <Panel title={`The ${catalog?.gates.length ?? 24} gates (in order)`}>
          {catalog && (
            <>
              <p className={`mb-2 text-xs ${catalog.self_test.passed ? "text-pass" : "text-fail"}`}>
                Self-test: {catalog.self_test.detail}
              </p>
              <ol className="space-y-1 text-xs">
                {catalog.gates.map((g) => (
                  <li key={g.name}>
                    <span className="font-mono">{g.order}. {g.name}</span>
                    {!g.applies_to_exits && <span className="text-muted"> (entries only)</span>} — <span className="text-muted">{g.description}</span>
                  </li>
                ))}
              </ol>
            </>
          )}
        </Panel>
      </div>
    </main>
  );
}
