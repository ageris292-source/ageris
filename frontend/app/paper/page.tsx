"use client";

import { CheckCircle2, Hand, Plus, RefreshCw, ScrollText, ShieldCheck, TriangleAlert, Wallet, XCircle } from "lucide-react";
import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import { EquityChart } from "@/components/charts";
import { usePageTitle } from "@/components/usePageTitle";
import { useSession } from "@/components/providers/SessionProvider";
import { useToast } from "@/components/providers/ToastProvider";
import { ConfirmDialog, Dialog } from "@/components/ui/Dialog";
import {
  Badge,
  Button,
  Callout,
  Card,
  DesktopOnly,
  EmptyState,
  Field,
  Input,
  LinkButton,
  LoadingRows,
  MobileItem,
  MobileList,
  PageHeader,
  Select,
  StatCard,
  Table,
  Tabs,
  Td,
  Th,
  cx,
} from "@/components/ui/core";
import {
  api,
  ApiError,
  type PaperOrderOut,
  type PaperPortfolioOut,
  type PortfolioSummary,
  type ProposalRow,
} from "@/lib/api";
import { humanize, inr, istDate, istDateTime, pct, signedInr, signedPct, toneOf } from "@/lib/format";

function newKey(): string {
  try {
    return crypto.randomUUID();
  } catch {
    return `k-${Date.now()}-${Math.random().toString(36).slice(2)}`;
  }
}

type TabKey = "positions" | "theses" | "fills" | "orders";

