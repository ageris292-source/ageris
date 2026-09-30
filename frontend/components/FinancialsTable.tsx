import type { Financials } from "@/lib/api";
import { Callout, Table, Td, Th } from "@/components/ui/core";

const crore = new Intl.NumberFormat("en-IN", { maximumFractionDigits: 0 });
const pct = (v: number | null | undefined) => (v === null || v === undefined ? "—" : `${(v * 100).toFixed(1)}%`);
const numf = (v: number | null | undefined, d = 2) => (v === null || v === undefined ? "—" : v.toFixed(d));
const cr = (v: number | undefined) => (v === undefined ? "—" : `₹${crore.format(v / 1e7)} cr`);

const ROWS: { label: string; get: (p: Financials["annual"][number]) => string }[] = [
  { label: "Revenue", get: (p) => cr(p.values.revenue) },
  { label: "Revenue growth", get: (p) => pct(p.ratios.revenue_growth) },
  { label: "Net income", get: (p) => cr(p.values.net_income) },
  { label: "EPS (diluted)", get: (p) => numf(p.ratios.eps) },
  { label: "Operating margin", get: (p) => pct(p.ratios.operating_margin) },
  { label: "Return on equity", get: (p) => pct(p.ratios.roe) },
  { label: "Return on capital employed", get: (p) => pct(p.ratios.roce) },
  { label: "Debt / equity", get: (p) => numf(p.ratios.debt_to_equity) },
  { label: "Interest coverage", get: (p) => (p.ratios.interest_coverage == null ? "—" : `${p.ratios.interest_coverage.toFixed(1)}×`) },
  { label: "FCF / net income", get: (p) => pct(p.ratios.fcf_conversion) },
];

export function FinancialsTable({ data }: { data: Financials | null }) {
  if (!data) return null;
  if (!data.annual.length) {
    return <p className="text-sm text-muted">No financial statements stored yet. Use “Fetch financials”.</p>;
  }
  const periods = data.annual.slice(-4);
  return (
    <div>
      {data.notice && <Callout tone="warn" className="mb-4">{data.notice}</Callout>}
      <Table>
        <thead>
          <tr>
            <Th>Fiscal year ending</Th>
            {periods.map((p) => (
              <Th key={p.period_end} align="right">{p.period_end}</Th>
            ))}
          </tr>
        </thead>
        <tbody>
          {ROWS.map((r) => (
            <tr key={r.label}>
              <Td className="text-muted">{r.label}</Td>
              {periods.map((p) => (
                <Td key={p.period_end} align="right" mono>{r.get(p)}</Td>
              ))}
            </tr>
          ))}
        </tbody>
      </Table>
      <p className="mt-2 text-[11px] text-subtle">Source: {data.sources.join(", ")} · 1 crore = 10 million rupees</p>
    </div>
  );
}
