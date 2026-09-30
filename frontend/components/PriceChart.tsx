"use client";

import {
  Area,
  Bar,
  BarChart,
  CartesianGrid,
  ComposedChart,
  Line,
  LineChart,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
  type TooltipProps,
} from "recharts";
import { ChartTooltipBox, useNarrow } from "@/components/charts";
import { useChartColors } from "@/components/providers/ThemeProvider";
import type { BarOut, IndicatorSeries } from "@/lib/api";
import { axisNum, compact, inr, num, shortDate } from "@/lib/format";

interface Point {
  session: string;
  close: number;
  open: number;
  high: number;
  low: number;
  volume: number;
  version: number;
  smaMid: number | null;
  smaLong: number | null;
  rsi: number | null;
}

function LegendItem({ color, label, dashed }: { color: string; label: string; dashed?: boolean }) {
  return (
    <span className="inline-flex items-center gap-1.5">
      <svg width="18" height="6" aria-hidden>
        <line x1="0" y1="3" x2="18" y2="3" stroke={color} strokeWidth="2" strokeDasharray={dashed ? "4 3" : undefined} />
      </svg>
      {label}
    </span>
  );
}

/** Close with SMA overlays (slots 1-3 of the validated palette; SMAs also dashed,
 *  so identity never relies on colour alone), volume and RSI panes sharing a crosshair. */
