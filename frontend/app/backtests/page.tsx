"use client";

import { CheckCircle2, ChevronDown, FlaskConical, Play, TriangleAlert, XCircle } from "lucide-react";
import { useCallback, useEffect, useState } from "react";
import {
  CartesianGrid,
  Line,
  LineChart,
  ReferenceLine,
  ResponsiveContainer,
  Scatter,
  ScatterChart,
  Tooltip,
  XAxis,
  YAxis,
  type TooltipProps,
} from "recharts";
import { ChartTooltipBox } from "@/components/charts";
import { usePageTitle } from "@/components/usePageTitle";
import { useSession } from "@/components/providers/SessionProvider";
import { useChartColors } from "@/components/providers/ThemeProvider";
import { useToast } from "@/components/providers/ToastProvider";
import { ConfirmDialog } from "@/components/ui/Dialog";
import {
  Badge,
  Button,
  Callout,
  Card,
  EmptyState,
  LoadingRows,
  PageHeader,
  StatCard,
  Table,
  Td,
  Th,
  cx,
} from "@/components/ui/core";
import { api, ApiError, type BacktestDetail, type BacktestSummary, type ModelRow } from "@/lib/api";
import { ago, istDate, num, pct, shortDate, signedPct, toneOf } from "@/lib/format";

function EquityVsBenchmark({ data }: { data: NonNullable<BacktestDetail["simulation"]>["periods"] }) {
  const c = useChartColors();
  const Tip = ({ active, payload }: TooltipProps<number, string>) => {
    if (!active || !payload?.length) return null;
    const p = payload[0].payload as (typeof data)[number];
    return (
      <ChartTooltipBox
        title={shortDate(p.date)}
        rows={[
          ["Strategy", num(p.equity, 3), c.s1],
          ["NIFTY 50", num(p.benchmark_equity, 3), c.s2],
          ["Held", p.names.length ? p.names.join(", ") : "no trade"],
        ]}
      />
    );
  };
  const last = data[data.length - 1];
  return (
    <div>
      <div className="mb-2 flex gap-4 text-xs text-muted" aria-label="Legend">
        <span className="inline-flex items-center gap-1.5"><svg width="18" height="6" aria-hidden><line x1="0" y1="3" x2="18" y2="3" stroke={c.s1} strokeWidth="2" /></svg>Strategy {last && `· ${num(last.equity, 2)}×`}</span>
        <span className="inline-flex items-center gap-1.5"><svg width="18" height="6" aria-hidden><line x1="0" y1="3" x2="18" y2="3" stroke={c.s2} strokeWidth="2" strokeDasharray="4 3" /></svg>NIFTY 50 {last && `· ${num(last.benchmark_equity, 2)}×`}</span>
      </div>
      <div className="h-64">
        <ResponsiveContainer>
          <LineChart data={data} margin={{ top: 5, right: 4, left: 0, bottom: 0 }}>
            <CartesianGrid stroke={c.grid} vertical={false} />
            <XAxis dataKey="date" tickFormatter={shortDate} tick={{ fill: c.axis, fontSize: 11 }} tickLine={false} axisLine={{ stroke: c.grid }} minTickGap={40} />
            <YAxis orientation="right" width={48} tick={{ fill: c.axis, fontSize: 11 }} tickLine={false} axisLine={false} domain={["auto", "auto"]} tickFormatter={(v: number) => `${v.toFixed(2)}×`} />
            <ReferenceLine y={1} stroke={c.axis} strokeDasharray="2 3" />
            <Tooltip content={<Tip />} cursor={{ stroke: c.axis }} isAnimationActive={false} />
            <Line type="stepAfter" dataKey="benchmark_equity" stroke={c.s2} strokeWidth={2} strokeDasharray="5 3" dot={false} isAnimationActive={false} />
            <Line type="stepAfter" dataKey="equity" stroke={c.s1} strokeWidth={2} dot={false} activeDot={{ r: 4, stroke: c.surface, strokeWidth: 2 }} isAnimationActive={false} />
          </LineChart>
        </ResponsiveContainer>
      </div>
    </div>
  );
}

