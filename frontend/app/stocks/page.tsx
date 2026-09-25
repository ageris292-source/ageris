"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import { Login } from "@/components/Login";
import { Nav } from "@/components/Nav";
import { FreshnessBadge } from "@/components/StatusBadge";
import { useSession } from "@/components/useSession";
import { ApiError, api, type StockSummary } from "@/lib/api";

export default function StocksPage() {
  const { token, ready, me, health, signIn, signOut, guard } = useSession();
  const [stocks, setStocks] = useState<StockSummary[] | null>(null);
  const [ticker, setTicker] = useState("");
  const [busy, setBusy] = useState<string | null>(null);
  const [message, setMessage] = useState<{ tone: "ok" | "fail"; text: string } | null>(null);

  const load = useCallback(async () => {
    try {
      const rows = await guard((t) => api.stocks(t));
      if (rows) setStocks(rows);
    } catch (err) {
      setMessage({ tone: "fail", text: err instanceof Error ? err.message : "Request failed" });
    }
  }, [guard]);

  useEffect(() => {
    if (token) void load();
  }, [token, load]);

  async function add(e: React.FormEvent) {
    e.preventDefault();
    setMessage(null);
    try {
      await guard((t) => api.addStock(t, ticker.trim()));
      setTicker("");
      await load();
    } catch (err) {
      setMessage({ tone: "fail", text: err instanceof ApiError ? err.message : "Request failed" });
    }
  }

  async function refresh(tk: string) {
    setBusy(tk);
    setMessage(null);
    try {
      const run = await guard((t) => api.ingest(t, tk));
      if (run) {
        setMessage({
          tone: run.status === "failed" || run.status === "rejected" ? "fail" : "ok",
          text:
            `${tk}: ${run.status.replaceAll("_", " ")} — ${run.rows_inserted} new, ` +
            `${run.rows_revised} revised, ${run.rows_rejected} rejected` +
            (run.error ? ` (${run.error})` : ""),
        });
      }
      await load();
    } catch (err) {
      setMessage({ tone: "fail", text: err instanceof Error ? err.message : "Request failed" });
    } finally {
      setBusy(null);
    }
  }

  if (!ready) return null;
  if (!token) return <Login onToken={signIn} />;

  return (
    <main className="mx-auto max-w-5xl px-4 py-8">
      <Nav mode={health?.system_mode} email={me?.email} role={me?.role} onSignOut={signOut} />

      <div className="mb-6 flex flex-wrap items-end justify-between gap-4">
        <div>
          <h2 className="text-xl font-semibold">Stocks</h2>
          <p className="text-sm text-muted">NSE (.NS) and BSE (.BO) end-of-day data.</p>
        </div>
        {me?.role === "admin" && (
          <form onSubmit={add} className="flex gap-2">
            <input
              className="w-40 rounded border border-line bg-panel px-3 py-1.5 font-mono text-sm uppercase"
              placeholder="TCS.NS"
              aria-label="Ticker to add"
              value={ticker}
              onChange={(e) => setTicker(e.target.value)}
            />
            <button
              className="rounded bg-ink px-3 py-1.5 text-sm font-medium text-surface disabled:opacity-40"
              disabled={ticker.trim().length < 4}
            >
              Add
            </button>
          </form>
        )}
      </div>

      {message && (
        <p className={`mb-4 text-sm ${message.tone === "ok" ? "text-pass" : "text-fail"}`}>
          {message.text}
        </p>
      )}

      <div className="overflow-x-auto rounded-lg border border-line bg-panel">
        <table className="w-full text-sm">
          <thead className="text-left text-xs uppercase tracking-wider text-muted">
            <tr>
              <th className="px-4 py-3 font-semibold">Ticker</th>
              <th className="px-4 py-3 font-semibold">Name</th>
              <th className="px-4 py-3 font-semibold">Latest session</th>
              <th className="px-4 py-3 font-semibold">Freshness</th>
              <th className="px-4 py-3 font-semibold">Last ingest</th>
              <th className="px-4 py-3" />
            </tr>
          </thead>
          <tbody>
            {stocks?.length === 0 && (
              <tr>
                <td colSpan={6} className="px-4 py-8 text-center text-muted">
                  No stocks yet.{" "}
                  {me?.role === "admin" ? "Add one above, e.g. TCS.NS." : "Ask an admin to add one."}
                </td>
              </tr>
            )}
            {stocks?.map((s) => (
              <tr key={s.ticker} className="border-t border-line">
                <td className="px-4 py-3 font-mono">
                  <Link className="underline-offset-2 hover:underline" href={`/stocks/${s.ticker}`}>
                    {s.ticker}
                  </Link>
                </td>
                <td className="px-4 py-3">{s.name ?? <span className="text-muted">—</span>}</td>
                <td className="px-4 py-3 font-mono">{s.latest_session ?? "—"}</td>
                <td className="px-4 py-3">
                  <FreshnessBadge f={s.freshness} />
                </td>
                <td className="px-4 py-3 text-muted">
                  {s.last_run_status?.replaceAll("_", " ") ?? "never"}
                </td>
                <td className="px-4 py-3 text-right">
                  <button
                    className="whitespace-nowrap rounded border border-line px-2.5 py-1 text-xs disabled:opacity-40"
                    disabled={busy !== null}
                    onClick={() => refresh(s.ticker)}
                  >
                    {busy === s.ticker ? "Fetching…" : "Refresh data"}
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </main>
  );
}
