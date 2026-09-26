import type { Financials } from "@/lib/api";

const crore = new Intl.NumberFormat("en-IN", { maximumFractionDigits: 0 });
const pct = (v: number | null | undefined) => (v === null || v === undefined ? "—" : `${(v * 100).toFixed(1)}%`);
const num = (v: number | null | undefined, d = 2) => (v === null || v === undefined ? "—" : v.toFixed(d));
const cr = (v: number | undefined) => (v === undefined ? "—" : `₹${crore.format(v / 1e7)} cr`);

const ROWS: { label: string; get: (p: Financials["annual"][number]) => string }[] = [
  { label: "Revenue", get: (p) => cr(p.values.revenue) },
  { label: "Revenue growth", get: (p) => pct(p.ratios.revenue_growth) },
  { label: "Net income", get: (p) => cr(p.values.net_income) },
  { label: "EPS (diluted)", get: (p) => num(p.ratios.eps) },
  { label: "Operating margin", get: (p) => pct(p.ratios.operating_margin) },
  { label: "ROE", get: (p) => pct(p.ratios.roe) },
  { label: "ROCE", get: (p) => pct(p.ratios.roce) },
  { label: "Debt / equity", get: (p) => num(p.ratios.debt_to_equity) },
  { label: "Interest coverage", get: (p) => (p.ratios.interest_coverage == null ? "—" : `${p.ratios.interest_coverage.toFixed(1)}x`) },
  { label: "FCF / net income", get: (p) => pct(p.ratios.fcf_conversion) },
];

export function FinancialsTable({ data }: { data: Financials | null }) {
  if (!data) return null;
  if (!data.annual.length) {
    return <p className="mb-4 text-sm text-muted">No financial statements stored yet. Use “Fetch financials”.</p>;
  }
  const periods = data.annual.slice(-4);
  return (
    <div className="mb-4">
      {data.notice && (
        <p className="mb-2 text-xs text-unknown"><span aria-hidden>! </span>{data.notice}</p>
      )}
      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead className="text-left text-xs text-muted">
            <tr>
              <th className="py-1.5 pr-3 font-normal">Fiscal year ending</th>
              {periods.map((p) => (
                <th key={p.period_end} className="py-1.5 pr-3 text-right font-mono font-normal">{p.period_end}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {ROWS.map((r) => (
              <tr key={r.label} className="border-t border-line">
                <td className="py-1.5 pr-3 text-muted">{r.label}</td>
                {periods.map((p) => (
                  <td key={p.period_end} className="py-1.5 pr-3 text-right font-mono text-xs">{r.get(p)}</td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p className="mt-1 text-[11px] text-muted">Source: {data.sources.join(", ")} · INR crore = 10 million</p>
    </div>
  );
}
