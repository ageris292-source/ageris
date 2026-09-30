"use client";

import type { ValuationDetails as Details } from "@/lib/api";
import { Callout, SectionLabel, Table, Td, Th, cx } from "@/components/ui/core";
import { inr, pct } from "@/lib/format";

export function ValuationDetails({ d }: { d: Details | null }) {
  if (!d) return null;
  const sc = d.scenarios;
  return (
    <div className="space-y-6">
      {sc ? (
        <div>
          {d.dcf_reliable === false && (
            <Callout tone="warn" className="mb-4">DCF shown for reference only — it failed the reliability guard and is not scored.</Callout>
          )}
          <div className="mb-4 grid grid-cols-3 gap-3">
            {(["bear", "base", "bull"] as const).map((k) => {
              const s = sc[k];
              if (!s) return <div key={k} />;
              return (
                <div key={k} className={cx("rounded-lg border p-3", k === "base" ? "border-accent/40 bg-accent-soft" : "border-line")}>
                  <div className="text-xs capitalize text-muted">{k} case</div>
                  <div className="mt-1 text-lg font-semibold tabular-nums">{inr(s.per_share, 0)}</div>
                  <div className={cx("text-xs font-medium", s.margin_of_safety >= 0 ? "text-pass" : "text-fail")}>
                    {s.margin_of_safety >= 0 ? "+" : ""}
                    {pct(s.margin_of_safety, 0)} vs price
                  </div>
                </div>
              );
            })}
          </div>
          <Table>
            <thead>
              <tr>
                {["Scenario", "Growth", "FCF margin", "WACC", "Terminal g", "Terminal % of EV"].map((h, i) => (
                  <Th key={h} align={i ? "right" : "left"}>{h}</Th>
                ))}
              </tr>
            </thead>
            <tbody>
              {(["bear", "base", "bull"] as const).map((k) => {
                const s = sc[k];
                if (!s) return null;
                return (
                  <tr key={k}>
                    <Td className="capitalize">{k}</Td>
                    <Td align="right" mono>{pct(s.assumptions.growth)}</Td>
                    <Td align="right" mono>{pct(s.assumptions.fcf_margin)}</Td>
                    <Td align="right" mono>{pct(s.assumptions.wacc)}</Td>
                    <Td align="right" mono>{pct(s.assumptions.terminal_growth)}</Td>
                    <Td align="right" mono>{pct(s.terminal_share_of_ev, 0)}</Td>
                  </tr>
                );
              })}
            </tbody>
          </Table>
          <p className="mt-3 text-xs text-muted">
            Price {inr(d.price, 0)} on {d.price_date ?? "—"} · beta {d.beta_used?.toFixed(2) ?? "—"} ({d.beta_weeks ?? 0} weeks vs NIFTY 50) · tax {pct(d.tax_rate)} · revenue CAGR {pct(d.revenue_cagr)}. Model estimates under stated assumptions — not price targets.
          </p>
        </div>
      ) : (
        <p className="text-sm text-muted">No DCF scenarios for this stock (see warnings).</p>
      )}

      {d.sensitivity && (
        <div>
          <SectionLabel>Base-case sensitivity (₹ per share)</SectionLabel>
          <div className="overflow-x-auto">
            <table className="text-xs">
              <thead>
                <tr>
                  <th className="px-2 py-1.5 text-left font-medium text-muted">WACC ↓ · growth →</th>
                  {d.sensitivity.growth_deltas.map((g) => (
                    <th key={g} className="px-2 py-1.5 text-right font-medium text-muted">{g >= 0 ? "+" : ""}{(g * 100).toFixed(0)}pp</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {d.sensitivity.per_share.map((row, i) => (
                  <tr key={i} className="border-t border-line">
                    <td className="px-2 py-1.5 text-muted">
                      {d.sensitivity!.wacc_deltas[i] >= 0 ? "+" : ""}
                      {(d.sensitivity!.wacc_deltas[i] * 100).toFixed(0)}pp
                    </td>
                    {row.map((v, j) => {
                      const base = d.sensitivity!.wacc_deltas[i] === 0 && d.sensitivity!.growth_deltas[j] === 0;
                      const above = v !== null && d.price !== undefined && v >= d.price;
                      return (
                        <td key={j} className={cx("px-2 py-1.5 text-right font-mono", base && "font-semibold", v === null ? "text-subtle" : above ? "text-pass" : "text-fail")}>
                          {v === null ? "—" : inr(v, 0)}
                        </td>
                      );
                    })}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <p className="mt-2 text-[11px] text-subtle">Green: at or above today&apos;s price · red: below · bold: base case.</p>
        </div>
      )}
    </div>
  );
}
