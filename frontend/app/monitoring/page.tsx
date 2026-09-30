"use client";

import { Activity, CircleHelp, Lock, Play, X, XCircle } from "lucide-react";
import { useCallback, useEffect, useState } from "react";
import {
  CartesianGrid,
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
import { GateBadge } from "@/components/ui/Status";
import { Button, Card, EmptyState, IconButton, LoadingRows, PageHeader, Table, Td, Th, cx } from "@/components/ui/core";
import { api, type MonitoringOverview, type MonitorRun } from "@/lib/api";
import { istDateTime, pct } from "@/lib/format";

const n3 = (v: number | null | undefined) => (v === null || v === undefined ? "—" : v.toFixed(3));

function CalibrationScatter({ curve }: { curve: NonNullable<NonNullable<MonitorRun["calibration"]>["curve"]> }) {
  const c = useChartColors();
  const Tip = ({ active, payload }: TooltipProps<number, string>) => {
    if (!active || !payload?.length) return null;
    const p = payload[0].payload as (typeof curve)[number];
    return <ChartTooltipBox title="Bin" rows={[["Predicted", pct(p.mean_predicted)], ["Observed", pct(p.observed_rate)], ["Predictions", String(p.count)]]} />;
  };
  return (
    <div className="h-52">
      <ResponsiveContainer>
        <ScatterChart margin={{ left: 0, right: 8, top: 8, bottom: 4 }}>
          <CartesianGrid stroke={c.grid} />
          <XAxis type="number" dataKey="mean_predicted" domain={[0, 1]} tickFormatter={(v: number) => pct(v, 0)} tick={{ fill: c.axis, fontSize: 11 }} tickLine={false} />
          <YAxis type="number" dataKey="observed_rate" domain={[0, 1]} tickFormatter={(v: number) => pct(v, 0)} tick={{ fill: c.axis, fontSize: 11 }} tickLine={false} width={44} />
          <ReferenceLine segment={[{ x: 0, y: 0 }, { x: 1, y: 1 }]} stroke={c.axis} strokeDasharray="4 4" />
          <Tooltip content={<Tip />} isAnimationActive={false} />
          <Scatter data={curve} fill={c.s1} stroke={c.surface} strokeWidth={2} isAnimationActive={false} />
        </ScatterChart>
      </ResponsiveContainer>
    </div>
  );
}

function RunDetail({ r }: { r: MonitorRun }) {
  const d = r.drift;
  const c = r.calibration;
  return (
    <div className="grid gap-6 xl:grid-cols-2">
      <div>
        <div className="mb-3 flex flex-wrap items-center gap-2 text-sm font-medium">
          Feature drift <GateBadge s={d?.status} />
          <span className="text-xs font-normal text-muted">{d?.samples ?? 0} current rows</span>
        </div>
        <Table className="!mx-0">
          <thead>
            <tr>
              <Th className="!pl-0">Feature</Th>
              <Th align="right">PSI</Th>
              <Th align="right" className="hidden sm:table-cell">Warn</Th>
              <Th align="right" className="hidden sm:table-cell">Fail</Th>
              <Th className="!pr-0" />
            </tr>
          </thead>
          <tbody>
            {(d?.features ?? []).map((f) => (
              <tr key={f.feature}>
                <Td mono className="!pl-0 text-xs">{f.feature}</Td>
                <Td align="right" mono>{n3(f.psi)}</Td>
                <Td align="right" mono className="hidden text-muted sm:table-cell">{n3(f.warn_at)}</Td>
                <Td align="right" mono className="hidden text-muted sm:table-cell">{n3(f.fail_at)}</Td>
                <Td className="!pr-0"><GateBadge s={f.status} /></Td>
              </tr>
            ))}
            {(d?.features ?? []).length === 0 && (
              <tr><Td colSpan={5} className="!px-0 text-muted">{d?.reasons.join("; ") || "No drift data."}</Td></tr>
            )}
          </tbody>
        </Table>
        <p className="mt-2 text-xs text-subtle">Thresholds come from the model&apos;s own training history (95th / 99th percentile PSI for same-length windows), floored by configured minimums.</p>
      </div>
      <div>
        <div className="mb-3 flex items-center gap-2 text-sm font-medium">
          Calibration on realised outcomes <GateBadge s={c?.status} />
        </div>
        <div className="mb-4 grid grid-cols-3 gap-2">
          {[
            ["Live ECE", n3(c?.live_ece)],
            ["Backtest ECE", n3(c?.backtest_ece)],
            ["Decay", c?.decay === undefined ? "—" : (c.decay >= 0 ? "+" : "") + c.decay.toFixed(3)],
            ["Evaluated", String(c?.evaluated ?? 0)],
            ["Matured", String(c?.matured ?? 0)],
            ["Pending", String(c?.pending ?? 0)],
          ].map(([k, v]) => (
            <div key={k} className="rounded-lg bg-sunken px-3 py-2">
              <div className="text-xs text-muted">{k}</div>
              <div className="font-mono text-sm">{v}</div>
            </div>
          ))}
        </div>
        {c?.curve && c.curve.length > 0 ? <CalibrationScatter curve={c.curve} /> : <p className="text-sm text-muted">{c?.reasons.join("; ") || "No matured predictions yet."}</p>}
      </div>
    </div>
  );
}

export default function MonitoringPage() {
  usePageTitle("Model monitoring");
  const { guard, isAdmin } = useSession();
  const toast = useToast();
  const [ov, setOv] = useState<MonitoringOverview | null>(null);
  const [runs, setRuns] = useState<MonitorRun[]>([]);
  const [busy, setBusy] = useState(false);
  const [picked, setPicked] = useState<MonitorRun | null>(null);

  const load = useCallback(async () => {
    try {
      const [o, r] = await Promise.all([guard((t) => api.monitoringOverview(t)), guard((t) => api.monitoringRuns(t))]);
      if (o) setOv(o);
      if (r) setRuns(r);
    } catch (err) {
      toast({ tone: "error", title: "Could not load monitoring", body: err instanceof Error ? err.message : undefined });
    }
  }, [guard, toast]);

  useEffect(() => {
    if (isAdmin) void load();
  }, [isAdmin, load]);

  async function pick(id: number) {
    try {
      const r = await guard((t) => api.monitoringRun(t, id));
      if (r) setPicked(r);
    } catch (err) {
      toast({ tone: "error", title: "Could not load the run", body: err instanceof Error ? err.message : undefined });
    }
  }

  async function runNow() {
    setBusy(true);
    try {
      const r = await guard((t) => api.runMonitoring(t));
      if (r) {
        toast({
          tone: r.some((x) => x.status === "FAIL") ? "error" : "success",
          title: r.length ? r.map((x) => `${x.model_name}: ${x.status}${x.action === "retired" ? " → retired" : ""}`).join(" · ") : "No active model to monitor",
        });
        window.dispatchEvent(new Event("aegis:alerts-changed"));
      }
      await load();
    } catch (err) {
      toast({ tone: "error", title: "Monitoring failed", body: err instanceof Error ? err.message : undefined });
    } finally {
      setBusy(false);
    }
  }

  if (!isAdmin) {
    return (
      <Card>
        <EmptyState icon={<Lock size={20} />} title="Admins only" body="Model monitoring is available to admin accounts." />
      </Card>
    );
  }

  return (
    <div className="space-y-6">
      <PageHeader
        title="Model monitoring"
        description="Each active model is checked daily for feature drift against its own training data and for calibration decay on its own realised predictions. A FAIL retires it automatically and raises a critical alert."
        actions={<Button variant="primary" loading={busy} onClick={runNow} icon={<Play size={15} />}>{busy ? "Checking…" : "Run monitoring now"}</Button>}
      />

      {ov === null && <LoadingRows rows={6} />}
      {ov && ov.models.length === 0 && (
        <Card>
          <EmptyState icon={<Activity size={20} />} title="No active or monitored model" body="Activate a model on Backtests & model." />
        </Card>
      )}
      {ov?.models.map((m) => (
        <Card key={m.model_id} title={`${m.name}`} description={`${m.horizon}-day horizon · ${m.status} · ${m.predictions} predictions logged · valid from ${istDateTime(m.valid_from)}`} actions={<GateBadge s={m.latest?.status} />}>
          <div className="mb-4 flex flex-wrap items-center gap-3 text-sm">
            {m.latest?.action === "retired" && <span className="inline-flex items-center gap-1 text-fail"><XCircle size={14} aria-hidden /> Retired automatically</span>}
            {!m.monitorable && <span className="inline-flex items-center gap-1 text-fail"><XCircle size={14} aria-hidden /> No training reference: cannot be monitored</span>}
            {m.latest && <span className="text-xs text-muted">Last check {istDateTime(m.latest.as_of)}</span>}
          </div>
          {m.latest && m.latest.reasons.length > 0 && (
            <ul className="mb-5 space-y-1 text-xs text-warn">
              {m.latest.reasons.map((r) => (
                <li key={r} className="flex gap-1.5"><CircleHelp size={13} className="mt-0.5 shrink-0" aria-hidden />{r}</li>
              ))}
            </ul>
          )}
          {m.latest ? <RunDetail r={m.latest} /> : <p className="text-sm text-muted">Not checked yet.</p>}
        </Card>
      ))}

      {runs.length > 0 && (
        <Card title="History" description="Select a run for its full drift table and calibration." bodyClassName="pb-2">
          <Table>
            <thead>
              <tr>
                <Th>#</Th>
                <Th>As of</Th>
                <Th className="hidden md:table-cell">Model</Th>
                <Th>Overall</Th>
                <Th className="hidden sm:table-cell">Drift</Th>
                <Th className="hidden sm:table-cell">Calibration</Th>
                <Th align="right" className="hidden lg:table-cell">Max PSI</Th>
                <Th align="right" className="hidden lg:table-cell">Live ECE</Th>
              </tr>
            </thead>
            <tbody>
              {runs.map((r) => (
                <tr
                  key={r.id}
                  className={cx("cursor-pointer hover:bg-hover", picked?.id === r.id && "bg-accent-soft")}
                  onClick={() => void pick(r.id)}
                  tabIndex={0}
                  onKeyDown={(e) => { if (e.key === "Enter") void pick(r.id); }}
                  aria-label={`Show monitoring run ${r.id}`}
                >
                  <Td mono className="text-subtle">{r.id}</Td>
                  <Td>{istDateTime(r.as_of)}</Td>
                  <Td mono className="hidden text-xs md:table-cell">{r.model_name}</Td>
                  <Td><GateBadge s={r.status} />{r.action === "retired" && <span className="ml-2 text-xs text-fail">retired</span>}</Td>
                  <Td className="hidden sm:table-cell"><GateBadge s={r.drift_status} /></Td>
                  <Td className="hidden sm:table-cell"><GateBadge s={r.calibration_status} /></Td>
                  <Td align="right" mono className="hidden lg:table-cell">{n3(r.max_psi)}</Td>
                  <Td align="right" mono className="hidden lg:table-cell">{n3(r.live_ece)}</Td>
                </tr>
              ))}
            </tbody>
          </Table>
        </Card>
      )}

      {picked && (
        <Card
          title={`Run #${picked.id} · ${picked.model_name ?? ""}`}
          description={istDateTime(picked.as_of)}
          actions={<IconButton label="Close run details" onClick={() => setPicked(null)}><X size={16} /></IconButton>}
        >
          {picked.reasons.length > 0 && (
            <ul className="mb-5 space-y-1 text-xs text-warn">
              {picked.reasons.map((x) => <li key={x}>{x}</li>)}
            </ul>
          )}
          <RunDetail r={picked} />
        </Card>
      )}
    </div>
  );
}
