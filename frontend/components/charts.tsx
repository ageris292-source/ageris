"use client";

import {
  Area,
  AreaChart,
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
import { useEffect, useState } from "react";
import { useChartColors } from "@/components/providers/ThemeProvider";
import { inr, inrCompact, shortDate } from "@/lib/format";

/** True on phone-width screens; charts use smaller axes and heights there. */
export function useNarrow(query = "(max-width: 639px)") {
  const [narrow, setNarrow] = useState(false);
  useEffect(() => {
    const mq = window.matchMedia(query);
    const on = () => setNarrow(mq.matches);
    on();
    mq.addEventListener("change", on);
    return () => mq.removeEventListener("change", on);
  }, [query]);
  return narrow;
}

export function ChartTooltipBox({ title, rows }: { title: string; rows: [string, string, string?][] }) {
  return (
    <div className="rounded-lg border border-line bg-elevated px-3 py-2 text-xs shadow-[var(--shadow-pop)]">
      <div className="mb-1 font-medium text-ink">{title}</div>
      <dl className="grid grid-cols-[auto_auto] gap-x-4 gap-y-0.5">
        {rows.map(([k, v, color]) => (
          <div key={k} className="contents">
            <dt className="flex items-center gap-1.5 text-muted">
              {color && <span className="inline-block h-2 w-2 rounded-full" style={{ background: color }} aria-hidden />}
              {k}
            </dt>
            <dd className="text-right font-mono text-ink">{v}</dd>
          </div>
        ))}
      </dl>
    </div>
  );
}

/** Single-series equity curve (rupees over time). One series: the title names it, no legend. */
export function EquityChart({
  data,
  height = 220,
}: {
  data: { t: string; equity: number }[];
  height?: number;
}) {
  const c = useChartColors();
  const narrow = useNarrow();
  if (data.length < 2) return null;
  const Tip = ({ active, payload }: TooltipProps<number, string>) => {
    if (!active || !payload?.length) return null;
    const p = payload[0].payload as { t: string; equity: number };
    return <ChartTooltipBox title={shortDate(p.t)} rows={[["Equity", inr(p.equity)]]} />;
  };
  return (
    <div style={{ height: narrow ? Math.round(height * 0.8) : height }}>
      <ResponsiveContainer width="100%" height="100%">
        <AreaChart data={data} margin={{ top: 8, right: 4, bottom: 0, left: 0 }}>
          <defs>
            <linearGradient id="eq-fill" x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stopColor={c.s1} stopOpacity={0.22} />
              <stop offset="100%" stopColor={c.s1} stopOpacity={0} />
            </linearGradient>
          </defs>
          <CartesianGrid stroke={c.grid} vertical={false} />
          <XAxis dataKey="t" tickFormatter={shortDate} tick={{ fill: c.axis, fontSize: 11 }} tickLine={false} axisLine={{ stroke: c.grid }} minTickGap={40} />
          <YAxis
            orientation="right"
            width={narrow ? 58 : 72}
            domain={["auto", "auto"]}
            tickFormatter={(v: number) => inrCompact(v)}
            tick={{ fill: c.axis, fontSize: 11 }}
            tickLine={false}
            axisLine={false}
          />
          <Tooltip content={<Tip />} cursor={{ stroke: c.axis, strokeWidth: 1 }} isAnimationActive={false} />
          <Area
            type="monotone"
            dataKey="equity"
            stroke={c.s1}
            strokeWidth={2}
            fill="url(#eq-fill)"
            activeDot={{ r: 4, stroke: c.surface, strokeWidth: 2, fill: c.s1 }}
            isAnimationActive={false}
          />
        </AreaChart>
      </ResponsiveContainer>
    </div>
  );
}

/**
 * Up to three series indexed to 100 at their first common point (fixed slot
 * order s1, s2, s3; a fourth series is never added: its colour pair fails the
 * all-pairs legibility floor). A legend is always shown; each line also ends
 * with a direct label so identity never relies on colour alone.
 */
export function IndexedLineChart({
  data,
  series,
  height = 260,
}: {
  data: Record<string, number | string | null>[];
  series: { key: string; label: string }[];
  height?: number;
}) {
  const c = useChartColors();
  const narrow = useNarrow();
  const colors = [c.s1, c.s2, c.s3];
  const shown = series.slice(0, 3);
  if (data.length < 2) return null;
  // End labels: the highest-ending series is labelled above its line, the
  // lowest below, so neighbouring labels don't sit on top of each other.
  const lastOf = (k: string) => {
    for (let j = data.length - 1; j >= 0; j--) if (typeof data[j][k] === "number") return data[j][k] as number;
    return null;
  };
  const order = shown.map((s) => ({ k: s.key, v: lastOf(s.key) ?? -Infinity })).sort((a, b) => b.v - a.v);
  const dyOf = (k: string) => {
    const r = order.findIndex((o) => o.k === k);
    return r === order.length - 1 && order.length > 1 ? 16 : -8;
  };
  const Tip = ({ active, payload }: TooltipProps<number, string>) => {
    if (!active || !payload?.length) return null;
    const p = payload[0].payload as Record<string, number | string | null>;
    return (
      <ChartTooltipBox
        title={shortDate(String(p.t))}
        rows={shown.map((s, i) => {
          const v = p[s.key];
          return [s.label, typeof v === "number" ? `${v.toFixed(1)} (${v >= 100 ? "+" : ""}${(v - 100).toFixed(1)}%)` : "—", colors[i]] as [string, string, string];
        })}
      />
    );
  };
  return (
    <div>
      <ul className="mb-2 flex flex-wrap gap-x-4 gap-y-1 text-xs text-muted" aria-label="Legend">
        {shown.map((s, i) => (
          <li key={s.key} className="flex items-center gap-1.5">
            <span className="inline-block h-0.5 w-4 rounded" style={{ background: colors[i] }} aria-hidden />
            {s.label}
          </li>
        ))}
      </ul>
      <div style={{ height: narrow ? Math.round(height * 0.8) : height }}>
        <ResponsiveContainer width="100%" height="100%">
          <LineChart data={data} margin={{ top: 8, right: 8, bottom: 0, left: 0 }}>
            <CartesianGrid stroke={c.grid} vertical={false} />
            <XAxis dataKey="t" tickFormatter={shortDate} tick={{ fill: c.axis, fontSize: 11 }} tickLine={false} axisLine={{ stroke: c.grid }} minTickGap={40} />
            <YAxis
              orientation="right"
              width={narrow ? 40 : 48}
              domain={["auto", "auto"]}
              tickFormatter={(v: number) => v.toFixed(0)}
              tick={{ fill: c.axis, fontSize: 11 }}
              tickLine={false}
              axisLine={false}
            />
            <ReferenceLine y={100} stroke={c.axis} strokeDasharray="3 3" strokeOpacity={0.6} />
            <Tooltip content={<Tip />} cursor={{ stroke: c.axis, strokeWidth: 1 }} isAnimationActive={false} />
            {shown.map((s, i) => {
              // Direct label on the series' last value, in text ink (never the series colour).
              let last = -1;
              data.forEach((d, j) => {
                if (typeof d[s.key] === "number") last = j;
              });
              const EndLabel = (props: { x?: number; y?: number; index?: number }) =>
                props.index === last && props.x !== undefined && props.y !== undefined ? (
                  <text x={props.x - 6} y={props.y + dyOf(s.key)} textAnchor="end" fontSize={11} fontWeight={600} fill={c.muted}>
                    {s.label}
                  </text>
                ) : null;
              return (
              <Line
                key={s.key}
                label={<EndLabel />}
                type="monotone"
                dataKey={s.key}
                name={s.label}
                stroke={colors[i]}
                strokeWidth={2}
                dot={false}
                connectNulls
                activeDot={{ r: 4, stroke: c.surface, strokeWidth: 2, fill: colors[i] }}
                isAnimationActive={false}
              />
              );
            })}
          </LineChart>
        </ResponsiveContainer>
      </div>
    </div>
  );
}
