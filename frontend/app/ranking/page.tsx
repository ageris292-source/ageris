"use client";

import { CheckCircle2, OctagonPause, Play, ShieldCheck, Trophy, XCircle } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useCallback, useEffect, useState } from "react";
import { Bar, BarChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis, type TooltipProps } from "recharts";
import { ChartTooltipBox } from "@/components/charts";
import { usePageTitle } from "@/components/usePageTitle";
import { useSession } from "@/components/providers/SessionProvider";
import { useChartColors } from "@/components/providers/ThemeProvider";
import { useToast } from "@/components/providers/ToastProvider";
import { StanceBadge } from "@/components/ui/Status";
import {
  Badge,
  Button,
  Callout,
  Card,
  EmptyState,
  LinkButton,
  LoadingRows,
  PageHeader,
  Segmented,
  Table,
  Td,
  Th,
  cx,
} from "@/components/ui/core";
import { api, type Counterfactuals, type RankingRow, type RankingRun } from "@/lib/api";
import { ago, inr, istDateTime, num, pct, signedPct, toneOf } from "@/lib/format";

function GateChart({ data }: { data: { gate: string; n: number }[] }) {
  const c = useChartColors();
  const Tip = ({ active, payload }: TooltipProps<number, string>) =>
    active && payload?.length ? (
      <ChartTooltipBox title={String((payload[0].payload as { gate: string }).gate)} rows={[["Stocks blocked first here", String(payload[0].value)]]} />
    ) : null;
  return (
    <div style={{ height: Math.max(140, data.length * 30 + 30) }}>
      <ResponsiveContainer>
        <BarChart data={data} layout="vertical" margin={{ left: 8, right: 16, top: 4, bottom: 4 }} barCategoryGap={6}>
          <CartesianGrid stroke={c.grid} horizontal={false} />
          <XAxis type="number" allowDecimals={false} tick={{ fill: c.axis, fontSize: 11 }} tickLine={false} axisLine={{ stroke: c.grid }} />
          <YAxis type="category" dataKey="gate" width={150} tick={{ fill: c.axis, fontSize: 11 }} tickLine={false} axisLine={false} />
          <Tooltip content={<Tip />} cursor={{ fill: c.grid, opacity: 0.4 }} isAnimationActive={false} />
          <Bar dataKey="n" fill={c.s1} radius={[0, 4, 4, 0]} maxBarSize={26} isAnimationActive={false} />
        </BarChart>
      </ResponsiveContainer>
    </div>
  );
}

function tradeLink(r: RankingRow) {
  const p = new URLSearchParams({ ticker: r.ticker });
  if (r.entry) p.set("entry", r.entry.toFixed(2));
  if (r.stop) p.set("stop", r.stop.toFixed(2));
  if (r.target) p.set("target", r.target.toFixed(2));
  if (r.quantity) p.set("qty", String(r.quantity));
  return `/trade?${p}`;
}

