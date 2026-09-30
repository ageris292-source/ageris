"use client";

import {
  Area,
  AreaChart,
  CartesianGrid,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
  type TooltipProps,
} from "recharts";
import { useChartColors } from "@/components/providers/ThemeProvider";
import { inr, inrCompact, shortDate } from "@/lib/format";

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
  if (data.length < 2) return null;
  const Tip = ({ active, payload }: TooltipProps<number, string>) => {
    if (!active || !payload?.length) return null;
    const p = payload[0].payload as { t: string; equity: number };
    return <ChartTooltipBox title={shortDate(p.t)} rows={[["Equity", inr(p.equity)]]} />;
  };
  return (
    <div style={{ height }}>
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
            width={72}
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
