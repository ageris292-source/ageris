"use client";

import type { ValuationDetails as Details } from "@/lib/api";

const inr = new Intl.NumberFormat("en-IN", { maximumFractionDigits: 0 });
const pct = (v: number | null | undefined, d = 1) =>
  v === null || v === undefined ? "—" : `${(v * 100).toFixed(d)}%`;

export function ValuationDetails({ d }: { d: Details | null }) {
  if (!d) return null;
  const sc = d.scenarios;
  return (
    <div className="mt-4 space-y-4 text-sm">
      {sc ? (
        <>
          {d.dcf_reliable === false && (
            <p className="text-xs text-unknown">
              DCF shown for reference only — it failed the reliability guard and is not scored.
            </p>
          )}
          <div className="overflow-x-auto">
            <table className="w-full font-mono text-xs">
              <thead className="text-left text-muted">
                <tr>
                  {["Scenario", "Value / share", "vs price", "Growth", "FCF margin", "WACC", "Terminal g", "TV % EV"].map((h) => (
                    <th key={h} className="py-1 pr-3 font-normal">{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {(["bear", "base", "bull"] as const).map((k) => {
                  const s = sc[k];
                  if (!s) return null;
                  return (
                    <tr key={k} className="border-t border-line">
                      <td className="py-1 pr-3 capitalize">{k}</td>
                      <td className="py-1 pr-3">₹{inr.format(s.per_share)}</td>
                      <td className={`py-1 pr-3 ${s.margin_of_safety >= 0 ? "text-pass" : "text-fail"}`}>
                        {s.margin_of_safety >= 0 ? "+" : ""}{pct(s.margin_of_safety, 0)}
                      </td>
                      <td className="py-1 pr-3">{pct(s.assumptions.growth)}</td>
                      <td className="py-1 pr-3">{pct(s.assumptions.fcf_margin)}</td>
                      <td className="py-1 pr-3">{pct(s.assumptions.wacc)}</td>
                      <td className="py-1 pr-3">{pct(s.assumptions.terminal_growth)}</td>
                      <td className="py-1 pr-3">{pct(s.terminal_share_of_ev, 0)}</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
          <p className="text-xs text-muted">
            Price ₹{d.price !== undefined ? inr.format(d.price) : "—"} on {d.price_date ?? "—"} · beta{" "}
            {d.beta_used?.toFixed(2) ?? "—"} ({d.beta_weeks ?? 0} weeks vs NIFTY 50) · tax {pct(d.tax_rate)} ·
            revenue CAGR {pct(d.revenue_cagr)}. Model estimates under stated assumptions, not price targets.
          </p>
        </>
      ) : (
        <p className="text-xs text-muted">No DCF scenarios for this stock (see warnings above).</p>
      )}

      {d.sensitivity && (
        <div>
          <h4 className="mb-1 text-xs font-semibold uppercase tracking-wider text-muted">
            Base-case sensitivity (₹ / share)
          </h4>
          <table className="font-mono text-xs">
            <thead className="text-muted">
              <tr>
                <th className="py-1 pr-3 text-left font-normal">WACC \ g</th>
                {d.sensitivity.growth_deltas.map((g) => (
                  <th key={g} className="py-1 pr-3 font-normal">{g >= 0 ? "+" : ""}{(g * 100).toFixed(0)}pp</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {d.sensitivity.per_share.map((row, i) => (
                <tr key={i} className="border-t border-line">
                  <td className="py-1 pr-3 text-muted">
                    {d.sensitivity!.wacc_deltas[i] >= 0 ? "+" : ""}
                    {(d.sensitivity!.wacc_deltas[i] * 100).toFixed(0)}pp
                  </td>
                  {row.map((v, j) => (
                    <td key={j} className="py-1 pr-3 text-right">{v === null ? "—" : inr.format(v)}</td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