export function PriceChart({ bars, indicators }: { bars: BarOut[]; indicators?: IndicatorSeries | null }) {
  const c = useChartColors();
  const narrow = useNarrow();
  const yw = narrow ? 52 : 72;
  const bySession = new Map(indicators?.points.map((p) => [p.session, p]) ?? []);
  const data: Point[] = bars.map((b) => {
    const ip = bySession.get(b.session);
    return {
      session: b.session,
      close: Number(b.close),
      open: Number(b.open),
      high: Number(b.high),
      low: Number(b.low),
      volume: b.volume,
      version: b.data_version,
      smaMid: ip?.sma_mid ?? null,
      smaLong: ip?.sma_long ?? null,
      rsi: ip?.rsi ?? null,
    };
  });
  if (data.length === 0) {
    return <p className="py-20 text-center text-sm text-muted">No stored prices in this range.</p>;
  }
  const overlays = Boolean(indicators && bySession.size);
  const mid = indicators?.sma_mid_period;
  const long = indicators?.sma_long_period;
  const up = data[data.length - 1].close >= data[0].close;
  const axis = { stroke: c.grid, tick: { fill: c.axis, fontSize: 11 }, tickLine: false };
  const margin = { top: 4, right: 4, bottom: 0, left: 0 };

  const Tip = ({ active, payload }: TooltipProps<number, string>) => {
    if (!active || !payload?.length) return null;
    const p = payload[0].payload as Point;
    const rows: [string, string, string?][] = [
      ["Close", inr(p.close), c.s1],
      ["Open", inr(p.open)],
      ["High", inr(p.high)],
      ["Low", inr(p.low)],
      ["Volume", compact(p.volume)],
    ];
    if (mid && p.smaMid !== null) rows.push([`SMA ${mid}`, inr(p.smaMid), c.s2]);
    if (long && p.smaLong !== null) rows.push([`SMA ${long}`, inr(p.smaLong), c.s3]);
    if (p.rsi !== null) rows.push(["RSI", num(p.rsi, 1)]);
    if (p.version > 1) rows.push(["Revision", `v${p.version}`]);
    return <ChartTooltipBox title={shortDate(p.session)} rows={rows} />;
  };

  return (
    <div>
      <div className="mb-2 flex flex-wrap gap-4 text-xs text-muted" aria-label="Legend">
        <LegendItem color={c.s1} label="Close" />
        {overlays && <LegendItem color={c.s2} label={`SMA ${mid}`} dashed />}
        {overlays && <LegendItem color={c.s3} label={`SMA ${long}`} dashed />}
      </div>
      <div className="h-56 sm:h-80">
        <ResponsiveContainer width="100%" height="100%">
          <ComposedChart data={data} syncId="px" margin={{ ...margin, top: 8 }}>
            <defs>
              <linearGradient id="px-fill" x1="0" y1="0" x2="0" y2="1">
                <stop offset="0%" stopColor={c.s1} stopOpacity={up ? 0.18 : 0.1} />
                <stop offset="100%" stopColor={c.s1} stopOpacity={0} />
              </linearGradient>
            </defs>
            <CartesianGrid stroke={c.grid} vertical={false} />
            <XAxis dataKey="session" {...axis} tickFormatter={shortDate} minTickGap={56} hide />
            <YAxis {...axis} axisLine={false} orientation="right" domain={["auto", "auto"]} width={yw} tickFormatter={(v: number) => (narrow ? axisNum(v) : inr(v, 0))} />
            <Tooltip content={<Tip />} cursor={{ stroke: c.axis, strokeWidth: 1 }} isAnimationActive={false} />
            <Area type="linear" dataKey="close" stroke="none" fill="url(#px-fill)" isAnimationActive={false} activeDot={false} />
            {overlays && (
              <Line type="linear" dataKey="smaLong" stroke={c.s3} strokeWidth={2} strokeDasharray="5 4" dot={false} activeDot={false} connectNulls={false} isAnimationActive={false} />
            )}
            {overlays && (
              <Line type="linear" dataKey="smaMid" stroke={c.s2} strokeWidth={2} strokeDasharray="5 4" dot={false} activeDot={false} connectNulls={false} isAnimationActive={false} />
            )}
            <Line type="linear" dataKey="close" stroke={c.s1} strokeWidth={2} dot={false} activeDot={{ r: 4, stroke: c.surface, strokeWidth: 2, fill: c.s1 }} isAnimationActive={false} />
          </ComposedChart>
        </ResponsiveContainer>
      </div>
      <div className="mt-1 h-12 sm:h-16">
        <ResponsiveContainer width="100%" height="100%">
          <BarChart data={data} syncId="px" margin={margin} barCategoryGap={1}>
            <XAxis dataKey="session" {...axis} tickFormatter={shortDate} minTickGap={56} hide={overlays} />
            <YAxis {...axis} axisLine={false} orientation="right" width={yw} tickFormatter={(v: number) => compact(v)} tickCount={2} />
            <Tooltip content={() => null} cursor={{ fill: c.grid }} />
            <Bar dataKey="volume" fill={c.axis} fillOpacity={0.5} radius={[2, 2, 0, 0]} isAnimationActive={false} />
          </BarChart>
        </ResponsiveContainer>
      </div>
      {overlays && indicators && (
        <div className="mt-1 h-20 sm:h-24">
          <ResponsiveContainer width="100%" height="100%">
            <LineChart data={data} syncId="px" margin={margin}>
              <XAxis dataKey="session" {...axis} tickFormatter={shortDate} minTickGap={narrow ? 40 : 56} />
              <YAxis {...axis} axisLine={false} orientation="right" width={yw} domain={[0, 100]} ticks={[indicators.rsi_oversold, indicators.rsi_overbought]} />
              <ReferenceLine y={indicators.rsi_overbought} stroke={c.axis} strokeDasharray="3 3" />
              <ReferenceLine y={indicators.rsi_oversold} stroke={c.axis} strokeDasharray="3 3" />
              <Tooltip content={() => null} cursor={{ stroke: c.axis, strokeWidth: 1 }} />
              <Line type="linear" dataKey="rsi" stroke={c.s1} strokeWidth={1.5} dot={false} activeDot={false} isAnimationActive={false} />
            </LineChart>
          </ResponsiveContainer>
        </div>
      )}
      <p className="mt-1 text-right text-[11px] text-subtle">
        Volume (shares){overlays ? ` · RSI with ${indicators?.rsi_overbought}/${indicators?.rsi_oversold} bands` : ""}
      </p>
    </div>
  );
}
