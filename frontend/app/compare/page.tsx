"use client";

import { GitCompareArrows, Plus, Table2, X } from "lucide-react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useEffect, useMemo, useState } from "react";
import { IndexedLineChart } from "@/components/charts";
import { usePageTitle } from "@/components/usePageTitle";
import { useSession } from "@/components/providers/SessionProvider";
import { StanceBadge } from "@/components/ui/Status";
import { Button, Card, EmptyState, Input, LoadingRows, PageHeader, Segmented, Table, Td, Th, cx } from "@/components/ui/core";
import { api, type AnalysisReport, type Financials, type PriceSeries, type StockSummary } from "@/lib/api";
import { inr, istDate, num, pct, signedPct, toneOf } from "@/lib/format";

const MAX = 3; // three series keep every colour pair legible (see charts.tsx)
const RANGES = [
  { key: "3M", days: 92 },
  { key: "6M", days: 183 },
  { key: "1Y", days: 366 },
  { key: "3Y", days: 3 * 366 },
] as const;
type RangeKey = (typeof RANGES)[number]["key"];

interface Loaded {
  series: PriceSeries | null;
  report: AnalysisReport | null;
  fin: Financials | null;
}

function stats(series: PriceSeries | null) {
  const closes = (series?.bars ?? []).map((b) => Number(b.close)).filter((v) => Number.isFinite(v) && v > 0);
  if (closes.length < 2) return { ret: null, vol: null, dd: null, sessions: closes.length };
  const rets: number[] = [];
  for (let i = 1; i < closes.length; i++) rets.push(Math.log(closes[i] / closes[i - 1]));
  const mean = rets.reduce((a, b) => a + b, 0) / rets.length;
  const sd = Math.sqrt(rets.reduce((a, b) => a + (b - mean) ** 2, 0) / Math.max(1, rets.length - 1));
  let peak = closes[0];
  let dd = 0;
  for (const c of closes) {
    peak = Math.max(peak, c);
    dd = Math.min(dd, c / peak - 1);
  }
  return { ret: closes[closes.length - 1] / closes[0] - 1, vol: sd * Math.sqrt(252), dd, sessions: closes.length };
}

const RATIO_ROWS: { key: string; label: string; fmt: (v: number) => string }[] = [
  { key: "revenue_growth", label: "Revenue growth (last FY)", fmt: (v) => signedPct(v) },
  { key: "operating_margin", label: "Operating margin", fmt: (v) => pct(v) },
  { key: "net_margin", label: "Net margin", fmt: (v) => pct(v) },
  { key: "roe", label: "Return on equity", fmt: (v) => pct(v) },
  { key: "roce", label: "Return on capital employed", fmt: (v) => pct(v) },
  { key: "debt_to_equity", label: "Debt / equity", fmt: (v) => num(v, 2) },
  { key: "interest_coverage", label: "Interest coverage", fmt: (v) => `${num(v, 1)}×` },
];

