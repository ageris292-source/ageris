"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import { Login } from "@/components/Login";
import { Nav } from "@/components/Nav";
import { TechnicalPanel } from "@/components/TechnicalPanel";
import { useSession } from "@/components/useSession";
import {
  api,
  ApiError,
  type GateStatus,
  type PortfolioAnalysis,
  type PortfolioFit,
  type PortfolioSummary,
} from "@/lib/api";

const tone: Record<GateStatus, string> = { PASS: "text-pass", FAIL: "text-fail", UNKNOWN: "text-unknown" };
const inr = new Intl.NumberFormat("en-IN", { maximumFractionDigits: 0 });
const pct = (v: number | null | undefined, d = 1) =>
  v === null || v === undefined ? "—" : `${(v * 100).toFixed(d)}%`;
const RATIO_KEYS = new Set(["sharpe", "beta", "effective_positions", "herfindahl", "positions"]);
const MONEY_KEYS = new Set(["equity", "cash", "invested"]);

function Panel({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section className="mb-4 rounded-lg border border-line bg-panel p-5">
      <h3 className="mb-3 text-xs font-semibold uppercase tracking-wider text-muted">{title}</h3>
      {children}
    </section>
  );
}

function Checks({ a }: { a: PortfolioAnalysis }) {
  return (
    <table className="w-full text-sm">
      <tbody>
        {a.checks.map((c) => (
          <tr key={c.name} className="border-t border-line">
            <td className="py-1.5 pr-3 font-mono text-xs">{c.name}</td>
            <td className="py-1.5 pr-3 text-xs text-muted">{c.kind}</td>
            <td className={`whitespace-nowrap py-1.5 pr-3 font-mono text-xs ${tone[c.status]}`}>
              {c.status === "PASS" ? "✓ " : c.status === "FAIL" ? "✕ " : "? "}
              {c.status}
            </td>
            <td className="py-1.5 text-xs text-muted">{c.reason}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

export default function PortfoliosPage() {
  const { token, ready, me, health, signIn, signOut, guard } = useSession();
  const [list, setList] = useState<PortfolioSummary[] | null>(null);
  const [sel, setSel] = useState<number | null>(null);
  const [analysis, setAnalysis] = useState<PortfolioAnalysis | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [name, setName] = useState("");
  const [cash, setCash] = useState("1000000");
  const [pos, setPos] = useState({ ticker: "", quantity: "", avg_cost: "" });
  const [cand, setCand] = useState({ ticker: "", weight: "5" });
  const [fit, setFit] = useState<PortfolioFit | null>(null);
  const [fitBusy, setFitBusy] = useState(false);

  const fail = (err: unknown) => setError(err instanceof ApiError || err instanceof Error ? err.message : "Request failed");

  const load = useCallback(async () => {
    try {
      const rows = await guard((t) => api.portfolios(t));
      if (rows) {
        setList(rows);
        setSel((s) => s ?? rows[0]?.id ?? null);
      }
    } catch (err) {
      fail(err);
    }
  }, [guard]);

  const analyse = useCallback(async () => {
    if (sel === null) return;
    setBusy(true);
    try {
      const a = await guard((t) => api.portfolioAnalysis(t, sel));
      if (a) setAnalysis(a);
    } catch (err) {
      fail(err);
    } finally {
      setBusy(false);
    }
  }, [guard, sel]);

  useEffect(() => {
    if (token) void load();
  }, [token, load]);
  useEffect(() => {
    setFit(null);
    void analyse();
  }, [analyse]);

  async function create(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    try {
      const p = await guard((t) => api.createPortfolio(t, name.trim(), cash));
      setName("");
      if (p) setSel(p.id);
      await load();
    } catch (err) {
      fail(err);
    }
  }

  async function savePosition(e: React.FormEvent) {
    e.preventDefault();
    if (sel === null) return;
    setError(null);
    try {
      await guard((t) =>
        api.setPosition(t, sel, pos.ticker.trim().toUpperCase(), Number(pos.quantity), pos.avg_cost || "0"),
      );
      setPos({ ticker: "", quantity: "", avg_cost: "" });
      await load();
      await analyse();
    } catch (err) {
      fail(err);
    }
  }

  async function testFit(e: React.FormEvent) {
    e.preventDefault();
    if (sel === null) return;
    setFitBusy(true);
    setError(null);
    try {
      const f = await guard((t) => api.portfolioFit(t, sel, cand.ticker.trim().toUpperCase(), Number(cand.weight) / 100));
      if (f) setFit(f);
    } catch (err) {
      fail(err);
    } finally {
      setFitBusy(false);
    }
  }

  if (!ready) return null;
  if (!token) return <Login onToken={signIn} />;
  const current = list?.find((p) => p.id === sel) ?? null;
  const input = "rounded border border-line bg-surface px-2 py-1.5 text-sm";

  return (
    <main className="mx-auto max-w-5xl px-4 py-8">
      <Nav mode={health?.system_mode} email={me?.email} role={me?.role} onSignOut={signOut} />
      <h2 className="mb-1 text-2xl font-semibold">Portfolios</h2>
      <p className="mb-6 text-sm text-muted">
        Model portfolios for exposure and what-if analysis. Paper portfolios are changed only by the paper broker.
      </p>
      {error && <p className="mb-4 text-sm text-fail">{error}</p>}

      <div className="mb-6 flex flex-wrap items-end gap-4">
        <div className="flex flex-wrap gap-2" role="tablist" aria-label="Portfolios">
          {list?.map((p) => (
            <button
              key={p.id}
              role="tab"
              aria-selected={p.id === sel}
              onClick={() => setSel(p.id)}
              className={`rounded px-3 py-1.5 text-sm ${p.id === sel ? "bg-ink text-surface" : "border border-line text-muted hover:text-ink"}`}
            >
              {p.name} <span className="text-xs opacity-70">({p.kind})</span>
            </button>
          ))}
          {list?.length === 0 && <span className="text-sm text-muted">No portfolios yet.</span>}
        </div>
        <form onSubmit={create} className="ml-auto flex flex-wrap gap-2">
          <input className={input} placeholder="New portfolio name" value={name} onChange={(e) => setName(e.target.value)} aria-label="Portfolio name" />
          <input className={`${input} w-32 font-mono`} value={cash} onChange={(e) => setCash(e.target.value)} aria-label="Starting cash (₹)" />
          <button className="rounded bg-ink px-3 py-1.5 text-sm text-surface disabled:opacity-40" disabled={name.trim().length < 2}>
            Create
          </button>
        </form>
      </div>

      {current && (
        <>
          <Panel title={`Holdings · ${current.name}`}>
            {analysis && analysis.portfolio.id === current.id ? (
              <>
                <div className="mb-3 flex flex-wrap gap-6 text-sm">
                  <div>
                    <div className="text-muted">Equity</div>
                    <div className="font-mono">₹{inr.format(analysis.metrics.equity ?? 0)}</div>
                  </div>
                  <div>
                    <div className="text-muted">Cash</div>
                    <div className="font-mono">₹{inr.format(analysis.metrics.cash ?? 0)}</div>
                  </div>
                  <div>
                    <div className="text-muted">Limits</div>
                    <div className={`font-mono ${tone[analysis.limits_status]}`}>{analysis.limits_status}</div>
                  </div>
                </div>
                <div className="overflow-x-auto">
                  <table className="w-full font-mono text-xs">
                    <thead className="text-left text-muted">
                      <tr>
                        {["Ticker", "Qty", "Price", "Value", "Weight", "Sector", "P&L", "ADTV (₹ cr)"].map((h) => (
                          <th key={h} className="py-1 pr-3 font-normal">{h}</th>
                        ))}
                      </tr>
                    </thead>
                    <tbody>
                      {analysis.holdings.map((x) => (
                        <tr key={x.ticker} className="border-t border-line">
                          <td className="py-1 pr-3"><Link className="underline" href={`/stocks/${encodeURIComponent(x.ticker)}`}>{x.ticker}</Link></td>
                          <td className="py-1 pr-3">{x.quantity}</td>
                          <td className="py-1 pr-3">{x.price === null ? <span className="text-unknown">unknown</span> : inr.format(x.price)}</td>
                          <td className="py-1 pr-3">{x.value === null ? "—" : inr.format(x.value)}</td>
                          <td className="py-1 pr-3">{pct(x.weight)}</td>
                          <td className="py-1 pr-3">{x.sector.replaceAll("_", " ").toLowerCase()}</td>
                          <td className={`py-1 pr-3 ${x.unrealised_pnl !== null && x.unrealised_pnl < 0 ? "text-fail" : ""}`}>
                            {x.unrealised_pnl === null ? "—" : inr.format(x.unrealised_pnl)}
                          </td>
                          <td className="py-1 pr-3">{x.adtv === null ? "—" : (x.adtv / 1e7).toFixed(1)}</td>
                        </tr>
                      ))}
                      {analysis.holdings.length === 0 && (
                        <tr><td colSpan={8} className="py-2 text-muted">No holdings.</td></tr>
                      )}
                    </tbody>
                  </table>
                </div>
              </>
            ) : (
              <p className="text-sm text-muted">{busy ? "Analysing…" : "—"}</p>
            )}
            {current.kind === "model" && (
              <form onSubmit={savePosition} className="mt-4 flex flex-wrap gap-2">
                <input className={`${input} w-36 font-mono`} placeholder="TICKER.NS" value={pos.ticker} onChange={(e) => setPos({ ...pos, ticker: e.target.value })} aria-label="Ticker" />
                <input className={`${input} w-24 font-mono`} placeholder="Qty (0 = remove)" value={pos.quantity} onChange={(e) => setPos({ ...pos, quantity: e.target.value })} aria-label="Quantity" />
                <input className={`${input} w-28 font-mono`} placeholder="Avg cost ₹" value={pos.avg_cost} onChange={(e) => setPos({ ...pos, avg_cost: e.target.value })} aria-label="Average cost" />
                <button className="rounded border border-line px-3 py-1.5 text-sm disabled:opacity-40" disabled={!pos.ticker || pos.quantity === ""}>
                  Save holding
                </button>
              </form>
            )}
          </Panel>

          {analysis && analysis.portfolio.id === current.id && (
            <div className="grid gap-4 md:grid-cols-2">
              <Panel title="Limit and advisory checks">
                <Checks a={analysis} />
                <p className="mt-3 text-xs text-muted">UNKNOWN never passes. Advisory checks inform but do not block.</p>
              </Panel>
              <Panel title="Risk (current weights, trailing year)">
                <dl className="grid grid-cols-2 gap-y-1 text-sm">
                  {Object.entries(analysis.metrics).map(([k, v]) => (
                    <div key={k} className="contents">
                      <dt className="text-muted">{k.replaceAll("_", " ")}</dt>
                      <dd className="font-mono text-xs">
                        {v === null ? "—" : MONEY_KEYS.has(k) ? `₹${inr.format(v)}` : RATIO_KEYS.has(k) ? v.toFixed(2) : pct(v, 2)}
                      </dd>
                    </div>
                  ))}
                </dl>
                {analysis.high_correlation_pairs.length > 0 && (
                  <p className="mt-2 text-xs text-unknown">
                    Highly correlated: {analysis.high_correlation_pairs.map((p) => `${p.a}/${p.b} ${p.correlation.toFixed(2)}`).join(", ")}
                  </p>
                )}
                {analysis.warnings.map((w) => (
                  <p key={w} className="mt-2 text-xs text-unknown">! {w}</p>
                ))}
              </Panel>
            </div>
          )}

          <Panel title="What-if: add a stock">
            <form onSubmit={testFit} className="flex flex-wrap items-center gap-2">
              <input className={`${input} w-36 font-mono`} placeholder="TICKER.NS" value={cand.ticker} onChange={(e) => setCand({ ...cand, ticker: e.target.value })} aria-label="Candidate ticker" />
              <input className={`${input} w-20 font-mono`} value={cand.weight} onChange={(e) => setCand({ ...cand, weight: e.target.value })} aria-label="Target weight %" />
              <span className="text-sm text-muted">% of equity</span>
              <button className="rounded bg-ink px-3 py-1.5 text-sm text-surface disabled:opacity-40" disabled={!cand.ticker || fitBusy}>
                {fitBusy ? "Checking…" : "Check fit"}
              </button>
            </form>
            {fit && (
              <div className="mt-4">
                <TechnicalPanel title={`Portfolio fit · ${fit.analysis.ticker}`} scoreLabel="Fit score" runLabel="Re-check" out={fit.analysis} busy={fitBusy} onRun={() => void testFit({ preventDefault() {} } as React.FormEvent)}>
                  <h4 className="mb-1 mt-4 text-xs font-semibold uppercase tracking-wider text-muted">Checks after the trade</h4>
                  <Checks a={fit.details.after} />
                </TechnicalPanel>
              </div>
            )}
          </Panel>
        </>
      )}
    </main>
  );
}