function Calibration({ data }: { data: { mean_predicted: number; observed_rate: number; count: number }[] }) {
  const c = useChartColors();
  const Tip = ({ active, payload }: TooltipProps<number, string>) => {
    if (!active || !payload?.length) return null;
    const p = payload[0].payload as (typeof data)[number];
    return <ChartTooltipBox title="Bin" rows={[["Predicted", pct(p.mean_predicted)], ["Observed", pct(p.observed_rate)], ["Rows", String(p.count)]]} />;
  };
  return (
    <div className="h-64">
      <ResponsiveContainer>
        <ScatterChart margin={{ top: 5, right: 8, left: 0, bottom: 0 }}>
          <CartesianGrid stroke={c.grid} />
          <XAxis type="number" dataKey="mean_predicted" domain={[0, 1]} tickFormatter={(v: number) => pct(v, 0)} tick={{ fill: c.axis, fontSize: 11 }} tickLine={false} axisLine={{ stroke: c.grid }} name="Predicted" />
          <YAxis type="number" dataKey="observed_rate" domain={[0, 1]} tickFormatter={(v: number) => pct(v, 0)} tick={{ fill: c.axis, fontSize: 11 }} tickLine={false} axisLine={false} width={44} name="Observed" />
          <ReferenceLine segment={[{ x: 0, y: 0 }, { x: 1, y: 1 }]} stroke={c.axis} strokeDasharray="4 4" />
          <Tooltip content={<Tip />} isAnimationActive={false} />
          <Scatter data={data} fill={c.s1} stroke={c.surface} strokeWidth={2} isAnimationActive={false} />
        </ScatterChart>
      </ResponsiveContainer>
    </div>
  );
}