export default function RankingPage() {
  usePageTitle("Opportunities");
  const { guard, isAdmin } = useSession();
  const toast = useToast();
  const router = useRouter();
  const [run, setRun] = useState<RankingRun | null | undefined>(undefined);
  const [history, setHistory] = useState<RankingRun[]>([]);
  const [cf, setCf] = useState<Counterfactuals | null>(null);
  const [busy, setBusy] = useState(false);
  const [show, setShow] = useState<"all" | "qualified">("all");

  const load = useCallback(async () => {
    guard((t) => api.rankingHistory(t)).then((h) => h && setHistory(h)).catch(() => {});
    guard((t) => api.counterfactuals(t)).then((c) => c && setCf(c)).catch(() => {});
    guard((t) => api.latestRanking(t))
      .then((r) => setRun(r ?? null))
      .catch(() => setRun(null)); // 404: no ranking yet
  }, [guard]);

  useEffect(() => {
    void load();
  }, [load]);

  async function runNow() {
    setBusy(true);
    try {
      const r = await guard((t) => api.runRanking(t));
      if (r) {
        setRun(r);
        toast({ tone: r.qualified ? "success" : "info", title: r.headline });
        window.dispatchEvent(new Event("aegis:alerts-changed"));
      }
      await load();
    } catch (err) {
      toast({ tone: "error", title: "Ranking failed", body: err instanceof Error ? err.message : undefined });
    } finally {
      setBusy(false);
    }
  }

  const gates = Object.entries(run?.gate_failure_counts ?? {}).map(([gate, n]) => ({ gate, n }));
  const rows = (run?.rows ?? []).filter((r) => show === "all" || r.qualified);
  const qualified = run?.qualified ?? 0;

  return (
    <div className="space-y-6">
      <PageHeader
        title="Opportunities"
        description="Each stock gets the same standardised candidate trade (entry at the last close, stop from ATR, fixed reward multiple), evaluated by the 24-gate engine. Qualifying is not an order."
        actions={isAdmin && <Button variant="primary" loading={busy} onClick={runNow} icon={<Play size={15} />}>{busy ? "Ranking…" : "Run ranking now"}</Button>}
      />

      {run === undefined && <LoadingRows rows={6} />}
      {run === null && (
        <Card>
          <EmptyState
            icon={<Trophy size={20} />}
            title="No ranking yet"
            body={isAdmin ? "Run one now, or wait for the daily job after the close (19:45 IST)." : "It runs every weekday after the close (19:45 IST)."}
            action={isAdmin && <Button variant="primary" loading={busy} onClick={runNow} icon={<Play size={15} />}>Run ranking now</Button>}
          />
        </Card>
      )}

      {run && (
        <>
          <section className={cx("rounded-xl border p-5", qualified ? "border-pass/40 bg-pass-soft" : "border-line bg-panel")}>
            <div className="flex flex-wrap items-center gap-3">
              <span className={cx("flex h-10 w-10 items-center justify-center rounded-full", qualified ? "bg-pass text-white" : "bg-sunken text-muted")}>
                {qualified ? <CheckCircle2 size={20} aria-hidden /> : <Trophy size={20} aria-hidden />}
              </span>
              <div className="min-w-0 flex-1">
                <p className={cx("text-lg font-semibold", qualified > 0 && "text-pass")}>{run.headline}</p>
                <p className="text-xs text-muted">
                  {istDateTime(run.as_of)} · {run.evaluated} evaluated · {run.horizon}-day horizon · config {run.config_fingerprint.slice(0, 10)}
                </p>
              </div>
            </div>
            {run.operational_blockers.length > 0 && (
              <Callout tone="warn" icon={<OctagonPause size={16} />} className="mt-4" title="Orders are blocked right now, whatever the opportunity">
                <ul className="list-inside list-disc">
                  {run.operational_blockers.map((b) => (
                    <li key={b}>{b}</li>
                  ))}
                </ul>
              </Callout>
            )}
          </section>

          <Card
            title="Ranked candidates"
            actions={
              <Segmented<"all" | "qualified">
                label="Show"
                value={show}
                onChange={setShow}
                options={[
                  { value: "all", label: `All · ${run.rows?.length ?? 0}` },
                  { value: "qualified", label: `Qualified · ${qualified}` },
                ]}
              />
            }
            bodyClassName="pb-2"
          >
            {rows.length === 0 ? (
              <EmptyState compact title={show === "qualified" ? "Nothing qualified" : "No candidates"} body={show === "qualified" ? "“No trade” is a valid answer: the gates are doing their job." : undefined} />
            ) : (
              <Table>
                <thead>
                  <tr>
                    <Th>#</Th>
                    <Th>Stock</Th>
                    <Th>Status</Th>
                    <Th className="hidden lg:table-cell">Research</Th>
                    <Th align="right" className="hidden md:table-cell">Entry · stop · target</Th>
                    <Th align="right">P(profit)</Th>
                    <Th align="right" className="hidden sm:table-cell">Exp. net</Th>
                    <Th align="right" className="hidden md:table-cell">R:R</Th>
                    <Th />
                  </tr>
                </thead>
                <tbody>
                  {rows.map((r) => (
                    <tr key={r.ticker} className="cursor-pointer align-top hover:bg-hover" onClick={() => router.push(`/stocks/${encodeURIComponent(r.ticker)}`)}>
                      <Td mono className="text-subtle">{r.rank}</Td>
                      <Td>
                        <span className="font-mono text-[13px] font-semibold">{r.ticker}</span>
                        <span className="hidden max-w-[200px] truncate text-xs text-muted sm:block">{r.name ?? ""}</span>
                      </Td>
                      <Td>
                        {r.qualified ? (
                          <Badge tone="pass" icon={<CheckCircle2 size={12} aria-hidden />}>Qualified</Badge>
                        ) : (
                          <span title={r.failures.join("\n")}>
                            <Badge tone="neutral" icon={<XCircle size={12} aria-hidden />}>Blocked</Badge>
                            <span className="mt-1 block font-mono text-[11px] text-muted">{r.first_failure}</span>
                          </span>
                        )}
                      </Td>
                      <Td className="hidden lg:table-cell">
                        <StanceBadge stance={r.stance} />
                        {r.composite !== null && <span className="ml-2 font-mono text-xs text-muted">{r.composite.toFixed(0)}</span>}
                      </Td>
                      <Td align="right" mono className="hidden text-xs md:table-cell">
                        {inr(r.entry)}
                        <span className="block text-subtle">
                          {inr(r.stop)} · {inr(r.target)}
                        </span>
                      </Td>
                      <Td align="right" mono>{pct(r.p_profit)}</Td>
                      <Td align="right" mono className={`hidden sm:table-cell ${toneOf(r.expected_net_return)}`}>{signedPct(r.expected_net_return)}</Td>
                      <Td align="right" mono className="hidden md:table-cell">{r.reward_risk == null ? "—" : num(r.reward_risk, 2)}</Td>
                      <Td align="right">
                        {r.qualified && (
                          <span onClick={(e) => e.stopPropagation()}>
                            <LinkButton href={tradeLink(r)} size="sm" variant="primary" icon={<ShieldCheck size={13} />}>Propose</LinkButton>
                          </span>
                        )}
                      </Td>
                    </tr>
                  ))}
                </tbody>
              </Table>
            )}
          </Card>

          <div className="grid gap-6 xl:grid-cols-2">
            <Card title="Why not? First blocking gate" description="Opportunity gates only; operational blockers are listed above.">
              {gates.length === 0 ? <p className="text-sm text-muted">No stock was blocked by an opportunity gate.</p> : <GateChart data={gates} />}
            </Card>
            <Card title="What happened afterwards" description="Realised returns of past candidates — do the gates reject the right trades?" bodyClassName="pb-2">
              {cf && cf.groups.length > 0 ? (
                <Table>
                  <thead>
                    <tr>
                      <Th>Group</Th>
                      <Th align="right">n</Th>
                      <Th align="right">Mean return</Th>
                      <Th align="right">Hit rate</Th>
                      <Th align="right">vs NIFTY 50</Th>
                    </tr>
                  </thead>
                  <tbody>
                    {cf.groups.map((g) => (
                      <tr key={g.group}>
                        <Td mono className="text-xs">{g.group}</Td>
                        <Td align="right" mono>{g.n}</Td>
                        <Td align="right" mono className={toneOf(g.mean_forward_return)}>{signedPct(g.mean_forward_return)}</Td>
                        <Td align="right" mono>{pct(g.hit_rate, 0)}</Td>
                        <Td align="right" mono className={toneOf(g.mean_excess_vs_nifty)}>{signedPct(g.mean_excess_vs_nifty)}</Td>
                      </tr>
                    ))}
                  </tbody>
                </Table>
              ) : (
                <p className="pb-3 text-sm text-muted">No realised outcomes yet.</p>
              )}
              {cf && (
                <p className="py-3 text-xs text-subtle">
                  {cf.rankings} rankings · {cf.pending} candidates still inside their {run.horizon}-session window.
                </p>
              )}
            </Card>
          </div>

          <Card title="History">
            <ul className="-mx-2 space-y-0.5">
              {history.map((h) => (
                <li key={h.id} className="flex flex-wrap items-center justify-between gap-2 rounded-lg px-2 py-2 text-sm hover:bg-hover">
                  <span className="text-muted">
                    <span className="font-mono text-xs text-subtle">#{h.id}</span> {istDateTime(h.as_of)} <span className="text-subtle">· {ago(h.created_at)}</span>
                  </span>
                  <span className={h.qualified ? "font-medium text-pass" : "text-muted"}>{h.headline}</span>
                </li>
              ))}
            </ul>
            <p className="mt-3 text-xs text-subtle">
              Qualified candidates need a live quote, a proposal on <Link href="/trade" className="text-accent hover:underline">New trade</Link> and human approval before any order.
            </p>
          </Card>
        </>
      )}
    </div>
  );
}
