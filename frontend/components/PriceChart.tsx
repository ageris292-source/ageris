"use client";

import {
  Bar,
  BarChart,
  CartesianGrid,
  Line,
  LineChart,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
  type TooltipProps,
} from "recharts";
import type { BarOut, IndicatorSeries } from "@/lib/api";

// Categorical slots 1-3 (dark steps), validated as a set against the panel
// surface #161c23: CVD dE >= 9.4, normal-vision dE >= 26.5, contrast >= 3:1.
// SMAs are also dashed, so identity never relies on colour alone.
const SERIES = "#3987e5";
const SMA_MID = "#d95926";
const SMA_LONG = "#199e70";
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
  smaMid: number | null;
  smaLong: number | null;
  rsi: number | null;
}

const inr = new Intl.NumberFormat("en-IN", { maximumFractionDigits: 2, minimumFractionDigits: 2 });
const compact = new Intl.NumberFormat("en-IN", { notation: "compact", maximumFractionDigits: 1 });

function fmtDate(iso: string) {
  const d = new Date(iso + "T00:00:00");
  return d.toLocaleDateString("en-IN", { day: "numeric", month: "short", year: "2-digit" });
}

function Row({ k, v, cls = "" }: { k: string; v: string; cls?: string }) {
  return (
    <>
      <dt className="text-muted">{k}</dt>
      <dd className={`text-right ${cls}`}>{v}</dd>
    </>
  );
}

function PriceTooltip({ active, payload, mid, long }: TooltipProps<number, string> & { mid?: number; long?: number }) {
  if (!active || !payload?.length) return null;
  const p = payload[0].payload as Point;
  return (
    <div className="rounded border border-line bg-surface px-3 py-2 text-xs shadow-lg">
      <div className="mb-1 font-medium text-ink">{fmtDate(p.session)}</div>
      <dl className="grid grid-cols-[auto_auto] gap-x-3 gap-y-0.5 font-mono">
        <Row k="Close" v={`₹${inr.format(p.close)}`} cls="text-ink" />
        <Row k="Open" v={`₹${inr.format(p.open)}`} />
        <Row k="High" v={`₹${inr.format(p.high)}`} />
        <Row k="Low" v={`₹${inr.format(p.low)}`} />
        <Row k="Volume" v={compact.format(p.volume)} />
        {mid && p.smaMid !== null && <Row k={`SMA ${mid}`} v={`₹${inr.format(p.smaMid)}`} />}
        {long && p.smaLong !== null && <Row k={`SMA ${long}`} v={`₹${inr.format(p.smaLong)}`} />}
        {p.rsi !== null && <Row k="RSI" v={p.rsi.toFixed(1)} />}
        {p.version > 1 && <Row k="Revision" v={`v${p.version}`} cls="text-unknown" />}
      </dl>
    </div>
  );
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

export function PriceChart({ bars, indicators }: { bars: BarOut[]; indicators?: IndicatorSeries | null }) {
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
    return <p className="py-16 text-center text-sm text-muted">No stored prices in this range.</p>;
  }
  const overlays = Boolean(indicators && bySession.size);
  const mid = indicators?.sma_mid_period;
  const long = indicators?.sma_long_period;
  const axis = { stroke: GRID, tick: { fill: MUTED, fontSize: 11 }, tickLine: false };
  const margin = { top: 4, right: 8, bottom: 0, left: 0 };
  return (
    <div>
      {overlays && (
        <div className="mb-2 flex flex-wrap gap-4 text-xs text-muted" aria-label="Legend">
          <LegendItem color={SERIES} label="Close" />
          <LegendItem color={SMA_MID} label={`SMA ${mid}`} dashed />
          <LegendItem color={SMA_LONG} label={`SMA ${long}`} dashed />
        </div>
      )}
      <div className="h-72">
        <ResponsiveContainer width="100%" height="100%">
          <LineChart data={data} syncId="px" margin={{ ...margin, top: 8 }}>
            <CartesianGrid stroke={GRID} vertical={false} />
            <XAxis dataKey="session" {...axis} tickFormatter={fmtDate} minTickGap={48} hide />
            <YAxis {...axis} orientation="right" domain={["auto", "auto"]} width={64} tickFormatter={(v: number) => inr.format(v)} />
            <Tooltip content={<PriceTooltip mid={mid} long={long} />} cursor={{ stroke: MUTED, strokeWidth: 1 }} isAnimationActive={false} />
            {overlays && (
              <Line type="linear" dataKey="smaLong" stroke={SMA_LONG} strokeWidth={2} strokeDasharray="5 4" dot={false} activeDot={false} connectNulls={false} isAnimationActive={false} />
            )}
            {overlays && (
              <Line type="linear" dataKey="smaMid" stroke={SMA_MID} strokeWidth={2} strokeDasharray="5 4" dot={false} activeDot={false} connectNulls={false} isAnimationActive={false} />
            )}
            <Line type="linear" dataKey="close" stroke={SERIES} strokeWidth={2} dot={false} activeDot={{ r: 4, stroke: "#161c23", strokeWidth: 2, fill: SERIES }} isAnimationActive={false} />
          </LineChart>
        </ResponsiveContainer>
      </div>
      <div className="mt-1 h-20">
        <ResponsiveContainer width="100%" height="100%">
          <BarChart data={data} syncId="px" margin={margin} barCategoryGap={1}>
            <XAxis dataKey="session" {...axis} tickFormatter={fmtDate} minTickGap={48} hide={overlays} />
            <YAxis {...axis} orientation="right" width={64} tickFormatter={(v: number) => compact.format(v)} />
            <Tooltip content={() => null} cursor={{ fill: "rgba(139,152,165,0.12)" }} />
            <Bar dataKey="volume" fill={MUTED} fillOpacity={0.55} radius={[2, 2, 0, 0]} isAnimationActive={false} />
          </BarChart>
        </ResponsiveContainer>
      </div>
      {overlays && indicators && (
        <div className="mt-1 h-24">
          <ResponsiveContainer width="100%" height="100%">
            <LineChart data={data} syncId="px" margin={margin}>
              <XAxis dataKey="session" {...axis} tickFormatter={fmtDate} minTickGap={48} />
              <YAxis {...axis} orientation="right" width={64} domain={[0, 100]} ticks={[indicators.rsi_oversold, indicators.rsi_overbought]} />
              <ReferenceLine y={indicators.rsi_overbought} stroke={MUTED} strokeDasharray="3 3" />
              <ReferenceLine y={indicators.rsi_oversold} stroke={MUTED} strokeDasharray="3 3" />
              <Tooltip content={() => null} cursor={{ stroke: MUTED, strokeWidth: 1 }} />
              <Line type="linear" dataKey="rsi" stroke={SERIES} strokeWidth={1.5} dot={false} activeDot={false} isAnimationActive={false} />
            </LineChart>
          </ResponsiveContainer>
        </div>
      )}
      <p className="mt-1 text-right text-[11px] text-muted">
        Volume (shares){overlays ? " · RSI with overbought / oversold lines" : ""}
      </p>
    </div>
  );
}
