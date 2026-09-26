"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useCallback, useEffect, useMemo, useState } from "react";
import { Login } from "@/components/Login";
import { Nav } from "@/components/Nav";
import { PriceChart } from "@/components/PriceChart";
import { FreshnessBadge, QualityBadge } from "@/components/StatusBadge";
import { FinancialsTable } from "@/components/FinancialsTable";
import { NewsList } from "@/components/NewsList";
import { TechnicalPanel } from "@/components/TechnicalPanel";
import { ValuationDetails } from "@/components/ValuationDetails";
import { ReportPanel } from "@/components/ReportPanel";
import { useSession } from "@/components/useSession";
import {
  api,
  type AgentOutput,
  type Financials,
  type NewsItem,
  type Basis,
  type IndicatorSeries,
  type PriceSeries,
  type StockDetail,
  type Valuation,
  type AnalysisReport,
} from "@/lib/api";

const RANGES = [
  { key: "1M", days: 31 },
  { key: "6M", days: 183 },
  { key: "1Y", days: 366 },
  { key: "5Y", days: 5 * 366 },
] as const;

const BASES: { key: Basis; label: string; hint: string }[] = [
  { key: "split_adjusted", label: "Price", hint: "Adjusted for splits and bonuses" },
  { key: "total_return", label: "Total return", hint: "Also reinvests dividends (derived)" },
];

function isoMinusDays(iso: string, days: number) {
  const d = new Date(iso + "T00:00:00Z");
  d.setUTCDate(d.getUTCDate() - days);
  return d.toISOString().slice(0, 10);
}

const inr = new Intl.NumberFormat("en-IN", { maximumFractionDigits: 2, minimumFractionDigits: 2 });
const dt = (iso: string | null) =>
  iso ? new Date(iso).toLocaleString("en-IN", { timeZone: "Asia/Kolkata" }) + " IST" : "—";

function Panel({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section className="rounded-lg border border-line bg-panel p-5">
      <h3 className="mb-3 text-xs font-semibold uppercase tracking-wider text-muted">{title}</h3>
      {children}
    </section>
  );
}

