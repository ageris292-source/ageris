"use client";

import {
  Bar,
  BarChart,
  CartesianGrid,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
  type TooltipProps,
} from "recharts";
import type { BarOut } from "@/lib/api";

// Single-series chart: one validated hue (dark step, >= 3:1 on the panel),
// recessive grid/axes, text in ink tokens. Price and volume are two charts
// sharing a crosshair (syncId) — never a dual axis.
const SERIES = "#3987e5";
const GRID = "#263039";
const MUTED = "#8b98a5";

interface Point {
  session: string;
  close: number;
  open: number;
  high: number;
  low: number;
  volume: number;
  version: number;
}

const inr = new Intl.NumberFormat("en-IN", { maximumFractionDigits: 2, minimumFractionDigits: 2 });
const compact = new Intl.NumberFormat("en-IN", { notation: "compact", maximumFractionDigits: 1 });

function fmtDate(iso: string) {
  const d = new Date(iso + "T00:00:00");
  return d.toLocaleDateString("en-IN", { day: "numeric", month: "short", year: "2-digit" });
}

function PriceTooltip({ active, payload }: TooltipProps<number, string>) {
  if (!active || !payload?.length) return null;
  const p = payload[0].payload as Point;
  return (
    <div className="rounded border border-line bg-surface px-3 py-2 text-xs shadow-lg">
      <div className="mb-1 font-medium text-ink">{fmtDate(p.session)}</div>
      <dl className="grid grid-cols-[auto_auto] gap-x-3 gap-y-0.5 font-mono">
        <dt className="text-muted">Close</dt><dd className="text-right text-ink">₹{inr.format(p.close)}</dd>
        <dt className="text-muted">Open</dt><dd className="text-right">₹{inr.format(p.open)}</dd>
        <dt className="text-muted">High</dt><dd className="text-right">₹{inr.format(p.high)}</dd>
        <dt className="text-muted">Low</dt><dd className="text-right">₹{inr.format(p.low)}</dd>
        <dt className="text-muted">Volume</dt><dd className="text-right">{compact.format(p.volume)}</dd>
        {p.version > 1 && (
          <>
            <dt className="text-muted">Revision</dt><dd className="text-right text-unknown">v{p.version}</dd>
          </>
        )}
      </dl>
    </div>
  );
}

export function PriceChart({ bars }: { bars: BarOut[] }) {
  const data: Point[] = bars.map((b) => ({
    session: b.session,
    close: Number(b.close),
    open: Number(b.open),
    high: Number(b.high),
    low: Number(b.low),
    volume: b.volume,
    version: b.data_version,
  }));
  if (data.length === 0) {
    return <p className="py-16 text-center text-sm text-muted">No stored prices in this range.</p>;
  }
  const axis = { stroke: GRID, tick: { fill: MUTED, fontSize: 11 }, tickLine: false };
  return (
    <div>
      <div className="h-72">
        <ResponsiveContainer width="100%" height="100%">
          <LineChart data={data} syncId="px" margin={{ top: 8, right: 8, bottom: 0, left: 0 }}>
            <CartesianGrid stroke={GRID} strokeDasharray="0" vertical={false} />
            <XAxis dataKey="session" {...axis} tickFormatter={fmtDate} minTickGap={48} hide />
            <YAxis
              {...axis}
              orientation="right"
              domain={["auto", "auto"]}
              width={64}
              tickFormatter={(v: number) => inr.format(v)}
            />
            <Tooltip
              content={<PriceTooltip />}
              cursor={{ stroke: MUTED, strokeWidth: 1 }}
              isAnimationActive={false}
            />
            <Line
              type="linear"
              dataKey="close"
              stroke={SERIES}
              strokeWidth={2}
              dot={false}
              activeDot={{ r: 4, stroke: "#161c23", strokeWidth: 2, fill: SERIES }}
              isAnimationActive={false}
            />
          </LineChart>
        </ResponsiveContainer>
      </div>
      <div className="mt-1 h-20">
        <ResponsiveContainer width="100%" height="100%">
          <BarChart data={data} syncId="px" margin={{ top: 4, right: 8, bottom: 0, left: 0 }} barCategoryGap={1}>
            <XAxis dataKey="session" {...axis} tickFormatter={fmtDate} minTickGap={48} />
            <YAxis {...axis} orientation="right" width={64} tickFormatter={(v: number) => compact.format(v)} />
            <Tooltip content={() => null} cursor={{ fill: "rgba(139,152,165,0.12)" }} />
            <Bar dataKey="volume" fill={MUTED} fillOpacity={0.55} radius={[2, 2, 0, 0]} isAnimationActive={false} />
          </BarChart>
        </ResponsiveContainer>
      </div>
      <p className="mt-1 text-right text-[11px] text-muted">Volume (shares)</p>
    </div>
  );
}
