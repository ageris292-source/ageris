"use client";

import { ArrowLeft, CheckCircle2, CircleHelp, RefreshCw, ShieldCheck, Table2, TriangleAlert, XCircle } from "lucide-react";
import Link from "next/link";
import { useParams } from "next/navigation";
import { useCallback, useEffect, useState } from "react";
import { AgentPanel } from "@/components/AgentPanel";
import { FinancialsTable } from "@/components/FinancialsTable";
import { NewsList } from "@/components/NewsList";
import { PriceChart } from "@/components/PriceChart";
import { ReportDetails, ReportHistory, ResearchSummary } from "@/components/ReportPanel";
import { CsvImportCard, ModelEstimateCard } from "@/components/StockExtras";
import { usePageTitle } from "@/components/usePageTitle";
import { ValuationDetails } from "@/components/ValuationDetails";
import { useWatchlist, WatchStar } from "@/components/Watchlist";
import { useSession } from "@/components/providers/SessionProvider";
import { useToast } from "@/components/providers/ToastProvider";
import { FreshnessBadge, QualityBadge } from "@/components/ui/Status";
import {
  Button,
  Callout,
  Card,
  EmptyState,
  KeyValues,
  LinkButton,
  Segmented,
  Skeleton,
  Table,
  Tabs,
  Td,
  Th,
  cx,
} from "@/components/ui/core";
import {
  api,
  ApiError,
  type AgentOutput,
  type AnalysisReport,
  type Basis,
  type Financials,
  type IndicatorSeries,
  type ModelEstimate,
  type NewsItem,
  type PriceSeries,
  type ReportHistoryRow,
  type StockDetail,
  type Valuation,
} from "@/lib/api";
import { compact, humanize, inr, istDate, istDateTime, signedPct, toneOf } from "@/lib/format";

const RANGES = [
  { key: "1M", days: 31 },
  { key: "3M", days: 92 },
  { key: "6M", days: 183 },
  { key: "1Y", days: 366 },
  { key: "5Y", days: 5 * 366 },
] as const;
type RangeKey = (typeof RANGES)[number]["key"];

type TabKey = "overview" | "technical" | "fundamentals" | "news" | "valuation" | "risk" | "data";

function isoMinusDays(iso: string, days: number) {
  const d = new Date(iso + "T00:00:00Z");
  d.setUTCDate(d.getUTCDate() - days);
  return d.toISOString().slice(0, 10);
}