export default function BacktestsPage() {
  usePageTitle("Backtests & model");
  const { guard, isAdmin } = useSession();
  const toast = useToast();
  const [runs, setRuns] = useState<BacktestSummary[] | null>(null);
  const [models, setModels] = useState<ModelRow[]>([]);
  const [sel, setSel] = useState<BacktestDetail | null>(null);
  const [busy, setBusy] = useState(false);
  const [confirm, setConfirm] = useState<{ m: ModelRow; action: "activate" | "retire" } | null>(null);
  const [acting, setActing] = useState(false);

  const load = useCallback(async () => {
    try {
      const [r, m] = await Promise.all([guard((t) => api.backtests(t)), guard((t) => api.models(t))]);
      if (r) setRuns(r);
      if (m) setModels(m);
      if (r && r[0]) {
        const d = await guard((t) => api.backtest(t, r[0].id));
        if (d) setSel((s) => s ?? d);
      }
    } catch (err) {
      toast({ tone: "error", title: "Could not load backtests", body: err instanceof Error ? err.message : undefined });
    }
  }, [guard, toast]);

  useEffect(() => {
    void load();
  }, [load]);

  async function run() {
    setBusy(true);
    try {
      const d = await guard((t) => api.runBacktest(t, 20));
      if (d) {
        setSel(d);
        toast({ tone: d.status === "failed" ? "error" : "success", title: `Backtest #${d.id} ${d.status}`, body: d.error ?? undefined });
      }
      await load();
    } catch (err) {
      toast({ tone: "error", title: "Backtest failed", body: err instanceof ApiError ? err.message : undefined });
    } finally {
      setBusy(false);
    }
  }

  async function open(id: number) {
    const d = await guard((t) => api.backtest(t, id));
    if (d) setSel(d);
  }

  async function applyModel() {
    if (!confirm) return;
    setActing(true);
    try {
      await guard((t) => api.setModel(t, confirm.m.id, confirm.action));
      toast({ tone: "success", title: `Model ${confirm.action === "activate" ? "activated" : "retired"}` });
      setConfirm(null);
      await load();
    } catch (err) {
      toast({ tone: "error", title: "Model not changed", body: err instanceof ApiError ? err.message : undefined });
    } finally {
      setActing(false);
    }
  }

  const m = sel?.metrics;
  const sum = sel?.simulation?.summary;

  return (
    <div className="space-y-6">
      <PageHeader
        title="Backtests & model"
        description="Walk-forward LightGBM with purged, embargoed folds and isotonic calibration. Past results do not predict future results."
        actions={isAdmin && <Button variant="primary" loading={busy} onClick={run} icon={<Play size={15} />}>{busy ? "Running walk-forward…" : "Run backtest (20-day)"}</Button>}
      />
      {busy && <Callout tone="info" title="Backtest running">Training every fold on point-in-time features can take a few minutes. You can keep using Aegis.</Callout>}

      {runs === null && <LoadingRows rows={6} />}
      {runs?.length === 0 && (
        <Card>
          <EmptyState icon={<FlaskConical size={20} />} title="No backtests yet" body={isAdmin ? "Run one to train and evaluate a candidate model." : "An admin can run one."} />
        </Card>
      )}

      {sel && (
        <>
          <Callout tone="warn" icon={<TriangleAlert size={16} />} title={`Survivorship bias: ${sel.survivorship_bias}`}>
            {sel.warnings.filter((w) => !w.startsWith("Universe")).join(" · ")}
          </Callout>
          {sel.status === "failed" && <Callout tone="fail" title={`Run #${sel.id} failed`}>{sel.error}</Callout>}
          {m && sum && (
            <>
              <div>
                <p className="mb-3 text-sm text-muted">
                  Run #{sel.id} · out of sample {istDate(m.oos_start)} → {istDate(m.oos_end)} · {sel.universe.length} stocks
                </p>
                <div className="grid grid-cols-2 gap-3 md:grid-cols-4 lg:gap-4">
                  <StatCard label="Strategy total return" value={signedPct(sum.total_return)} tone={toneOf(sum.total_return)} sub={`CAGR ${pct(sum.cagr)} · NIFTY ${signedPct(sum.benchmark_total_return)}`} />
                  <StatCard label="Max drawdown" value={pct(sum.max_drawdown)} sub={`NIFTY ${pct(sum.benchmark_max_drawdown)}`} />
                  <StatCard label="AUC · P(profit)" value={num(m.profit.auc, 3)} sub="0.5 = no skill" />
                  <StatCard label="Calibration error" value={num(m.profit.ece, 3)} sub="Gate maximum 0.050" tone={m.profit.ece !== null && m.profit.ece <= 0.05 ? "text-pass" : "text-warn"} />
                  <StatCard label="Trades" value={String(sum.trades ?? "—")} sub={`${sum.no_trade_periods ?? 0} no-trade periods`} />
                  <StatCard label="Win rate" value={pct(sum.win_rate, 0)} />
                  <StatCard label="AUC · P(outperform)" value={num(m.outperform.auc, 3)} />
                  <StatCard label="Folds" value={`${m.folds_trained}`} sub={`+${m.folds_skipped} skipped · ${m.oos_rows} OOS rows`} />
                </div>
              </div>

              <div className="grid gap-6 xl:grid-cols-2">
                <Card title="Growth of ₹1: strategy vs NIFTY 50" description="After costs, non-overlapping holding periods.">
                  <EquityVsBenchmark data={sel.simulation!.periods} />
                </Card>
                <Card title="Calibration" description="Predicted vs observed P(profit). Points on the diagonal are well calibrated.">
                  <Calibration data={m.calibration_curve_profit} />
                </Card>
              </div>

              <Card title="Walk-forward folds" bodyClassName="pb-2">
                <Table>
                  <thead>
                    <tr>
                      {["Fold", "Test window", "Train rows", "AUC", "ECE", ""].map((h, i) => (
                        <Th key={h + i} align={i >= 2 && i <= 4 ? "right" : "left"}>{h}</Th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {sel.folds?.map((f) => (
                      <tr key={f.fold}>
                        <Td mono>{f.fold}</Td>
                        <Td mono className="text-xs">{f.test_start} → {f.test_end}</Td>
                        <Td align="right" mono>{String(f.train_rows ?? "—")}</Td>
                        <Td align="right" mono>{num(f.profit?.auc, 3)}</Td>
                        <Td align="right" mono>{num(f.profit?.ece, 3)}</Td>
                        <Td className="text-xs text-muted">{f.skipped ? `Skipped: ${f.reason}` : ""}</Td>
                      </tr>
                    ))}
                  </tbody>
                </Table>
              </Card>

              <details className="group rounded-xl border border-line bg-panel">
                <summary className="flex cursor-pointer list-none items-center justify-between px-5 py-4 text-sm font-semibold">
                  Reproducibility
                  <ChevronDown size={16} className="text-subtle transition-transform group-open:rotate-180" aria-hidden />
                </summary>
                <dl className="grid grid-cols-[auto_1fr] gap-x-6 gap-y-2 border-t border-line px-5 py-4 text-xs">
                  <dt className="text-muted">Data hash</dt><dd className="break-all font-mono">{sel.data_hash}</dd>
                  <dt className="text-muted">Config</dt><dd className="break-all font-mono">{sel.config_fingerprint}</dd>
                  <dt className="text-muted">Seed</dt><dd className="font-mono">{String(sel.reproducibility.seed)}</dd>
                  <dt className="text-muted">Libraries</dt><dd className="font-mono">{Object.entries(sel.reproducibility.libraries ?? {}).map(([k, v]) => `${k} ${v}`).join(" · ")}</dd>
                  <dt className="text-muted">Universe</dt><dd className="font-mono">{sel.universe.join(" ")}</dd>
                </dl>
              </details>
            </>
          )}
        </>
      )}

      {runs && runs.length > 0 && (
        <div className="grid gap-6 xl:grid-cols-2">
          <Card title="Runs" description="Select a run to view it.">
            <ul className="-mx-2 space-y-0.5">
              {runs.map((r) => (
                <li key={r.id}>
                  <button onClick={() => open(r.id)} className={cx("flex w-full flex-wrap items-center justify-between gap-2 rounded-lg px-2 py-2 text-left text-sm hover:bg-hover", sel?.id === r.id && "bg-accent-soft")}>
                    <span>
                      <span className="font-mono text-xs text-subtle">#{r.id}</span> {r.horizon}-day · {r.universe_size} stocks
                      <span className="text-subtle"> · {ago(r.created_at)}</span>
                    </span>
                    <span className="flex items-center gap-2 text-xs">
                      {r.status === "failed" ? <Badge tone="fail">Failed</Badge> : <span className="font-mono text-muted">AUC {num(r.headline.auc_profit, 3)} · ECE {num(r.headline.ece_profit, 3)}</span>}
                    </span>
                  </button>
                </li>
              ))}
            </ul>
          </Card>
          <Card title="Model registry" description="Activating a model lets the risk engine query it; the engine still rejects estimates that fail the calibration or out-of-sample gates.">
            {models.length === 0 && <p className="text-sm text-muted">No models yet.</p>}
            <ul className="space-y-3">
              {models.map((mo) => (
                <li key={mo.id} className="rounded-lg border border-line p-3">
                  <div className="flex flex-wrap items-center justify-between gap-2">
                    <span className="font-mono text-sm">{mo.name}</span>
                    <Badge tone={mo.status === "active" ? "pass" : mo.status === "candidate" ? "info" : "neutral"}>{mo.status}</Badge>
                  </div>
                  <div className="mt-2 flex flex-wrap gap-x-4 gap-y-1 text-xs text-muted">
                    <span className="inline-flex items-center gap-1">
                      {mo.passes_calibration_gate ? <CheckCircle2 size={12} className="text-pass" aria-hidden /> : <XCircle size={12} className="text-fail" aria-hidden />}
                      ECE {mo.calibration_error.toFixed(3)}
                    </span>
                    <span className="inline-flex items-center gap-1">
                      {mo.passes_oos_gate ? <CheckCircle2 size={12} className="text-pass" aria-hidden /> : <XCircle size={12} className="text-fail" aria-hidden />}
                      {mo.oos_periods} folds
                    </span>
                    <span>AUC {num(mo.auc, 3)}</span>
                    <span>valid from {istDate(mo.valid_from)}</span>
                  </div>
                  {isAdmin && mo.status !== "retired" && (
                    <div className="mt-3 flex gap-2">
                      {mo.status === "candidate" && <Button size="sm" variant="primary" onClick={() => setConfirm({ m: mo, action: "activate" })}>Activate</Button>}
                      <Button size="sm" onClick={() => setConfirm({ m: mo, action: "retire" })}>Retire</Button>
                    </div>
                  )}
                </li>
              ))}
            </ul>
          </Card>
        </div>
      )}

      <ConfirmDialog
        open={confirm !== null}
        onClose={() => !acting && setConfirm(null)}
        onConfirm={applyModel}
        busy={acting}
        tone={confirm?.action === "retire" ? "danger" : "primary"}
        title={confirm?.action === "activate" ? `Activate ${confirm?.m.name}?` : `Retire ${confirm?.m.name}?`}
        body={
          confirm?.action === "activate"
            ? "The risk engine will use this model's estimates for its horizon. Daily monitoring retires it automatically if it drifts."
            : "The engine stops using it. With no active model for this horizon, probability gates are UNKNOWN and every entry is rejected."
        }
        confirmLabel={confirm?.action === "activate" ? "Activate model" : "Retire model"}
      />
    </div>
  );
}