function ComparePageInner() {
  usePageTitle("Compare stocks");
  const { guard, token } = useSession();
  const router = useRouter();
  const params = useSearchParams();
  const picked = useMemo(
    () =>
      (params.get("t") ?? "")
        .split(",")
        .map((s) => s.trim().toUpperCase())
        .filter(Boolean)
        .filter((v, i, a) => a.indexOf(v) === i)
        .slice(0, MAX),
    [params],
  );
  const [range, setRange] = useState<RangeKey>("1Y");
  const [stocks, setStocks] = useState<StockSummary[] | null>(null);
  const [adding, setAdding] = useState("");
  const [data, setData] = useState<Record<string, Loaded>>({});
  const [table, setTable] = useState(false);

  const setPicked = (list: string[]) => {
    const q = list.length ? `?t=${list.map(encodeURIComponent).join(",")}` : "";
    router.replace(`/compare${q}`, { scroll: false });
  };

  useEffect(() => {
    if (!token) return;
    guard((t) => api.stocks(t))
      .then((r) => r && setStocks(r))
      .catch(() => setStocks([]));
  }, [guard, token]);

  // Default: the first two stocks in the universe, so the page is never blank.
  useEffect(() => {
    if (picked.length === 0 && stocks && stocks.length >= 2 && !params.get("t")) setPicked(stocks.slice(0, 2).map((s) => s.ticker));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [stocks]);

  const days = RANGES.find((r) => r.key === range)!.days;
  useEffect(() => {
    if (!token || picked.length === 0) return;
    let stop = false;
    const end = new Date().toISOString().slice(0, 10);
    const start = new Date(Date.now() - days * 86400_000).toISOString().slice(0, 10);
    for (const tk of picked) {
      Promise.all([
        guard((t) => api.prices(t, tk, "split_adjusted", start, end)).catch(() => null),
        guard((t) => api.latestAnalysis(t, tk)).catch(() => null),
        guard((t) => api.financials(t, tk)).catch(() => null),
      ]).then(([series, report, fin]) => {
        if (!stop) setData((d) => ({ ...d, [tk]: { series: series ?? null, report: report ?? null, fin: fin ?? null } }));
      });
    }
    return () => {
      stop = true;
    };
  }, [guard, token, picked, days]);

  const ready = picked.every((t) => data[t]);

  // Align on common sessions and index each to 100 at the first common one.
  const chart = useMemo(() => {
    if (!ready || picked.length === 0) return [];
    const maps = picked.map((t) => new Map((data[t].series?.bars ?? []).map((b) => [b.session, Number(b.close)])));
    const sessions = [...(maps[0]?.keys() ?? [])].filter((s) => maps.every((m) => m.has(s))).sort();
    if (sessions.length < 2) return [];
    const base = maps.map((m) => m.get(sessions[0])!);
    return sessions.map((s) => {
      const row: Record<string, number | string | null> = { t: s };
      picked.forEach((tk, i) => {
        row[tk] = (maps[i].get(s)! / base[i]) * 100;
      });
      return row;
    });
  }, [ready, picked, data]);

  const summary = (tk: string) => stocks?.find((s) => s.ticker === tk);
  const st = (tk: string) => stats(data[tk]?.series ?? null);
  const lastRatios = (tk: string) => {
    const a = data[tk]?.fin?.annual ?? [];
    return a.length ? a[a.length - 1] : null;
  };

  const add = (e: React.FormEvent) => {
    e.preventDefault();
    const t = adding.trim().toUpperCase();
    if (!t || picked.includes(t) || picked.length >= MAX) return;
    setPicked([...picked, t]);
    setAdding("");
  };

  const row = (label: React.ReactNode, cell: (tk: string) => React.ReactNode, hint?: string) => (
    <tr key={String(label)}>
      <th scope="row" title={hint} className="min-w-[8.5rem] border-b border-line py-2 pl-4 pr-3 text-left text-xs font-normal text-muted sm:pl-5">
        {label}
      </th>
      {picked.map((tk) => (
        <Td key={tk} align="right" mono>
          {data[tk] ? cell(tk) : "…"}
        </Td>
      ))}
    </tr>
  );

  return (
    <div className="space-y-6">
      <PageHeader title="Compare stocks" description={`Put up to ${MAX} stocks side by side: price performance, risk, research stance and fundamentals. Only stored data is shown; a gap is shown as “—”.`} />

      <Card>
        <div className="flex flex-col gap-3 lg:flex-row lg:items-center">
          <div className="flex flex-wrap gap-2">
            {picked.map((tk) => (
              <span key={tk} className="inline-flex h-10 items-center gap-1 rounded-full border border-line bg-sunken pl-3.5 pr-1 font-mono text-sm font-semibold sm:h-8 sm:text-xs">
                {tk}
                <button type="button" aria-label={`Remove ${tk}`} onClick={() => setPicked(picked.filter((x) => x !== tk))} className="-my-1 flex h-10 w-10 items-center justify-center rounded-full text-muted hover:bg-hover hover:text-ink sm:my-0 sm:h-6 sm:w-6">
                  <X size={14} />
                </button>
              </span>
            ))}
          </div>
          {picked.length < MAX && (
            <form onSubmit={add} className="flex gap-2 lg:ml-2">
              <Input list="compare-stocks" value={adding} onChange={(e) => setAdding(e.target.value)} placeholder="Add a stock…" aria-label="Add a stock to compare" className="font-mono uppercase lg:w-48" />
              <datalist id="compare-stocks">
                {(stocks ?? [])
                  .filter((s) => !picked.includes(s.ticker))
                  .map((s) => (
                    <option key={s.ticker} value={s.ticker}>
                      {s.name ?? ""}
                    </option>
                  ))}
              </datalist>
              <Button type="submit" icon={<Plus size={15} />} disabled={!adding.trim()}>
                Add
              </Button>
            </form>
          )}
          <div className="lg:ml-auto">
            <Segmented<RangeKey> label="Time range" value={range} onChange={setRange} options={RANGES.map((r) => ({ value: r.key, label: r.key }))} />
          </div>
        </div>
      </Card>

      {picked.length < 2 ? (
        <Card>
          <EmptyState icon={<GitCompareArrows size={20} />} title="Pick at least two stocks" body="Add stocks above. The universe is managed on the Stocks page." />
        </Card>
      ) : (
        <>
          <Card
            title="Price performance"
            description={chart.length ? `Indexed to 100 on ${istDate(String(chart[0].t))}, the first session all ${picked.length} have. Split-adjusted closes.` : undefined}
            actions={
              <Button size="sm" variant="ghost" icon={<Table2 size={14} />} aria-pressed={table} onClick={() => setTable((v) => !v)}>
                {table ? "Chart" : "Table"}
              </Button>
            }
          >
            {!ready ? (
              <LoadingRows rows={6} />
            ) : chart.length < 2 ? (
              <EmptyState compact title="Not enough overlapping price history" body="Fetch prices for these stocks on their pages, or pick a shorter range." />
            ) : table ? (
              <div className="max-h-[420px] overflow-auto">
                <Table className="!mx-0">
                  <thead className="sticky top-0 bg-panel">
                    <tr>
                      <Th>Session</Th>
                      {picked.map((tk) => (
                        <Th key={tk} align="right">{tk}</Th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {[...chart].reverse().map((r) => (
                      <tr key={String(r.t)}>
                        <Td mono>{String(r.t)}</Td>
                        {picked.map((tk) => (
                          <Td key={tk} align="right" mono>{num(r[tk] as number, 1)}</Td>
                        ))}
                      </tr>
                    ))}
                  </tbody>
                </Table>
              </div>
            ) : (
              <IndexedLineChart data={chart} series={picked.map((tk) => ({ key: tk, label: tk }))} height={300} />
            )}
          </Card>

          <Card title="Side by side" bodyClassName="pb-2">
            <Table>
              <thead>
                <tr>
                  <Th />
                  {picked.map((tk) => (
                    <Th key={tk} align="right">
                      <Link href={`/stocks/${encodeURIComponent(tk)}`} className="-my-3 inline-block py-3 font-mono font-semibold text-ink hover:text-accent">
                        {tk}
                      </Link>
                    </Th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {row("Name", (tk) => <span className="font-sans text-xs">{summary(tk)?.name ?? "—"}</span>)}
                {row("Last close", (tk) => inr(summary(tk)?.last_close))}
                {row("Day change", (tk) => <span className={toneOf(summary(tk)?.change_pct)}>{signedPct(summary(tk)?.change_pct)}</span>)}
                {row(`Return (${range})`, (tk) => <span className={toneOf(st(tk).ret)}>{signedPct(st(tk).ret)}</span>)}
                {row("Volatility (annualised)", (tk) => pct(st(tk).vol), "Standard deviation of daily log returns × √252")}
                {row(`Max drawdown (${range})`, (tk) => <span className={cx(st(tk).dd ? "text-fail" : "")}>{st(tk).dd === null ? "—" : signedPct(st(tk).dd)}</span>)}
                {row("Research stance", (tk) => (data[tk]?.report ? <StanceBadge stance={data[tk].report!.synthesis.stance} /> : <span className="font-sans text-xs text-subtle">No report</span>))}
                {row("Composite score", (tk) => num(data[tk]?.report?.synthesis.composite_score, 2))}
                {row("Confidence", (tk) => (data[tk]?.report ? pct(data[tk].report!.synthesis.confidence, 0) : "—"))}
                {RATIO_ROWS.map((r) =>
                  row(r.label, (tk) => {
                    const v = lastRatios(tk)?.ratios[r.key];
                    return v === null || v === undefined ? "—" : r.fmt(v);
                  }),
                )}
                {row("Latest fiscal year", (tk) => (lastRatios(tk) ? istDate(lastRatios(tk)!.period_end) : "—"))}
              </tbody>
            </Table>
            <p className="mt-3 text-xs text-subtle">Research stance and scores come from each stock&apos;s latest stored report and may be from different dates. Comparisons are for research only; they are not recommendations.</p>
          </Card>
        </>
      )}
    </div>
  );
}

export default function ComparePage() {
  return (
    <Suspense fallback={<LoadingRows rows={6} />}>
      <ComparePageInner />
    </Suspense>
  );
}
