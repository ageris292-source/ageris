"use client";

import { Download, Trophy } from "lucide-react";
import Link from "next/link";
import { useEffect, useState } from "react";
import { IndexedLineChart } from "@/components/charts";
import { useSession } from "@/components/providers/SessionProvider";
import { useToast } from "@/components/providers/ToastProvider";
import { Button, Card, DesktopOnly, EmptyState, LoadingRows, MobileItem, MobileList, StatCard, Table, Td, Th, cx } from "@/components/ui/core";
import { api, ApiError, type ExportKind, type PaperPerformance } from "@/lib/api";
import { num, pct, signedInr, signedPct, toneOf } from "@/lib/format";

const EXPORTS: { kind: ExportKind; label: string }[] = [
  { kind: "orders", label: "Orders" },
  { kind: "fills", label: "Fills" },
  { kind: "positions", label: "Positions" },
  { kind: "equity", label: "Equity curve" },
];

export function PaperPerformanceView({ pid }: { pid: number }) {
  const { guard, token } = useSession();
  const toast = useToast();
  const [p, setP] = useState<PaperPerformance | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState<ExportKind | null>(null);

  useEffect(() => {
    if (!token) return;
    setP(null);
    guard((t) => api.paperPerformance(t, pid))
      .then((r) => r && setP(r))
      .catch((e) => setErr(e instanceof Error ? e.message : "Could not load performance"));
  }, [guard, token, pid]);

  if (err) return <Card><p className="text-sm text-fail">{err}</p></Card>;
  if (!p) return <Card><LoadingRows rows={5} /></Card>;

  const t = p.trades;
  const bench = p.benchmark;
  const benchLabel = bench.series === "nifty50" ? "NIFTY 50" : bench.series;
  const chart = p.curve.map((c) => ({ t: c.date, portfolio: c.portfolio_index, benchmark: c.benchmark_index }));

  return (
    <div className="space-y-6">
      <div className="grid grid-cols-2 gap-3 md:grid-cols-3 xl:grid-cols-6">
        <StatCard label="Win rate" value={t.win_rate === null ? "—" : pct(t.win_rate, 0)} sub={t.closed ? `${t.wins} of ${t.closed} closed trades` : "No closed trades yet"} />
        <StatCard label="Profit factor" value={t.profit_factor === null ? "—" : num(t.profit_factor, 2)} sub="Gross wins ÷ gross losses" />
        <StatCard label="Avg win / loss" value={<span className="text-lg sm:text-xl">{t.avg_win === null ? "—" : signedInr(t.avg_win)} <span className="text-subtle">/</span> {t.avg_loss === null ? "—" : signedInr(t.avg_loss)}</span>} />
        <StatCard label="Max drawdown" value={p.equity.max_drawdown === null ? "—" : signedPct(p.equity.max_drawdown)} tone={p.equity.max_drawdown ? "text-fail" : undefined} sub="Worst fall from a peak" />
        <StatCard label="Total return" value={signedPct(p.equity.total_return)} tone={toneOf(p.equity.total_return)} sub="After fees" />
        <StatCard
          label={`vs ${benchLabel}`}
          value={bench.excess_return === null ? "—" : signedPct(bench.excess_return)}
          tone={toneOf(bench.excess_return)}
          sub={
            bench.return !== null
              ? `${benchLabel} ${signedPct(bench.return)}`
              : p.equity.points < 2
                ? "Needs equity history first"
                : bench.available
                  ? "Not enough overlap"
                  : `${benchLabel} data not stored`
          }
        />
      </div>

      <Card
        title={`Portfolio vs ${benchLabel}`}
        description={`Both indexed to 100 at the start. ${benchLabel} comes from the stored macro series; if it isn't stored, only the portfolio is shown.`}
      >
        {chart.length > 1 ? (
          <IndexedLineChart
            data={chart}
            series={[
              { key: "portfolio", label: p.portfolio.name },
              ...(bench.available ? [{ key: "benchmark", label: benchLabel }] : []),
            ]}
          />
        ) : (
          <EmptyState compact title="Not enough history yet" body="The comparison appears after the first end-of-day marks." />
        )}
      </Card>

      <div className="grid gap-6 xl:grid-cols-3">
        <Card className="xl:col-span-2" title="Realised P&L by stock" description="Closed (sold) trades only." bodyClassName="pb-2">
          {p.by_ticker.length === 0 ? (
            <EmptyState compact icon={<Trophy size={20} />} title="No closed trades yet" />
          ) : (
            <>
              <MobileList className="mb-2">
                {p.by_ticker.map((r) => (
                  <MobileItem key={r.ticker} href={`/stocks/${encodeURIComponent(r.ticker)}`}>
                    <div className="flex items-center justify-between">
                      <div>
                        <p className="font-mono text-[13px] font-semibold">{r.ticker}</p>
                        <p className="text-xs text-muted">{r.wins}/{r.trades} winners</p>
                      </div>
                      <p className={cx("font-mono text-sm", toneOf(r.realised_pnl))}>{signedInr(r.realised_pnl)}</p>
                    </div>
                  </MobileItem>
                ))}
              </MobileList>
              <DesktopOnly>
                <Table>
                  <thead>
                    <tr>
                      <Th>Stock</Th>
                      <Th align="right">Closed trades</Th>
                      <Th align="right">Winners</Th>
                      <Th align="right">Realised</Th>
                    </tr>
                  </thead>
                  <tbody>
                    {p.by_ticker.map((r) => (
                      <tr key={r.ticker} className="hover:bg-hover">
                        <Td>
                          <Link href={`/stocks/${encodeURIComponent(r.ticker)}`} className="font-mono text-[13px] font-semibold hover:underline">
                            {r.ticker}
                          </Link>
                        </Td>
                        <Td align="right" mono>{r.trades}</Td>
                        <Td align="right" mono>{r.wins}</Td>
                        <Td align="right" mono className={toneOf(r.realised_pnl)}>{signedInr(r.realised_pnl)}</Td>
                      </tr>
                    ))}
                  </tbody>
                </Table>
              </DesktopOnly>
            </>
          )}
          <p className="mt-2 text-xs text-subtle">
            Best {t.best === null ? "—" : signedInr(t.best)} · worst {t.worst === null ? "—" : signedInr(t.worst)} · fees paid {signedInr(-t.fees_paid)}
          </p>
        </Card>

        <Card title="Download" description="CSV files for this portfolio.">
          <div className="grid grid-cols-2 gap-2">
            {EXPORTS.map((x) => (
              <Button
                key={x.kind}
                icon={<Download size={14} />}
                loading={busy === x.kind}
                onClick={async () => {
                  setBusy(x.kind);
                  try {
                    await guard((tk) => api.exportCsv(tk, x.kind, { portfolio_id: pid }));
                  } catch (e) {
                    toast({ tone: "error", title: "Export failed", body: e instanceof ApiError ? e.message : undefined });
                  } finally {
                    setBusy(null);
                  }
                }}
              >
                {x.label}
              </Button>
            ))}
          </div>
          <p className="mt-3 text-xs text-subtle">Past paper results do not predict future returns. Paper fills are simulated.</p>
        </Card>
      </div>
    </div>
  );
}
