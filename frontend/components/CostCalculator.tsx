"use client";

import { useState } from "react";
import { api, ApiError, type CostResult } from "@/lib/api";

type Guard = <T>(fn: (t: string) => Promise<T>) => Promise<T | undefined>;

const inr = (v: number) => `₹${v.toLocaleString("en-IN", { maximumFractionDigits: 2 })}`;

/** Round-trip cost of a trade under the configured NSE schedule, before proposing it. */
export function CostCalculator({ guard }: { guard: Guard }) {
  const [f, setF] = useState({ ticker: "RELIANCE.NS", quantity: "10", entry_price: "", horizon_days: "20", spread: "" });
  const [out, setOut] = useState<CostResult | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function run(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setErr(null);
    try {
      const r = await guard((t) =>
        api.tradeCosts(t, {
          ticker: f.ticker.trim().toUpperCase(),
          quantity: Number(f.quantity),
          entry_price: f.entry_price,
          horizon_days: Number(f.horizon_days),
          quoted_spread_bps: f.spread === "" ? null : Number(f.spread),
        }),
      );
      if (r) setOut(r);
    } catch (x) {
      setOut(null);
      setErr(x instanceof ApiError ? x.message : "Could not compute costs");
    } finally {
      setBusy(false);
    }
  }

  const field = (key: keyof typeof f, label: string, props: React.InputHTMLAttributes<HTMLInputElement> = {}) => (
    <label className="flex flex-col gap-1">
      <span className="text-xs text-muted">{label}</span>
      <input className="w-32 rounded border border-line bg-surface px-2 py-1 font-mono" value={f[key]} onChange={(e) => setF({ ...f, [key]: e.target.value })} {...props} />
    </label>
  );

  return (
    <section className="mb-4 rounded-lg border border-line bg-panel p-5">
      <h3 className="mb-3 text-xs font-semibold uppercase tracking-wider text-muted">Cost calculator</h3>
      <form onSubmit={run} className="flex flex-wrap items-end gap-3 text-sm">
        {field("ticker", "Ticker", { required: true })}
        {field("quantity", "Quantity", { inputMode: "numeric", pattern: "[0-9]+", required: true })}
        {field("entry_price", "Entry price (₹)", { inputMode: "decimal", required: true })}
        {field("horizon_days", "Holding (trading days)", { inputMode: "numeric", pattern: "[0-9]+", required: true })}
        {field("spread", "Quoted spread (bps, optional)", { inputMode: "decimal" })}
        <button className="rounded bg-ink px-3 py-1.5 text-surface disabled:opacity-40" disabled={busy} type="submit">
          {busy ? "Computing…" : "Compute"}
        </button>
      </form>
      {err && <p className="mt-3 text-sm text-fail">{err}</p>}
      {out && (
        <div className="mt-4 grid gap-4 md:grid-cols-2">
          <div className="grid grid-cols-2 gap-3 text-sm">
            {[
              ["Order value", inr(out.order_value)],
              ["Round trip", `${(out.round_trip_fraction * 100).toFixed(3)}% · ${inr(out.round_trip_fraction * out.order_value)}`],
              ["Buy side", `${out.buy_bps.toFixed(1)} bps`],
              ["Sell side", `${out.sell_bps.toFixed(1)} bps`],
              ["Market impact (each side)", `${out.impact_bps_each_side.toFixed(1)} bps`],
              ["Share of daily traded value", out.participation_pct_of_adv === null ? "—" : `${out.participation_pct_of_adv.toFixed(3)}%`],
            ].map(([k, v]) => (
              <div key={k}><div className="text-xs text-muted">{k}</div><div className="font-mono">{v}</div></div>
            ))}
          </div>
          <table className="w-full text-xs">
            <tbody>
              {Object.entries(out.items_bps).map(([k, v]) => (
                <tr key={k} className="border-t border-line first:border-0">
                  <td className="py-1 pr-3">{k.replaceAll("_", " ")}</td>
                  <td className="py-1 text-right font-mono">{v.toFixed(2)} bps</td>
                </tr>
              ))}
            </tbody>
          </table>
          <p className="text-xs text-muted md:col-span-2">Schedule “{out.schedule}”. {out.notice}</p>
        </div>
      )}
    </section>
  );
}