export default function StockPage() {
  const ticker = decodeURIComponent(useParams<{ ticker: string }>().ticker);
  const { token, ready, me, health, signIn, signOut, guard } = useSession();
  const [detail, setDetail] = useState<StockDetail | null>(null);
  const [series, setSeries] = useState<PriceSeries | null>(null);
  const [range, setRange] = useState<(typeof RANGES)[number]["key"]>("1Y");
  const [basis, setBasis] = useState<Basis>("split_adjusted");
  const [showTable, setShowTable] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [tech, setTech] = useState<AgentOutput | null>(null);
  const [techBusy, setTechBusy] = useState(false);
  const [indicators, setIndicators] = useState<IndicatorSeries | null>(null);
  const [fund, setFund] = useState<AgentOutput | null>(null);
  const [fin, setFin] = useState<Financials | null>(null);
  const [fundBusy, setFundBusy] = useState(false);
  const [newsOut, setNewsOut] = useState<AgentOutput | null>(null);
  const [news, setNews] = useState<NewsItem[] | null>(null);
  const [newsBusy, setNewsBusy] = useState(false);
  const [val, setVal] = useState<Valuation | null>(null);
  const [macroOut, setMacroOut] = useState<AgentOutput | null>(null);
  const [vmBusy, setVmBusy] = useState(false);
  const [report, setReport] = useState<AnalysisReport | null>(null);
  const [reportBusy, setReportBusy] = useState(false);
  const [riskOut, setRiskOut] = useState<AgentOutput | null>(null);
  const [riskBusy, setRiskBusy] = useState(false);

  useEffect(() => {
    if (!token) return;
    guard((t) => api.latestAnalysis(t, ticker))
      .then((r) => r && setReport(r))
      .catch(() => setReport(null)); // 404 = no report yet
  }, [token, guard, ticker]);

  const runReport = useCallback(async () => {
    setReportBusy(true);
    try {
      const r = await guard((t) => api.runAnalysis(t, ticker));
      if (r) setReport(r);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Analysis failed");
    } finally {
      setReportBusy(false);
    }
  }, [guard, ticker]);

  const downloadReport = useCallback(async () => {
    if (!report) return;
    const md = await guard((t) => api.reportMarkdown(t, report.report_id));
    if (!md) return;
    const url = URL.createObjectURL(new Blob([md], { type: "text/markdown" }));
    const a = document.createElement("a");
    a.href = url;
    a.download = `aegis-${ticker}-report-${report.report_id}.md`;
    a.click();
    URL.revokeObjectURL(url);
  }, [guard, report, ticker]);

  const runRisk = useCallback(async () => {
    setRiskBusy(true);
    try {
      const out = await guard((t) => api.riskAgent(t, ticker));
      if (out) setRiskOut(out);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Risk analysis failed");
    } finally {
      setRiskBusy(false);
    }
  }, [guard, ticker]);


  const runValMacro = useCallback(async () => {
    setVmBusy(true);
    try {
      const [v, m] = await Promise.all([
        guard((t) => api.valuation(t, ticker)),
        guard((t) => api.macroAgent(t, ticker)),
      ]);
      if (v) setVal(v);
      if (m) setMacroOut(m);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Valuation / macro analysis failed");
    } finally {
      setVmBusy(false);
    }
  }, [guard, ticker]);

  const loadDetail = useCallback(async () => {
    try {
      const d = await guard((t) => api.stock(t, ticker));
      if (d) setDetail(d);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Request failed");
    }
  }, [guard, ticker]);

  useEffect(() => {
    if (token) void loadDetail();
  }, [token, loadDetail]);

  const end = detail?.latest_session ?? null;
  useEffect(() => {
    if (token && end) void runRisk();
  }, [token, end, runRisk]);
  useEffect(() => {
    if (!token || !end) return;
    const days = RANGES.find((r) => r.key === range)!.days;
    const start = isoMinusDays(end, days);
    guard((t) => api.prices(t, ticker, basis, start, end))
      .then((s) => s && setSeries(s))
      .catch((err) => setError(err instanceof Error ? err.message : "Request failed"));
    guard((t) => api.indicators(t, ticker, start, end))
      .then((s) => s && setIndicators(s))
      .catch(() => setIndicators(null));
  }, [token, guard, ticker, basis, range, end]);

  const runTechnical = useCallback(async () => {
    setTechBusy(true);
    try {
      const out = await guard((t) => api.technical(t, ticker));
      if (out) setTech(out);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Technical analysis failed");
    } finally {
      setTechBusy(false);
    }
  }, [guard, ticker]);

  useEffect(() => {
    if (token && end) void runTechnical();
  }, [token, end, runTechnical]);

  const runFundamental = useCallback(
    async (fetchFirst: boolean) => {
      setFundBusy(true);
      try {
        if (fetchFirst) {
          const run = await guard((t) => api.ingestFinancials(t, ticker));
          if (run && run.status === "failed") setError(`Financials fetch failed: ${run.error}`);
        }
        const [f, out] = await Promise.all([
          guard((t) => api.financials(t, ticker)),
          guard((t) => api.fundamental(t, ticker)),
        ]);
        if (f) setFin(f);
        if (out) setFund(out);
      } catch (err) {
        setError(err instanceof Error ? err.message : "Fundamental analysis failed");
      } finally {
        setFundBusy(false);
      }
    },
    [guard, ticker],
  );

  const runNews = useCallback(
    async (fetchFirst: boolean) => {
      setNewsBusy(true);
      try {
        if (fetchFirst) {
          const run = await guard((t) => api.ingestNews(t, ticker));
          if (run && run.status === "failed") setError(`News fetch failed: ${run.error}`);
        }
        const [items, out] = await Promise.all([
          guard((t) => api.news(t, ticker)),
          guard((t) => api.newsAgent(t, ticker)),
        ]);
        if (items) setNews(items);
        if (out) setNewsOut(out);
      } catch (err) {
        setError(err instanceof Error ? err.message : "News analysis failed");
      } finally {
        setNewsBusy(false);
      }
    },
    [guard, ticker],
  );

  useEffect(() => {
    if (token && detail) void runNews(false);
  }, [token, detail?.ticker, runNews]); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    if (token && detail) void runValMacro();
  }, [token, detail?.ticker, runValMacro]); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    if (token && detail) void runFundamental(false);
  }, [token, detail?.ticker, runFundamental]); // eslint-disable-line react-hooks/exhaustive-deps

  async function refresh() {
    setBusy(true);
    setError(null);
    try {
      const run = await guard((t) => api.ingest(t, ticker));
      if (run && (run.status === "failed" || run.status === "rejected")) {
        setError(`Ingestion ${run.status}: ${run.error ?? "see data quality"}`);
      }
      await loadDetail();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Request failed");
    } finally {
      setBusy(false);
    }
  }

  const change = useMemo(() => {
    const b = series?.bars;
    if (!b || b.length < 2) return null;
    const first = Number(b[0].close);
    const last = Number(b[b.length - 1].close);
    return (last / first - 1) * 100;
  }, [series]);

  if (!ready) return null;
  if (!token) return <Login onToken={signIn} />;

  const lb = detail?.latest_bar;
  const issues = detail?.data_quality?.issues.filter((i) => i.severity !== "info") ?? [];

  return (
    <main className="mx-auto max-w-5xl px-4 py-8">
      <Nav mode={health?.system_mode} email={me?.email} role={me?.role} onSignOut={signOut} />
      <Link href="/stocks" className="text-sm text-muted hover:text-ink">← Stocks</Link>

      {error && <p className="mt-4 text-sm text-fail">{error}</p>}

      {detail && (
        <>
          <div className="mb-6 mt-3 flex flex-wrap items-end justify-between gap-4">
            <div>
              <h2 className="text-2xl font-semibold">{detail.name ?? detail.ticker}</h2>
              <p className="font-mono text-sm text-muted">
                {detail.ticker} · {detail.exchange} · {detail.currency}
              </p>
            </div>
            <div className="text-right">
              {lb ? (
                <>
                  <div className="font-mono text-3xl">₹{inr.format(Number(lb.close))}</div>
                  <div className="text-xs text-muted">
                    Close on {lb.session}
                    {change !== null && (
                      <span className="ml-2 font-mono text-ink">
                        {change >= 0 ? "▲" : "▼"} {Math.abs(change).toFixed(2)}% ({range})
                      </span>
                    )}
                  </div>
                </>
              ) : (
                <div className="text-sm text-muted">No prices stored yet</div>
              )}
              <button
                className="mt-2 rounded border border-line px-2.5 py-1 text-xs disabled:opacity-40"
                onClick={refresh}
                disabled={busy}
              >
                {busy ? "Fetching…" : "Refresh data"}
              </button>
            </div>
          </div>

          {detail.licensing_notice && (
            <div className="mb-4 rounded border border-unknown/50 bg-unknown/10 px-4 py-2 text-sm text-unknown">
              <span aria-hidden>⚠ </span>
              {detail.licensing_notice}
            </div>
          )}

          <ReportPanel report={report} busy={reportBusy} onRun={runReport} onDownload={downloadReport} />

          <section className="mb-4 rounded-lg border border-line bg-panel p-5">
            <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
              <div className="flex gap-1" role="group" aria-label="Price basis">
                {BASES.map((b) => (
                  <button
                    key={b.key}
                    title={b.hint}
                    onClick={() => setBasis(b.key)}
                    aria-pressed={basis === b.key}
                    className={`rounded px-2.5 py-1 text-xs ${basis === b.key ? "bg-ink text-surface" : "text-muted hover:text-ink"}`}
                  >
                    {b.label}
                  </button>
                ))}
              </div>
              <div className="flex items-center gap-3">
                <div className="flex gap-1" role="group" aria-label="Time range">
                  {RANGES.map((r) => (
                    <button
                      key={r.key}
                      onClick={() => setRange(r.key)}
                      aria-pressed={range === r.key}
                      className={`rounded px-2 py-1 font-mono text-xs ${range === r.key ? "bg-ink text-surface" : "text-muted hover:text-ink"}`}
                    >
                      {r.key}
                    </button>
                  ))}
                </div>
                <button
                  className="text-xs text-muted underline"
                  onClick={() => setShowTable((v) => !v)}
                >
                  {showTable ? "Chart" : "Table"}
                </button>
              </div>
            </div>

            {series && !showTable && (
              <PriceChart
                bars={series.bars}
                indicators={basis === "split_adjusted" ? indicators : null}
              />
            )}
            {series && showTable && (
              <div className="max-h-80 overflow-auto">
                <table className="w-full font-mono text-xs">
                  <thead className="sticky top-0 bg-panel text-left text-muted">
                    <tr>
                      {["Session", "Open", "High", "Low", "Close", "Volume", "Ver"].map((h) => (
                        <th key={h} className="py-1.5 pr-3 font-normal">{h}</th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {[...series.bars].reverse().map((b) => (
                      <tr key={b.session} className="border-t border-line">
                        <td className="py-1 pr-3">{b.session}</td>
                        <td className="py-1 pr-3">{inr.format(Number(b.open))}</td>
                        <td className="py-1 pr-3">{inr.format(Number(b.high))}</td>
                        <td className="py-1 pr-3">{inr.format(Number(b.low))}</td>
                        <td className="py-1 pr-3">{inr.format(Number(b.close))}</td>
                        <td className="py-1 pr-3">{b.volume.toLocaleString("en-IN")}</td>
                        <td className="py-1 pr-3">{b.data_version}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
            {series && (
              <p className="mt-3 text-xs text-muted">
                {series.derived
                  ? `Total-return series derived deterministically from stored ${series.stored_basis?.replace("_", "-")} prices and dividends.`
                  : `Stored ${series.basis.replace("_", "-")} prices.`}{" "}
                Source: {series.source ?? "—"}.
              </p>
            )}
          </section>

          <TechnicalPanel out={tech} busy={techBusy} onRun={runTechnical} />

          <TechnicalPanel
            title="Fundamental analysis"
            scoreLabel="Fundamental score"
            runLabel="Fetch financials & re-run"
            out={fund}
            busy={fundBusy}
            onRun={() => runFundamental(true)}
          >
            <FinancialsTable data={fin} />
          </TechnicalPanel>

          <TechnicalPanel
            title="News"
            scoreLabel="News sentiment"
            runLabel="Fetch news & re-run"
            out={newsOut}
            busy={newsBusy}
            onRun={() => runNews(true)}
          >
            <NewsList items={news} />
          </TechnicalPanel>

          <TechnicalPanel
            title="Risk"
            scoreLabel="Risk suitability (higher = lower risk)"
            runLabel="Re-run"
            out={riskOut}
            busy={riskBusy}
            onRun={runRisk}
          />

          <TechnicalPanel
            title="Valuation"
            scoreLabel="Valuation score"
            runLabel="Re-run"
            out={val?.analysis ?? null}
            busy={vmBusy}
            onRun={runValMacro}
          >
            <ValuationDetails d={val?.details ?? null} />
          </TechnicalPanel>

          <TechnicalPanel
            title="Macro & regime"
            scoreLabel="Macro fit"
            runLabel="Re-run"
            out={macroOut}
            busy={vmBusy}
            onRun={runValMacro}
          />

          <div className="grid gap-4 md:grid-cols-2">
            <Panel title="Data quality">
              <div className="mb-3 flex flex-wrap gap-2">
                <FreshnessBadge f={detail.freshness} />
                {detail.data_quality && (
                  <QualityBadge
                    usable={detail.data_quality.usable}
                    score={detail.data_quality.quality_score}
                    threshold={detail.data_quality.minimum_score_required}
                  />
                )}
              </div>
              <p className="mb-3 text-xs text-muted">{detail.freshness.reason}</p>
              {detail.data_quality && (
                <dl className="mb-3 grid grid-cols-2 gap-y-1 text-sm">
                  <dt className="text-muted">Window</dt>
                  <dd className="font-mono text-xs">
                    {detail.data_quality.window_start} → {detail.data_quality.window_end}
                  </dd>
                  <dt className="text-muted">Coverage (1Y)</dt>
                  <dd className={`font-mono ${detail.data_quality.coverage < 0.95 ? "text-unknown" : ""}`}>
                    {(detail.data_quality.coverage * 100).toFixed(1)}%
                  </dd>
                  <dt className="text-muted">Expected sessions</dt>
                  <dd className="font-mono">{detail.data_quality.expected_sessions}</dd>
                  <dt className="text-muted">Missing sessions</dt>
                  <dd className="font-mono">{detail.data_quality.missing_session_count}</dd>
                  <dt className="text-muted">Provider revisions</dt>
                  <dd className="font-mono">{detail.open_conflicts}</dd>
                </dl>
              )}
              {issues.length > 0 ? (
                <ul className="max-h-40 space-y-1 overflow-auto text-xs">
                  {issues.map((i, k) => (
                    <li key={k} className="flex gap-2">
                      <span className={i.severity === "critical" ? "text-fail" : "text-unknown"}>
                        {i.severity === "critical" ? "✕" : "!"}
                      </span>
                      <span className="font-mono text-muted">{i.session ?? "series"}</span>
                      <span>{i.code.replaceAll("_", " ")}</span>
                    </li>
                  ))}
                </ul>
              ) : (
                detail.data_quality && <p className="text-xs text-pass">✓ No warnings in the window.</p>
              )}
            </Panel>

            <Panel title="Provenance (latest bar)">
              {lb ? (
                <dl className="grid grid-cols-[auto_1fr] gap-x-4 gap-y-1 text-sm">
                  <dt className="text-muted">Source</dt>
                  <dd>{lb.source} {detail.licensed === false && <span className="text-unknown">(unlicensed)</span>}</dd>
                  <dt className="text-muted">Basis</dt>
                  <dd>{detail.stored_basis?.replace("_", "-")}</dd>
                  <dt className="text-muted">Session close</dt>
                  <dd className="text-xs">{dt(lb.effective_at)}</dd>
                  <dt className="text-muted">Available from</dt>
                  <dd className="text-xs">{dt(lb.available_at)}</dd>
                  <dt className="text-muted">Retrieved</dt>
                  <dd className="text-xs">{dt(lb.retrieved_at)}</dd>
                  <dt className="text-muted">Data version</dt>
                  <dd className="font-mono">v{lb.data_version}</dd>
                </dl>
              ) : (
                <p className="text-sm text-muted">Nothing ingested yet. Use “Refresh data”.</p>
              )}
            </Panel>

            <Panel title="Corporate actions">
              {detail.corporate_actions.length ? (
                <ul className="space-y-1 text-sm">
                  {[...detail.corporate_actions].reverse().slice(0, 12).map((a) => (
                    <li key={a.kind + a.ex_date} className="flex justify-between">
                      <span className="font-mono text-xs">{a.ex_date}</span>
                      <span>
                        {a.kind === "split"
                          ? `Split / bonus ${Number(a.numerator)}:${Number(a.denominator)}`
                          : `Dividend ₹${Number(a.amount).toFixed(2)}`}
                      </span>
                    </li>
                  ))}
                </ul>
              ) : (
                <p className="text-sm text-muted">None reported by the source in stored history.</p>
              )}
            </Panel>

            <Panel title="Recent ingestion runs">
              <ul className="space-y-2 text-xs">
                {detail.recent_runs.map((r) => (
                  <li key={r.id} className="flex flex-wrap justify-between gap-2 border-t border-line pt-2 first:border-0 first:pt-0">
                    <span className="font-mono text-muted">
                      #{r.id} {r.requested_start} → {r.requested_end}
                    </span>
                    <span className={r.status === "failed" || r.status === "rejected" ? "text-fail" : ""}>
                      {r.status.replaceAll("_", " ")} · +{r.rows_inserted} / ~{r.rows_revised} / ✕{r.rows_rejected}
                    </span>
                    {r.error && <span className="w-full text-fail">{r.error}</span>}
                  </li>
                ))}
                {detail.recent_runs.length === 0 && <li className="text-muted">No runs yet.</li>}
              </ul>
            </Panel>
          </div>
        </>
      )}
    </main>
  );
}
