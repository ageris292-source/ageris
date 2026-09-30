"use client";

import { BriefcaseBusiness, FlaskConical, Pencil, Plus, TriangleAlert } from "lucide-react";
import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import { AgentPanel } from "@/components/AgentPanel";
import { usePageTitle } from "@/components/usePageTitle";
import { useSession } from "@/components/providers/SessionProvider";
import { useToast } from "@/components/providers/ToastProvider";
import { Dialog } from "@/components/ui/Dialog";
import { GateBadge } from "@/components/ui/Status";
import {
  Badge,
  Button,
  Callout,
  Card,
  EmptyState,
  Field,
  Input,
  LoadingRows,
  PageHeader,
  Segmented,
  StatCard,
  Table,
  Td,
  Th,
} from "@/components/ui/core";
import { api, ApiError, type PortfolioAnalysis, type PortfolioFit, type PortfolioSummary } from "@/lib/api";
import { humanize, inr, num, pct, signedInr, toneOf } from "@/lib/format";

const RATIO_KEYS = new Set(["sharpe", "sortino", "beta", "effective_positions", "herfindahl", "positions"]);
const MONEY_KEYS = new Set(["equity", "cash", "invested"]);

function Checks({ a }: { a: PortfolioAnalysis }) {
  return (
    <Table>
      <thead>
        <tr>
          <Th>Check</Th>
          <Th>Result</Th>
          <Th className="hidden md:table-cell">Detail</Th>
        </tr>
      </thead>
      <tbody>
        {a.checks.map((c) => (
          <tr key={c.name} className="align-top">
            <Td>
              <span className="font-mono text-[13px]">{c.name}</span>
              <span className="ml-2 text-[11px] text-subtle">{c.kind}</span>
              <span className="block text-xs text-muted md:hidden">{c.reason}</span>
            </Td>
            <Td><GateBadge s={c.status} /></Td>
            <Td className="hidden text-muted md:table-cell">{c.reason}</Td>
          </tr>
        ))}
      </tbody>
    </Table>
  );
}