function ThesisCard({ t, price }: { t: PaperPortfolioOut["theses"][number]; price: number | null }) {
  const stop = Number(t.stop_loss);
  const target = Number(t.target);
  const entry = Number(t.entry_price);
  const span = target - stop;
  const pos = (v: number) => Math.max(0, Math.min(100, ((v - stop) / span) * 100));
  const open = t.status === "OPEN";
  return (
    <div className="rounded-lg border border-line p-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <Link href={`/stocks/${encodeURIComponent(t.ticker)}`} className="font-mono text-sm font-semibold hover:underline">
          {t.ticker}
        </Link>
        <Badge tone={open ? "info" : "neutral"}>{humanize(t.status).toLowerCase()}</Badge>
      </div>
      {span > 0 && (
        <div className="mt-4">
          <div className="relative h-2 rounded-full bg-gradient-to-r from-fail/40 via-sunken to-pass/40" aria-hidden>
            <span className="absolute -top-1 h-4 w-0.5 bg-line-strong" style={{ left: `${pos(entry)}%` }} />
            {price !== null && open && (
              <span className="absolute -top-1.5 h-5 w-5 -translate-x-1/2 rounded-full border-2 border-panel bg-accent" style={{ left: `${pos(price)}%` }} />
            )}
          </div>
          <div className="mt-2 flex justify-between text-xs">
            <span className="text-fail">Stop {inr(stop)}</span>
            <span className="text-muted">Entry {inr(entry)}</span>
            <span className="text-pass">Target {inr(target)}</span>
          </div>
          {price !== null && open && (
            <p className="mt-1 text-center text-xs">
              Now <span className="font-mono font-medium">{inr(price)}</span>{" "}
              <span className={toneOf(price - entry)}>({signedPct(price / entry - 1)})</span>
            </p>
          )}
        </div>
      )}
      <p className="mt-3 text-xs text-muted">
        Opened {istDate(t.opened_at)} · horizon ends {istDate(t.horizon_end)}
      </p>
      {t.events.length > 0 && (
        <ul className="mt-3 space-y-1.5 border-t border-line pt-3 text-xs">
          {t.events.map((e) => (
            <li key={e.kind + e.session} className="flex gap-1.5 text-warn">
              <TriangleAlert size={13} className="mt-0.5 shrink-0" aria-hidden />
              <span>
                {istDate(e.session)} · {humanize(e.kind)}: {e.detail}
                {e.exit_proposal_id && ` → exit proposal #${e.exit_proposal_id} (${e.exit_decision})`}
              </span>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

export default function PaperPage() {
  usePageTitle("Paper trading");
  const { guard, isAdmin, health } = useSession();
  const toast = useToast();
  const [pfs, setPfs] = useState<PortfolioSummary[] | null>(null);
  const [sel, setSel] = useState<number | null>(null);
  const [data, setData] = useState<PaperPortfolioOut | null>(null);
  const [orders, setOrders] = useState<PaperOrderOut[]>([]);
  const [pending, setPending] = useState<ProposalRow[]>([]);
  const [tab, setTab] = useState<TabKey>("positions");
  const [confirm, setConfirm] = useState<ProposalRow | null>(null);
  const [placing, setPlacing] = useState(false);
  const [checking, setChecking] = useState(false);
  const [creating, setCreating] = useState(false);
  const [newName, setNewName] = useState("Paper");
  const [newCash, setNewCash] = useState("1000000");
  const [busyCreate, setBusyCreate] = useState(false);

  const load = useCallback(async () => {
    try {
      const all = await guard((t) => api.portfolios(t));
      const paper = (all ?? []).filter((p) => p.kind === "paper");
      setPfs(paper);
      const id = sel ?? paper[0]?.id ?? null;
      if (id === null) return;
      setSel(id);
      const [d, o, p] = await Promise.all([
        guard((t) => api.paperPortfolio(t, id)),
        guard((t) => api.paperOrders(t, id)),
        guard((t) => api.proposalsFor(t, id)),
      ]);
      if (d) setData(d);
      if (o) setOrders(o);
      if (p && o) {
        const done = new Set(o.filter((x) => x.status === "FILLED").map((x) => x.decision_id));
        setPending(p.filter((x) => x.decision === "APPROVED" && !done.has(x.decision_id) && !x.rationale?.startsWith("pre-order re-check")));
      }
    } catch (err) {
      toast({ tone: "error", title: "Could not load paper trading", body: err instanceof Error ? err.message : undefined });
    }
  }, [guard, sel, toast]);

  useEffect(() => {
    void load();
  }, [load]);

  async function createPaper(e: React.FormEvent) {
    e.preventDefault();
    setBusyCreate(true);
    try {
      const p = await guard((t) => api.createPortfolio(t, newName.trim(), newCash, "paper"));
      if (p) {
        setSel(p.id);
        setData(null);
        setCreating(false);
        toast({ tone: "success", title: `Created “${p.name}”`, body: `Starting cash ${inr(p.cash, 0)} (simulated).` });
      }
      await load();
    } catch (err) {
      toast({ tone: "error", title: "Could not create the portfolio", body: err instanceof ApiError ? err.message : undefined });
    } finally {
      setBusyCreate(false);
    }
  }

  async function approve() {
    if (!confirm) return;
    setPlacing(true);
    try {
      const o = await guard((t) => api.placePaperOrder(t, confirm.decision_id, newKey()));
      if (o) {
        toast({
          tone: o.status === "FILLED" ? "success" : "error",
          title: `Order #${o.id} ${o.status.toLowerCase()}`,
          body: o.reason,
        });
      }
      setConfirm(null);
      await load();
    } catch (err) {
      toast({ tone: "error", title: "Order not placed", body: err instanceof ApiError ? err.message : undefined });
    } finally {
      setPlacing(false);
    }
  }

  async function monitor() {
    setChecking(true);
    try {
      const r = await guard((t) => api.runMonitor(t));
      toast({
        tone: r && r.events.length ? "warning" : "success",
        title: r && r.events.length ? `${r.events.length} thesis event(s)` : "No new thesis events",
        body: r?.events.map((e) => `${humanize(e.kind)}: ${e.detail}`).join(" · "),
      });
      window.dispatchEvent(new Event("aegis:alerts-changed"));
      await load();
    } catch (err) {
      toast({ tone: "error", title: "Check failed", body: err instanceof Error ? err.message : undefined });
    } finally {
      setChecking(false);
    }
  }

  const m = data?.analysis.metrics;
  const priceOf = (ticker: string) => data?.analysis.holdings.find((h) => h.ticker === ticker)?.price ?? null;
  const unrealised = data?.analysis.holdings.reduce((a, h) => a + (h.unrealised_pnl ?? 0), 0) ?? null;

  return (
    <div className="space-y-6">
      <PageHeader
        title="Paper trading"
        description="Simulated money only. An admin approves each order, and the engine re-checks all 24 gates right before the fill."
        actions={
          pfs && pfs.length > 0 && (
            <>
              {pfs.length > 1 && (
                <Select aria-label="Paper portfolio" value={sel ?? ""} onChange={(e) => { setSel(Number(e.target.value)); setData(null); }} className="w-44">
                  {pfs.map((p) => (
                    <option key={p.id} value={p.id}>{p.name}</option>
                  ))}
                </Select>
              )}
              <Button onClick={monitor} loading={checking} icon={<RefreshCw size={15} />}>Check theses</Button>
              <Button onClick={() => setCreating(true)} icon={<Plus size={15} />}>New portfolio</Button>
            </>
          )
        }
      />

      {health && health.system_mode !== "paper" && (
        <Callout tone="warn" icon={<TriangleAlert size={16} />} title={`System mode is “${health.system_mode}”`}>
          Every order will be rejected by the execution-mode gate until the server runs with AEGIS_SYSTEM_MODE=paper.
        </Callout>
      )}

      {pfs === null && <LoadingRows rows={5} />}
      {pfs?.length === 0 && (
        <Card>
          <EmptyState
            icon={<Wallet size={20} />}
            title="Start paper trading"
            body="Create a portfolio with simulated cash. Trades still need an APPROVED decision, an admin's approval and a passing re-check."
            action={<Button variant="primary" icon={<Plus size={15} />} onClick={() => setCreating(true)}>Create paper portfolio</Button>}
          />
        </Card>
      )}

      {data && m && (
        <>
          <div className="grid grid-cols-2 gap-3 md:grid-cols-5 lg:gap-4">
            <StatCard label="Equity" value={inr(m.equity, 0)} sub={`Started with ${inr(data.starting_cash, 0)}`} />
            <StatCard label="Total return" value={signedPct(data.total_return)} tone={toneOf(data.total_return)} sub="After fees" />
            <StatCard label="Cash" value={inr(m.cash, 0)} sub={m.equity ? `${pct((m.cash ?? 0) / m.equity, 0)} of equity` : undefined} />
            <StatCard label="Unrealised P&L" value={signedInr(unrealised)} tone={toneOf(unrealised)} sub={`${data.analysis.holdings.length} open position(s)`} />
            <StatCard label="Realised P&L" value={signedInr(data.realised_pnl)} tone={toneOf(data.realised_pnl)} sub={`Fees paid ${inr(data.fees_paid, 0)}`} />
          </div>

          <div className="grid gap-6 xl:grid-cols-3">
            <Card className="xl:col-span-2" title="Equity curve" description="Marked to market after each session close.">
              {data.equity_curve.length > 1 ? (
                <EquityChart data={data.equity_curve.map((p) => ({ t: p.taken_at, equity: p.equity }))} height={240} />
              ) : (
                <EmptyState compact title="Not enough history yet" body="The curve appears after the first end-of-day marks." />
              )}
            </Card>

            <Card
              title={
                <span className="flex items-center gap-2">
                  <Hand size={15} aria-hidden /> Awaiting approval
                  {pending.length > 0 && <Badge tone="warn">{pending.length}</Badge>}
                </span>
              }
              description="Approved by the engine, not yet ordered."
            >
              {pending.length === 0 ? (
                <EmptyState
                  compact
                  icon={<CheckCircle2 size={20} />}
                  title="Nothing waiting"
                  action={<LinkButton href="/trade" size="sm" icon={<ShieldCheck size={14} />}>Propose a trade</LinkButton>}
                />
              ) : (
                <ul className="space-y-3">
                  {pending.map((p) => (
                    <li key={p.decision_id} className="rounded-lg border border-line p-3">
                      <div className="flex items-center justify-between gap-2">
                        <span className="text-sm">
                          <span className="capitalize">{p.side}</span> <span className="font-mono">{p.quantity}</span>{" "}
                          <span className="font-mono font-semibold">{p.ticker}</span>
                        </span>
                        <span className="font-mono text-xs text-muted">≤ {inr(p.entry_price)}</span>
                      </div>
                      <p className="mt-1 text-xs text-subtle">Proposal #{p.proposal_id} · {istDateTime(p.created_at)}</p>
                      {isAdmin ? (
                        <Button size="sm" variant="primary" className="mt-3 w-full" onClick={() => setConfirm(p)}>
                          Review & approve
                        </Button>
                      ) : (
                        <p className="mt-2 text-xs text-muted">Waiting for an admin to approve.</p>
                      )}
                    </li>
                  ))}
                </ul>
              )}
            </Card>
          </div>

          <div>
            <Tabs<TabKey>
              label="Paper portfolio sections"
              value={tab}
              onChange={setTab}
              tabs={[
                { value: "positions", label: "Positions", badge: <Badge>{data.analysis.holdings.length}</Badge> },
                { value: "theses", label: "Theses", badge: <Badge>{data.theses.filter((t) => t.status === "OPEN").length}</Badge> },
                { value: "fills", label: "Fills", badge: <Badge>{data.executions.length}</Badge> },
                { value: "orders", label: "Orders", badge: <Badge>{orders.length}</Badge> },
              ]}
            />

            {tab === "positions" && (
              <Card bodyClassName="pb-2">
                {data.analysis.holdings.length === 0 ? (
                  <EmptyState compact icon={<Wallet size={20} />} title="No open positions" />
                ) : (
                  <>
                  <MobileList className="mb-2">
                    {data.analysis.holdings.map((x) => (
                      <MobileItem key={x.ticker} href={`/stocks/${encodeURIComponent(x.ticker)}`}>
                        <div className="flex items-center justify-between gap-3">
                          <div className="min-w-0">
                            <p className="font-mono text-[13px] font-semibold">{x.ticker}</p>
                            <p className="text-xs text-muted">{x.quantity} × {inr(x.avg_cost)} · {pct(x.weight)} of equity</p>
                          </div>
                          <div className="text-right">
                            <p className="font-mono text-[13px]">{x.price === null ? "unknown" : inr(x.price)}</p>
                            <p className={cx("font-mono text-xs", toneOf(x.unrealised_pnl))}>{signedInr(x.unrealised_pnl)}</p>
                          </div>
                        </div>
                      </MobileItem>
                    ))}
                  </MobileList>
                  <DesktopOnly><Table>
                    <thead>
                      <tr>
                        <Th>Stock</Th>
                        <Th align="right">Qty</Th>
                        <Th align="right">Avg cost</Th>
                        <Th align="right">Price</Th>
                        <Th align="right" className="hidden sm:table-cell">Value</Th>
                        <Th align="right" className="hidden md:table-cell">Weight</Th>
                        <Th align="right">Unrealised</Th>
                      </tr>
                    </thead>
                    <tbody>
                      {data.analysis.holdings.map((x) => (
                        <tr key={x.ticker} className="hover:bg-hover">
                          <Td>
                            <Link href={`/stocks/${encodeURIComponent(x.ticker)}`} className="font-mono text-[13px] font-semibold hover:underline">{x.ticker}</Link>
                            <span className="block text-xs capitalize text-muted">{humanize(x.sector).toLowerCase()}</span>
                          </Td>
                          <Td align="right" mono>{x.quantity}</Td>
                          <Td align="right" mono>{inr(x.avg_cost)}</Td>
                          <Td align="right" mono>{x.price === null ? <span className="text-warn">unknown</span> : inr(x.price)}</Td>
                          <Td align="right" mono className="hidden sm:table-cell">{inr(x.value, 0)}</Td>
                          <Td align="right" mono className="hidden md:table-cell">{pct(x.weight)}</Td>
                          <Td align="right" mono className={toneOf(x.unrealised_pnl)}>{signedInr(x.unrealised_pnl)}</Td>
                        </tr>
                      ))}
                    </tbody>
                  </Table></DesktopOnly>
                  </>
                )}
              </Card>
            )}

            {tab === "theses" && (
              data.theses.length === 0 ? (
                <Card><EmptyState compact icon={<ScrollText size={20} />} title="No theses yet" body="Each filled entry opens a thesis with its stop, target and horizon." /></Card>
              ) : (
                <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
                  {data.theses.map((t) => (
                    <ThesisCard key={t.id} t={t} price={priceOf(t.ticker)} />
                  ))}
                </div>
              )
            )}

            {tab === "fills" && (
              <Card bodyClassName="pb-2">
                {data.executions.length === 0 ? (
                  <EmptyState compact title="No fills yet" />
                ) : (
                  <>
                  <MobileList className="mb-2">
                    {data.executions.map((x) => (
                      <MobileItem key={x.id}>
                        <div className="flex items-start justify-between gap-3">
                          <div className="min-w-0">
                            <p className="text-sm">
                              <span className={cx("font-medium capitalize", x.side === "buy" ? "text-pass" : "text-fail")}>{x.side}</span>{" "}
                              <span className="font-mono">{x.quantity}</span> <span className="font-mono font-semibold">{x.ticker}</span>
                            </p>
                            <p className="text-xs text-subtle">{istDateTime(x.executed_at)} · fees {inr(x.fees)}</p>
                          </div>
                          <div className="text-right">
                            <p className="font-mono text-[13px]">{inr(x.fill_price)}</p>
                            {x.realised_pnl !== null && <p className={cx("font-mono text-xs", toneOf(x.realised_pnl))}>{signedInr(x.realised_pnl)}</p>}
                          </div>
                        </div>
                      </MobileItem>
                    ))}
                  </MobileList>
                  <DesktopOnly><Table>
                    <thead>
                      <tr>
                        <Th>When</Th>
                        <Th>Trade</Th>
                        <Th align="right">Fill</Th>
                        <Th align="right" className="hidden md:table-cell">Reference</Th>
                        <Th align="right" className="hidden sm:table-cell">Fees</Th>
                        <Th align="right">Realised</Th>
                      </tr>
                    </thead>
                    <tbody>
                      {data.executions.map((x) => (
                        <tr key={x.id}>
                          <Td className="text-muted">{istDateTime(x.executed_at)}</Td>
                          <Td>
                            <span className={cx("font-medium capitalize", x.side === "buy" ? "text-pass" : "text-fail")}>{x.side}</span>{" "}
                            <span className="font-mono">{x.quantity}</span> <span className="font-mono font-semibold">{x.ticker}</span>
                          </Td>
                          <Td align="right" mono>{inr(x.fill_price)}</Td>
                          <Td align="right" mono className="hidden text-muted md:table-cell">{inr(x.reference_price)}</Td>
                          <Td align="right" mono className="hidden sm:table-cell">{inr(x.fees)}</Td>
                          <Td align="right" mono className={toneOf(x.realised_pnl)}>{x.realised_pnl === null ? "—" : signedInr(x.realised_pnl)}</Td>
                        </tr>
                      ))}
                    </tbody>
                  </Table></DesktopOnly>
                  </>
                )}
              </Card>
            )}

            {tab === "orders" && (
              <Card bodyClassName="pb-2">
                {orders.length === 0 ? (
                  <EmptyState compact title="No orders yet" />
                ) : (
                  <>
                  <MobileList className="mb-2">
                    {orders.map((o) => (
                      <MobileItem key={o.id}>
                        <div className="flex items-start justify-between gap-3">
                          <p className="text-sm">
                            <span className="capitalize">{o.side}</span> <span className="font-mono">{o.quantity}</span>{" "}
                            <span className="font-mono font-semibold">{o.ticker}</span> <span className="text-muted">≤ {inr(o.limit_price)}</span>
                          </p>
                          {o.status === "FILLED" ? (
                            <Badge tone="pass" icon={<CheckCircle2 size={12} aria-hidden />}>Filled</Badge>
                          ) : (
                            <Badge tone="fail" icon={<XCircle size={12} aria-hidden />}>Rejected</Badge>
                          )}
                        </div>
                        <p className="mt-1 text-xs text-muted">#{o.id} · {o.reason}</p>
                      </MobileItem>
                    ))}
                  </MobileList>
                  <DesktopOnly><Table>
                    <thead>
                      <tr>
                        <Th>#</Th>
                        <Th>Trade</Th>
                        <Th align="right">Limit</Th>
                        <Th>Status</Th>
                        <Th className="hidden md:table-cell">Detail</Th>
                      </tr>
                    </thead>
                    <tbody>
                      {orders.map((o) => (
                        <tr key={o.id} className="align-top">
                          <Td mono className="text-subtle">{o.id}</Td>
                          <Td>
                            <span className="capitalize">{o.side}</span> <span className="font-mono">{o.quantity}</span>{" "}
                            <span className="font-mono font-semibold">{o.ticker}</span>
                            <span className="block text-xs text-muted md:hidden">{o.reason}</span>
                          </Td>
                          <Td align="right" mono>{inr(o.limit_price)}</Td>
                          <Td>
                            {o.status === "FILLED" ? (
                              <Badge tone="pass" icon={<CheckCircle2 size={12} aria-hidden />}>Filled</Badge>
                            ) : (
                              <Badge tone="fail" icon={<XCircle size={12} aria-hidden />}>Rejected</Badge>
                            )}
                          </Td>
                          <Td className="hidden text-muted md:table-cell">{o.reason}</Td>
                        </tr>
                      ))}
                    </tbody>
                  </Table></DesktopOnly>
                  </>
                )}
              </Card>
            )}
          </div>
        </>
      )}

      <ConfirmDialog
        open={confirm !== null}
        onClose={() => !placing && setConfirm(null)}
        onConfirm={approve}
        busy={placing}
        title="Approve this paper order?"
        body="The engine re-runs all 24 gates on fresh data first. If any gate fails, nothing is filled."
        confirmLabel="Approve & place order"
      >
        {confirm && (
          <div className="rounded-lg bg-sunken p-4 text-sm">
            <div className="flex justify-between">
              <span className="text-muted">Trade</span>
              <span>
                <span className="capitalize">{confirm.side}</span> <span className="font-mono">{confirm.quantity}</span>{" "}
                <span className="font-mono font-semibold">{confirm.ticker}</span>
              </span>
            </div>
            <div className="mt-1.5 flex justify-between">
              <span className="text-muted">Limit price</span>
              <span className="font-mono">{inr(confirm.entry_price)}</span>
            </div>
            <div className="mt-1.5 flex justify-between">
              <span className="text-muted">Approx. value</span>
              <span className="font-mono">{inr(Number(confirm.entry_price) * confirm.quantity, 0)}</span>
            </div>
          </div>
        )}
      </ConfirmDialog>

      <Dialog
        open={creating}
        onClose={() => setCreating(false)}
        title="New paper portfolio"
        description="Simulated money only."
        footer={
          <>
            <Button onClick={() => setCreating(false)}>Cancel</Button>
            <Button variant="primary" type="submit" form="new-paper" loading={busyCreate}>Create portfolio</Button>
          </>
        }
      >
        <form id="new-paper" onSubmit={createPaper} className="space-y-4">
          <Field label="Name">{(id) => <Input id={id} value={newName} onChange={(e) => setNewName(e.target.value)} minLength={2} maxLength={80} required />}</Field>
          <Field label="Starting cash (₹)" hint={Number(newCash) > 0 ? inr(newCash, 0) : undefined}>
            {(id) => <Input id={id} value={newCash} onChange={(e) => setNewCash(e.target.value)} inputMode="decimal" pattern="[0-9]+(\.[0-9]{1,2})?" className="font-mono" required />}
          </Field>
        </form>
      </Dialog>
    </div>
  );
}