export default function StockPage() {
  const ticker = decodeURIComponent(useParams<{ ticker: string }>().ticker).toUpperCase();
  usePageTitle(ticker);
  const { guard, isAdmin, token } = useSession();
  const toast = useToast();
  const { has, toggle } = useWatchlist();

  const [tab, setTab] = useState<TabKey>("overview");
  const [detail, setDetail] = useState<StockDetail | null>(null);
  const [notFound, setNotFound] = useState(false);
  const [series, setSeries] = useState<PriceSeries | null>(null);
  const [indicators, setIndicators] = useState<IndicatorSeries | null>(null);
  const [range, setRange] = useState<RangeKey>("1Y");
  const [basis, setBasis] = useState<Basis>("split_adjusted");
  const [showTable, setShowTable] = useState(false);
  const [refreshing, setRefreshing] = useState(false);

  const [report, setReport] = useState<AnalysisReport | null | undefined>(undefined);
  const [reportBusy, setReportBusy] = useState(false);
  const [est, setEst] = useState<ModelEstimate | null | undefined>(undefined);
  const [history, setHistory] = useState<ReportHistoryRow[] | null>(null);

  const [tech, setTech] = useState<AgentOutput | null>(null);
  const [fund, setFund] = useState<AgentOutput | null>(null);
  const [fin, setFin] = useState<Financials | null>(null);
  const [newsOut, setNewsOut] = useState<AgentOutput | null>(null);
  const [news, setNews] = useState<NewsItem[] | null>(null);
  const [val, setVal] = useState<Valuation | null>(null);
  const [macroOut, setMacroOut] = useState<AgentOutput | null>(null);
  const [riskOut, setRiskOut] = useState<AgentOutput | null>(null);
  const [busy, setBusy] = useState<Partial<Record<TabKey, boolean>>>({});
  const [loaded, setLoaded] = useState<Partial<Record<TabKey, boolean>>>({});

  const fail = useCallback(
    (title: string) => (err: unknown) => toast({ tone: "error", title, body: err instanceof Error ? err.message : undefined }),
    [toast],
  );

  const loadDetail = useCallback(async () => {
    try {
      const d = await guard((t) => api.stock(t, ticker));
      if (d) setDetail(d);
    } catch (err) {
      if (err instanceof ApiError && err.status === 404) setNotFound(true);
      else fail("Could not load the stock")(err);
    }
  }, [guard, ticker, fail]);

  const loadReports = useCallback(async () => {
    guard((t) => api.latestAnalysis(t, ticker))
      .then((r) => setReport(r ?? null))
      .catch(() => setReport(null)); // 404 = no report yet
    guard((t) => api.analysisHistory(t, ticker)).then((h) => h && setHistory(h)).catch(() => setHistory([]));
  }, [guard, ticker]);

  useEffect(() => {
    if (!token) return;
    void loadDetail();
    void loadReports();
    guard((t) => api.modelEstimate(t, ticker)).then((e) => setEst(e ?? null)).catch(() => setEst(null));
  }, [token, loadDetail, loadReports, guard, ticker]);

  const end = detail?.latest_session ?? null;
  useEffect(() => {
    if (!end) return;
    const start = isoMinusDays(end, RANGES.find((r) => r.key === range)!.days);
    guard((t) => api.prices(t, ticker, basis, start, end))
      .then((s) => s && setSeries(s))
      .catch((err) => {
        if (basis === "total_return") {
          toast({ tone: "warning", title: "No total-return series", body: err instanceof Error ? err.message : undefined });
          setBasis("split_adjusted");
        } else fail("Could not load prices")(err);
      });
    guard((t) => api.indicators(t, ticker, start, end)).then((s) => s && setIndicators(s)).catch(() => setIndicators(null));
  }, [guard, ticker, basis, range, end, fail, toast]);

  const runTab = useCallback(
    async (k: TabKey, fetchFirst = false) => {
      setBusy((b) => ({ ...b, [k]: true }));
      try {
        if (k === "technical") {
          const o = await guard((t) => api.technical(t, ticker));
          if (o) setTech(o);
        } else if (k === "fundamentals") {
          if (fetchFirst) {
            const run = await guard((t) => api.ingestFinancials(t, ticker));
            if (run?.status === "failed") toast({ tone: "error", title: "Financials fetch failed", body: run.error ?? undefined });
          }
          const [f, o] = await Promise.all([guard((t) => api.financials(t, ticker)), guard((t) => api.fundamental(t, ticker))]);
          if (f) setFin(f);
          if (o) setFund(o);
        } else if (k === "news") {
          if (fetchFirst) {
            const run = await guard((t) => api.ingestNews(t, ticker));
            if (run?.status === "failed") toast({ tone: "error", title: "News fetch failed", body: run.error ?? undefined });
          }
          const [items, o] = await Promise.all([guard((t) => api.news(t, ticker)), guard((t) => api.newsAgent(t, ticker))]);
          if (items) setNews(items);
          if (o) setNewsOut(o);
        } else if (k === "valuation") {
          const [v, m] = await Promise.all([guard((t) => api.valuation(t, ticker)), guard((t) => api.macroAgent(t, ticker))]);
          if (v) setVal(v);
          if (m) setMacroOut(m);
        } else if (k === "risk") {
          const o = await guard((t) => api.riskAgent(t, ticker));
          if (o) setRiskOut(o);
        }
        setLoaded((l) => ({ ...l, [k]: true }));
      } catch (err) {
        fail(`${humanize(k)} analysis failed`)(err);
      } finally {
        setBusy((b) => ({ ...b, [k]: false }));
      }
    },
    [guard, ticker, toast, fail],
  );

  useEffect(() => {
    if (detail && !loaded[tab] && !busy[tab] && tab !== "overview" && tab !== "data") void runTab(tab);
  }, [tab, detail, loaded, busy, runTab]);

  async function runReport() {
    setReportBusy(true);
    try {
      const r = await guard((t) => api.runAnalysis(t, ticker));
      if (r) {
        setReport(r);
        toast({ tone: "success", title: "Research report ready", body: `${r.synthesis.stance_text} · composite ${r.synthesis.composite_score?.toFixed(1) ?? "—"}` });
        void loadReports();
      }
    } catch (err) {
      fail("Analysis failed")(err);
    } finally {
      setReportBusy(false);
    }
  }

  async function downloadReport() {
    if (!report) return;
    const md = await guard((t) => api.reportMarkdown(t, report.report_id));
    if (!md) return;
    const url = URL.createObjectURL(new Blob([md], { type: "text/markdown" }));
    const a = document.createElement("a");
    a.href = url;
    a.download = `aegis-${ticker}-report-${report.report_id}.md`;
    a.click();
    URL.revokeObjectURL(url);
  }

  async function refresh() {
    setRefreshing(true);
    try {
      const run = await guard((t) => api.ingest(t, ticker));
      if (run) {
        const bad = run.status === "failed" || run.status === "rejected";
        toast({ tone: bad ? "error" : "success", title: `Prices ${humanize(run.status)}`, body: `${run.rows_inserted} new, ${run.rows_revised} revised${run.error ? ` — ${run.error}` : ""}` });
      }
      await loadDetail();
    } catch (err) {
      fail("Refresh failed")(err);
    } finally {
      setRefreshing(false);
    }
  }

  if (notFound) {
    return (
      <Card>
        <EmptyState
          icon={<CircleHelp size={20} />}
          title={`${ticker} isn't in the universe`}
          body={isAdmin ? "Add it from the Stocks page to start collecting data." : "Ask an admin to add it."}
          action={<LinkButton href="/stocks" icon={<ArrowLeft size={15} />}>Back to stocks</LinkButton>}
        />
      </Card>
    );
  }

  const lb = detail?.latest_bar;
  const rangeChange = (() => {
    const b = series?.bars;
    if (!b || b.length < 2) return null;
    return Number(b[b.length - 1].close) / Number(b[0].close) - 1;
  })();
  const issues = detail?.data_quality?.issues.filter((i) => i.severity !== "info") ?? [];
  const tradeHref = `/trade?ticker=${encodeURIComponent(ticker)}${lb ? `&entry=${Number(lb.close).toFixed(2)}` : ""}`;

  return (
    <div className="space-y-6">
      <div>
        <Link href="/stocks" className="inline-flex items-center gap-1 text-sm text-muted hover:text-ink">
          <ArrowLeft size={15} aria-hidden /> Stocks
        </Link>
        <div className="mt-3 flex flex-wrap items-start justify-between gap-4">
          <div className="min-w-0">
            {detail ? (
              <>
                <h1 className="text-2xl font-semibold tracking-tight">{detail.name ?? detail.ticker}</h1>
                <div className="mt-1 flex flex-wrap items-center gap-2 text-sm text-muted">
                  <span className="font-mono">{detail.ticker}</span>
                  <span aria-hidden>·</span>
                  <span>{detail.exchange}</span>
                  <FreshnessBadge f={detail.freshness} />
                  {detail.licensed === false && <span className="text-xs text-warn">research-only data</span>}
                </div>
              </>
            ) : (
              <>
                <Skeleton className="h-8 w-64" />
                <Skeleton className="mt-2 h-4 w-40" />
              </>
            )}
          </div>
          <div className="flex flex-col items-end gap-3">
            {lb ? (
              <div className="text-right">
                <div className="text-3xl font-semibold tracking-tight tabular-nums">{inr(Number(lb.close))}</div>
                <div className="mt-0.5 text-sm">
                  <span className={cx("font-medium tabular-nums", toneOf(detail?.change_pct))}>{signedPct(detail?.change_pct)}</span>
                  <span className="text-muted"> day · close {istDate(lb.session)}</span>
                </div>
              </div>
            ) : detail ? (
              <p className="text-sm text-muted">No prices stored yet</p>
            ) : (
              <Skeleton className="h-10 w-40" />
            )}
            <div className="flex flex-wrap justify-end gap-2">
              <WatchStar on={has(ticker)} ticker={ticker} onToggle={() => toggle(ticker)} withLabel />
              <Button onClick={refresh} loading={refreshing} icon={<RefreshCw size={15} />}>
                Refresh data
              </Button>
              <LinkButton href={tradeHref} variant="primary" icon={<ShieldCheck size={15} />}>
                Evaluate a trade
              </LinkButton>
            </div>
          </div>
        </div>
      </div>

      {detail?.licensing_notice && (
        <Callout tone="warn" icon={<TriangleAlert size={16} />}>
          {detail.licensing_notice}
        </Callout>
      )}

      <div>
        <Tabs<TabKey>
          label="Stock sections"
          value={tab}
          onChange={setTab}
          tabs={[
            { value: "overview", label: "Overview" },
            { value: "technical", label: "Technical" },
            { value: "fundamentals", label: "Fundamentals" },
            { value: "news", label: "News" },
            { value: "valuation", label: "Valuation & macro" },
            { value: "risk", label: "Risk" },
            { value: "data", label: "Data" },
          ]}
        />

        {tab === "overview" && (
          <div className="space-y-6">
            <div className="grid gap-6 xl:grid-cols-3">
              <Card
                className="xl:col-span-2"
                title="Price"
                description={
                  rangeChange !== null ? (
                    <span>
                      <span className={cx("font-medium", toneOf(rangeChange))}>{signedPct(rangeChange)}</span> over {range}
                    </span>
                  ) : undefined
                }
                actions={
                  <>
                    <Segmented<Basis>
                      label="Price basis"
                      value={basis}
                      onChange={setBasis}
                      options={[
                        { value: "split_adjusted", label: "Price", title: "Adjusted for splits and bonuses" },
                        { value: "total_return", label: "Total return", title: "Also reinvests dividends (derived)" },
                      ]}
                    />
                    <Segmented<RangeKey> label="Time range" value={range} onChange={setRange} options={RANGES.map((r) => ({ value: r.key, label: r.key }))} />
                    <Button size="sm" variant="ghost" onClick={() => setShowTable((v) => !v)} icon={<Table2 size={14} />} aria-pressed={showTable}>
                      {showTable ? "Chart" : "Table"}
                    </Button>
                  </>
                }
              >
                {!series && <Skeleton className="h-80" />}
                {series && !showTable && <PriceChart bars={series.bars} indicators={basis === "split_adjusted" ? indicators : null} />}
                {series && showTable && (
                  <div className="max-h-[420px] overflow-auto">
                    <Table className="!mx-0">
                      <thead className="sticky top-0 bg-panel">
                        <tr>
                          {["Session", "Open", "High", "Low", "Close", "Volume", "Ver"].map((h, i) => (
                            <Th key={h} align={i ? "right" : "left"}>{h}</Th>
                          ))}
                        </tr>
                      </thead>
                      <tbody>
                        {[...series.bars].reverse().map((b) => (
                          <tr key={b.session}>
                            <Td mono>{b.session}</Td>
                            <Td align="right" mono>{inr(b.open)}</Td>
                            <Td align="right" mono>{inr(b.high)}</Td>
                            <Td align="right" mono>{inr(b.low)}</Td>
                            <Td align="right" mono>{inr(b.close)}</Td>
                            <Td align="right" mono>{compact(b.volume)}</Td>
                            <Td align="right" mono>{b.data_version}</Td>
                          </tr>
                        ))}
                      </tbody>
                    </Table>
                  </div>
                )}
                {series && (
                  <p className="mt-3 text-xs text-subtle">
                    {series.derived
                      ? `Total-return series derived from stored ${humanize(series.stored_basis ?? "")} prices and dividends.`
                      : `Stored ${humanize(series.basis)} prices.`}{" "}
                    Source: {series.source ?? "—"}.
                  </p>
                )}
              </Card>

              <div className="space-y-6">
                <ResearchSummary report={report} busy={reportBusy} onRun={runReport} onDownload={downloadReport} />
                <ModelEstimateCard est={est} />
              </div>
            </div>

            {report && <ReportDetails report={report} />}
            <ReportHistory rows={history} />
          </div>
        )}

        {tab === "technical" && (
          <AgentPanel title="Technical analysis" description="Trend, momentum, volatility and volume rules on stored prices." scoreLabel="Technical score" out={tech} busy={!!busy.technical} onRun={() => runTab("technical")} />
        )}

        {tab === "fundamentals" && (
          <AgentPanel
            title="Fundamental analysis"
            description="Growth, profitability, balance-sheet strength and cash conversion."
            scoreLabel="Fundamental score"
            runLabel="Fetch financials & re-run"
            out={fund}
            busy={!!busy.fundamentals}
            onRun={() => runTab("fundamentals", true)}
          >
            <FinancialsTable data={fin} />
          </AgentPanel>
        )}

        {tab === "news" && (
          <AgentPanel
            title="News & sentiment"
            description="Recent headlines, de-duplicated, scored for sentiment and event type."
            scoreLabel="News sentiment"
            runLabel="Fetch news & re-run"
            out={newsOut}
            busy={!!busy.news}
            onRun={() => runTab("news", true)}
          >
            <NewsList items={news} />
          </AgentPanel>
        )}

        {tab === "valuation" && (
          <div className="space-y-6">
            <AgentPanel title="Valuation" description="Discounted cash flow under bear, base and bull assumptions." scoreLabel="Valuation score" out={val?.analysis ?? null} busy={!!busy.valuation} onRun={() => runTab("valuation")}>
              <ValuationDetails d={val?.details ?? null} />
            </AgentPanel>
            <AgentPanel title="Macro & regime fit" description="How the stock's sector sits in the current market regime." scoreLabel="Macro fit" out={macroOut} busy={!!busy.valuation} />
          </div>
        )}

        {tab === "risk" && (
          <AgentPanel title="Risk" description="Volatility, drawdown, tail risk and beta over the trailing year." scoreLabel="Risk suitability (higher = lower risk)" out={riskOut} busy={!!busy.risk} onRun={() => runTab("risk")}>
            {riskOut?.metrics && Object.keys(riskOut.metrics).length > 0 && (
              <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
                {Object.entries(riskOut.metrics)
                  .slice(0, 8)
                  .map(([k, v]) => (
                    <div key={k} className="rounded-lg bg-sunken px-3 py-2">
                      <div className="truncate text-xs capitalize text-muted">{humanize(k)}</div>
                      <div className="font-mono text-sm">{v === null ? "—" : Math.abs(v) < 5 ? v.toFixed(3) : v.toFixed(1)}</div>
                    </div>
                  ))}
              </div>
            )}
          </AgentPanel>
        )}

        {tab === "data" && detail && (
          <div className="space-y-6">
            <div className="grid gap-6 lg:grid-cols-2">
              <Card title="Data quality" description="Validation of the stored window before any agent may use it.">
                <div className="mb-4 flex flex-wrap gap-2">
                  <FreshnessBadge f={detail.freshness} />
                  {detail.data_quality && (
                    <QualityBadge usable={detail.data_quality.usable} score={detail.data_quality.quality_score} threshold={detail.data_quality.minimum_score_required} />
                  )}
                </div>
                <p className="mb-4 text-sm text-muted">{detail.freshness.reason}</p>
                {detail.data_quality && (
                  <KeyValues
                    items={[
                      ["Window", <span key="w" className="font-mono text-xs">{detail.data_quality.window_start} → {detail.data_quality.window_end}</span>],
                      ["Coverage (1 year)", <span key="c" className={cx("font-mono", detail.data_quality.coverage < 0.95 && "text-warn")}>{(detail.data_quality.coverage * 100).toFixed(1)}%</span>],
                      ["Expected sessions", <span key="e" className="font-mono">{detail.data_quality.expected_sessions}</span>],
                      ["Missing sessions", <span key="m" className="font-mono">{detail.data_quality.missing_session_count}</span>],
                      ["Provider revisions", <span key="r" className="font-mono">{detail.open_conflicts}</span>],
                    ]}
                  />
                )}
                <div className="mt-4 border-t border-line pt-4">
                  {issues.length > 0 ? (
                    <ul className="max-h-48 space-y-1.5 overflow-auto text-xs">
                      {issues.map((i, k) => (
                        <li key={k} className="flex gap-2">
                          {i.severity === "critical" ? <XCircle size={13} className="shrink-0 text-fail" aria-hidden /> : <CircleHelp size={13} className="shrink-0 text-warn" aria-hidden />}
                          <span className="font-mono text-subtle">{i.session ?? "series"}</span>
                          <span>{humanize(i.code)}</span>
                        </li>
                      ))}
                    </ul>
                  ) : (
                    detail.data_quality && (
                      <p className="flex items-center gap-1.5 text-sm text-pass">
                        <CheckCircle2 size={15} aria-hidden /> No warnings in the window.
                      </p>
                    )
                  )}
                </div>
              </Card>

              <Card title="Provenance" description="Where the latest bar came from and when it became known.">
                {lb ? (
                  <KeyValues
                    items={[
                      ["Source", <span key="s">{lb.source}{detail.licensed === false && <span className="text-warn"> (unlicensed)</span>}</span>],
                      ["Basis", humanize(detail.stored_basis ?? "—")],
                      ["Session close", istDateTime(lb.effective_at)],
                      ["Available from", istDateTime(lb.available_at)],
                      ["Retrieved", istDateTime(lb.retrieved_at)],
                      ["Data version", <span key="v" className="font-mono">v{lb.data_version}</span>],
                    ]}
                  />
                ) : (
                  <p className="text-sm text-muted">Nothing ingested yet. Use “Refresh data”.</p>
                )}
              </Card>

              <Card title="Corporate actions">
                {detail.corporate_actions.length ? (
                  <ul className="space-y-2 text-sm">
                    {[...detail.corporate_actions].reverse().slice(0, 12).map((a) => (
                      <li key={a.kind + a.ex_date} className="flex justify-between gap-4">
                        <span className="font-mono text-xs text-muted">{a.ex_date}</span>
                        <span>{a.kind === "split" ? `Split / bonus ${Number(a.numerator)}:${Number(a.denominator)}` : `Dividend ${inr(a.amount)}`}</span>
                      </li>
                    ))}
                  </ul>
                ) : (
                  <p className="text-sm text-muted">None reported by the source in stored history.</p>
                )}
              </Card>

              <Card title="Recent ingestion runs">
                <ul className="space-y-2.5 text-sm">
                  {detail.recent_runs.map((r) => {
                    const bad = r.status === "failed" || r.status === "rejected";
                    return (
                      <li key={r.id} className="border-t border-line pt-2.5 first:border-0 first:pt-0">
                        <div className="flex flex-wrap justify-between gap-2">
                          <span className="font-mono text-xs text-muted">#{r.id} · {r.requested_start} → {r.requested_end}</span>
                          <span className={cx("text-xs font-medium", bad ? "text-fail" : "text-muted")}>{humanize(r.status)}</span>
                        </div>
                        <div className="text-xs text-subtle">
                          {r.provider} · +{r.rows_inserted} new · {r.rows_revised} revised · {r.rows_rejected} rejected
                        </div>
                        {r.error && <div className="mt-1 text-xs text-fail">{r.error}</div>}
                      </li>
                    );
                  })}
                  {detail.recent_runs.length === 0 && <li className="text-muted">No runs yet.</li>}
                </ul>
              </Card>
            </div>
            {isAdmin && <CsvImportCard ticker={ticker} guard={guard} onImported={() => void loadDetail()} />}
          </div>
        )}
      </div>
    </div>
  );
}