export default function PortfoliosPage() {
  usePageTitle("Portfolios");
  const { guard } = useSession();
  const toast = useToast();
  const [list, setList] = useState<PortfolioSummary[] | null>(null);
  const [sel, setSel] = useState<number | null>(null);
  const [analysis, setAnalysis] = useState<PortfolioAnalysis | null>(null);
  const [busy, setBusy] = useState(false);
  const [createOpen, setCreateOpen] = useState(false);
  const [name, setName] = useState("");
  const [cash, setCash] = useState("1000000");
  const [posOpen, setPosOpen] = useState(false);
  const [pos, setPos] = useState({ ticker: "", quantity: "", avg_cost: "" });
  const [cand, setCand] = useState({ ticker: "", weight: "5" });
  const [fit, setFit] = useState<PortfolioFit | null>(null);
  const [fitBusy, setFitBusy] = useState(false);

  const fail = useCallback(
    (title: string, err: unknown) => toast({ tone: "error", title, body: err instanceof ApiError || err instanceof Error ? err.message : undefined }),
    [toast],
  );

  const load = useCallback(async () => {
    try {
      const rows = await guard((t) => api.portfolios(t));
      if (rows) {
        setList(rows);
        setSel((s) => s ?? rows[0]?.id ?? null);
      }
    } catch (err) {
      fail("Could not load portfolios", err);
    }
  }, [guard, fail]);

  const analyse = useCallback(async () => {
    if (sel === null) return;
    setBusy(true);
    try {
      const a = await guard((t) => api.portfolioAnalysis(t, sel));
      if (a) setAnalysis(a);
    } catch (err) {
      fail("Analysis failed", err);
    } finally {
      setBusy(false);
    }
  }, [guard, sel, fail]);

  useEffect(() => {
    void load();
  }, [load]);
  useEffect(() => {
    setFit(null);
    void analyse();
  }, [analyse]);

  async function create(e: React.FormEvent) {
    e.preventDefault();
    try {
      const p = await guard((t) => api.createPortfolio(t, name.trim(), cash));
      setName("");
      setCreateOpen(false);
      if (p) {
        setSel(p.id);
        toast({ tone: "success", title: `Created “${p.name}”` });
      }
      await load();
    } catch (err) {
      fail("Could not create the portfolio", err);
    }
  }

  async function savePosition(e: React.FormEvent) {
    e.preventDefault();
    if (sel === null) return;
    try {
      await guard((t) => api.setPosition(t, sel, pos.ticker.trim().toUpperCase(), Number(pos.quantity), pos.avg_cost || "0"));
      toast({ tone: "success", title: Number(pos.quantity) === 0 ? `Removed ${pos.ticker.toUpperCase()}` : `Saved ${pos.ticker.toUpperCase()}` });
      setPos({ ticker: "", quantity: "", avg_cost: "" });
      setPosOpen(false);
      await load();
      await analyse();
    } catch (err) {
      fail("Could not save the holding", err);
    }
  }

  async function testFit(e?: React.FormEvent) {
    e?.preventDefault();
    if (sel === null) return;
    setFitBusy(true);
    try {
      const f = await guard((t) => api.portfolioFit(t, sel, cand.ticker.trim().toUpperCase(), Number(cand.weight) / 100));
      if (f) setFit(f);
    } catch (err) {
      fail("Fit check failed", err);
    } finally {
      setFitBusy(false);
    }
  }

  const current = list?.find((p) => p.id === sel) ?? null;
  const a = analysis && current && analysis.portfolio.id === current.id ? analysis : null;
  const sectors = a ? Object.entries(a.sector_weights).sort((x, y) => y[1] - x[1]) : [];

  return (
    <div className="space-y-6">
      <PageHeader
        title="Portfolios"
        description="Model portfolios for exposure and what-if analysis. Paper portfolios change only through the paper broker."
        actions={
          <>
            {list && list.length > 0 && (
              <Segmented<string>
                label="Portfolio"
                size="md"
                value={String(sel ?? "")}
                onChange={(v) => setSel(Number(v))}
                options={list.map((p) => ({ value: String(p.id), label: <span>{p.name} <span className="text-[11px] opacity-60">{p.kind}</span></span> }))}
              />
            )}
            <Button variant="primary" icon={<Plus size={15} />} onClick={() => setCreateOpen(true)}>New model portfolio</Button>
          </>
        }
      />

      {list === null && <LoadingRows rows={5} />}
      {list?.length === 0 && (
        <Card>
          <EmptyState
            icon={<BriefcaseBusiness size={20} />}
            title="No portfolios yet"
            body="Create a model portfolio to check exposure, limits and how a new stock would fit."
            action={<Button variant="primary" icon={<Plus size={15} />} onClick={() => setCreateOpen(true)}>New model portfolio</Button>}
          />
        </Card>
      )}

      {current && (
        <>
          <div className="grid grid-cols-2 gap-3 lg:grid-cols-4 lg:gap-4">
            <StatCard label="Equity" value={a ? inr(a.metrics.equity, 0) : "—"} />
            <StatCard label="Cash" value={a ? inr(a.metrics.cash, 0) : "—"} />
            <StatCard label="Positions" value={a ? a.holdings.length : "—"} />
            <StatCard
              label="Hard limits"
              value={a ? <GateBadge s={a.limits_status} label={a.limits_status === "PASS" ? "All pass" : a.limits_status === "FAIL" ? "Breached" : "Unknown"} /> : "—"}
              sub="UNKNOWN never passes"
            />
          </div>

          <div className="grid gap-6 xl:grid-cols-3">
            <Card
              className="xl:col-span-2"
              title={`Holdings · ${current.name}`}
              actions={current.kind === "model" && <Button size="sm" icon={<Pencil size={14} />} onClick={() => setPosOpen(true)}>Add or edit holding</Button>}
              bodyClassName="pb-2"
            >
              {!a && busy && <LoadingRows rows={4} />}
              {a && a.holdings.length === 0 && (
                <EmptyState compact title="No holdings" body={current.kind === "model" ? "Add a holding to analyse exposure." : "Filled paper orders appear here."} />
              )}
              {a && a.holdings.length > 0 && (
                <Table>
                  <thead>
                    <tr>
                      <Th>Stock</Th>
                      <Th align="right">Qty</Th>
                      <Th align="right">Price</Th>
                      <Th align="right" className="hidden sm:table-cell">Value</Th>
                      <Th align="right">Weight</Th>
                      <Th align="right" className="hidden md:table-cell">P&L</Th>
                      <Th align="right" className="hidden lg:table-cell">Avg traded / day</Th>
                    </tr>
                  </thead>
                  <tbody>
                    {a.holdings.map((x) => (
                      <tr key={x.ticker} className="hover:bg-hover">
                        <Td>
                          <Link className="font-mono text-[13px] font-semibold hover:underline" href={`/stocks/${encodeURIComponent(x.ticker)}`}>{x.ticker}</Link>
                          <span className="block text-xs capitalize text-muted">{humanize(x.sector).toLowerCase()}</span>
                        </Td>
                        <Td align="right" mono>{x.quantity}</Td>
                        <Td align="right" mono>{x.price === null ? <span className="text-warn">unknown</span> : inr(x.price)}</Td>
                        <Td align="right" mono className="hidden sm:table-cell">{inr(x.value, 0)}</Td>
                        <Td align="right" mono>{pct(x.weight)}</Td>
                        <Td align="right" mono className={`hidden md:table-cell ${toneOf(x.unrealised_pnl)}`}>{signedInr(x.unrealised_pnl)}</Td>
                        <Td align="right" mono className="hidden lg:table-cell">{x.adtv === null ? "—" : `₹${(x.adtv / 1e7).toFixed(1)} cr`}</Td>
                      </tr>
                    ))}
                  </tbody>
                </Table>
              )}
            </Card>

            <Card title="Sector allocation" description="Share of equity by sector.">
              {sectors.length === 0 ? (
                <p className="text-sm text-muted">No exposure.</p>
              ) : (
                <ul className="space-y-3">
                  {sectors.map(([s, w]) => (
                    <li key={s}>
                      <div className="flex justify-between text-sm">
                        <span className="capitalize">{humanize(s).toLowerCase()}</span>
                        <span className="font-mono text-xs">{pct(w)}</span>
                      </div>
                      <div className="mt-1 h-1.5 rounded-full bg-sunken">
                        <div className="h-1.5 rounded-full bg-accent" style={{ width: `${Math.min(100, w * 100)}%` }} />
                      </div>
                    </li>
                  ))}
                </ul>
              )}
            </Card>
          </div>

          {a && (
            <div className="grid items-start gap-6 xl:grid-cols-3">
              <Card className="xl:col-span-2" title="Limit and advisory checks" description="Hard limits block trades; advisory checks inform." bodyClassName="pb-2">
                <Checks a={a} />
              </Card>
              <Card title="Risk" description="Current weights, trailing year.">
                <dl className="grid grid-cols-2 gap-3">
                  {Object.entries(a.metrics)
                    .filter(([k]) => !MONEY_KEYS.has(k))
                    .map(([k, v]) => (
                      <div key={k} className="rounded-lg bg-sunken px-3 py-2">
                        <dt className="truncate text-xs capitalize text-muted">{humanize(k)}</dt>
                        <dd className="font-mono text-sm">{v === null ? "—" : k === "positions" ? num(v, 0) : RATIO_KEYS.has(k) ? num(v, 2) : pct(v, 2)}</dd>
                      </div>
                    ))}
                </dl>
                {a.high_correlation_pairs.length > 0 && (
                  <Callout tone="warn" className="mt-4" icon={<TriangleAlert size={15} />} title="Highly correlated">
                    {a.high_correlation_pairs.map((p) => `${p.a} / ${p.b} (${p.correlation.toFixed(2)})`).join(", ")}
                  </Callout>
                )}
                {a.warnings.map((w) => (
                  <p key={w} className="mt-3 text-xs text-warn">{w}</p>
                ))}
              </Card>
            </div>
          )}

          <Card
            title={
              <span className="flex items-center gap-2">
                <FlaskConical size={15} aria-hidden /> What if I add a stock?
              </span>
            }
            description="Checks limits, concentration and correlation before and after a hypothetical position."
          >
            <form onSubmit={testFit} className="flex flex-wrap items-end gap-3">
              <Field label="Ticker">{(id) => <Input id={id} className="w-40 font-mono uppercase" placeholder="TCS.NS" value={cand.ticker} onChange={(e) => setCand({ ...cand, ticker: e.target.value })} />}</Field>
              <Field label="Target weight (% of equity)">{(id) => <Input id={id} className="w-28 font-mono" inputMode="decimal" value={cand.weight} onChange={(e) => setCand({ ...cand, weight: e.target.value })} />}</Field>
              <Button type="submit" variant="primary" loading={fitBusy} disabled={!cand.ticker}>Check fit</Button>
            </form>
            {fit && (
              <div className="mt-6 space-y-6">
                <AgentPanel title={`Portfolio fit · ${fit.analysis.ticker}`} scoreLabel="Fit score" out={fit.analysis} busy={fitBusy} onRun={() => void testFit()} runLabel="Re-check" />
                <div>
                  <h3 className="mb-2 flex items-center gap-2 text-sm font-semibold">
                    Checks after the trade <Badge>{fit.details.after.limits_status}</Badge>
                  </h3>
                  <Checks a={fit.details.after} />
                </div>
              </div>
            )}
          </Card>
        </>
      )}

      <Dialog
        open={createOpen}
        onClose={() => setCreateOpen(false)}
        title="New model portfolio"
        description="For exposure analysis only; it never trades."
        footer={
          <>
            <Button onClick={() => setCreateOpen(false)}>Cancel</Button>
            <Button variant="primary" type="submit" form="new-model" disabled={name.trim().length < 2}>Create</Button>
          </>
        }
      >
        <form id="new-model" onSubmit={create} className="space-y-4">
          <Field label="Name">{(id) => <Input id={id} value={name} onChange={(e) => setName(e.target.value)} placeholder="e.g. Long-term core" />}</Field>
          <Field label="Cash (₹)">{(id) => <Input id={id} className="font-mono" value={cash} onChange={(e) => setCash(e.target.value)} />}</Field>
        </form>
      </Dialog>

      <Dialog
        open={posOpen}
        onClose={() => setPosOpen(false)}
        title="Add or edit a holding"
        description="Set quantity to 0 to remove a holding."
        footer={
          <>
            <Button onClick={() => setPosOpen(false)}>Cancel</Button>
            <Button variant="primary" type="submit" form="pos-form" disabled={!pos.ticker || pos.quantity === ""}>Save holding</Button>
          </>
        }
      >
        <form id="pos-form" onSubmit={savePosition} className="grid gap-4 sm:grid-cols-3">
          <Field label="Ticker">{(id) => <Input id={id} className="font-mono uppercase" placeholder="TCS.NS" value={pos.ticker} onChange={(e) => setPos({ ...pos, ticker: e.target.value })} />}</Field>
          <Field label="Quantity">{(id) => <Input id={id} className="font-mono" inputMode="numeric" value={pos.quantity} onChange={(e) => setPos({ ...pos, quantity: e.target.value })} />}</Field>
          <Field label="Average cost (₹)">{(id) => <Input id={id} className="font-mono" inputMode="decimal" value={pos.avg_cost} onChange={(e) => setPos({ ...pos, avg_cost: e.target.value })} />}</Field>
        </form>
      </Dialog>
    </div>
  );
}
