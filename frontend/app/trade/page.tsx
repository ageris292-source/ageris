"use client";

import {
  ArrowRight,
  Calculator,
  CheckCircle2,
  ChevronDown,
  CircleHelp,
  FileSearch,
  Hand,
  ListChecks,
  ShieldCheck,
  XCircle,
} from "lucide-react";
import Link from "next/link";
import { useCallback, useEffect, useMemo, useState } from "react";
import { usePageTitle } from "@/components/usePageTitle";
import { useSession } from "@/components/providers/SessionProvider";
import { useToast } from "@/components/providers/ToastProvider";
import { GateBadge } from "@/components/ui/Status";
import {
  Badge,
  Button,
  Callout,
  Card,
  EmptyState,
  Field,
  Input,
  LinkButton,
  PageHeader,
  Segmented,
  Select,
  Table,
  Td,
  Th,
  cx,
} from "@/components/ui/core";
import {
  api,
  ApiError,
  type CostResult,
  type GateCatalog,
  type PortfolioSummary,
  type ProposalRow,
  type StockSummary,
  type TradeDecision,
} from "@/lib/api";
import { humanize, inr, istDateTime, num } from "@/lib/format";

function fmtGate(v: number | string | null): string {
  if (v === null) return "—";
  if (typeof v === "string") return v;
  if (Math.abs(v) >= 1e5) return v.toLocaleString("en-IN", { maximumFractionDigits: 0 });
  if (Math.abs(v) < 1 && v !== 0) return v.toFixed(4);
  return v.toLocaleString("en-IN", { maximumFractionDigits: 2 });
}

const STEPS = [
  { icon: FileSearch, title: "Propose", body: "Describe the trade: size, limit price, stop and target." },
  { icon: ListChecks, title: "The engine decides", body: "24 deterministic gates. Any FAIL or UNKNOWN rejects it." },
  { icon: Hand, title: "A human approves", body: "Approved proposals wait on Paper trading for an admin." },
  { icon: ShieldCheck, title: "Re-check, then fill", body: "Every gate runs again on fresh data right before the simulated fill." },
];

function Decision({ d }: { d: TradeDecision }) {
  const [onlyProblems, setOnlyProblems] = useState(d.decision === "REJECTED");
  const counts = d.gates.reduce<Record<string, number>>((m, g) => ({ ...m, [g.status]: (m[g.status] ?? 0) + 1 }), {});
  const total = d.gates.length;
  const shown = onlyProblems ? d.gates.filter((g) => g.status === "FAIL" || g.status === "UNKNOWN") : d.gates;
  const ok = d.decision === "APPROVED";
  return (
    <Card id="decision" className={cx("border-2", ok ? "border-pass/40" : "border-fail/30")}>
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div className="flex items-center gap-3">
          <span className={cx("flex h-11 w-11 items-center justify-center rounded-full", ok ? "bg-pass-soft text-pass" : "bg-fail-soft text-fail")}>
            {ok ? <CheckCircle2 size={22} aria-hidden /> : <XCircle size={22} aria-hidden />}
          </span>
          <div>
            <div className={cx("text-xl font-semibold", ok ? "text-pass" : "text-fail")}>{d.decision}</div>
            <div className="text-sm text-muted">
              Proposal #{d.proposal_id} · {istDateTime(d.evaluated_at)}
            </div>
          </div>
        </div>
        {ok ? (
          <LinkButton href="/paper" variant="primary" icon={<Hand size={15} />}>
            Review on Paper trading <ArrowRight size={14} />
          </LinkButton>
        ) : (
          d.first_failure && (
            <div className="text-sm">
              First failed gate: <span className="font-mono font-medium">{d.first_failure}</span>
            </div>
          )
        )}
      </div>

      <div className="mt-5">
        <div className="flex h-2 overflow-hidden rounded-full bg-sunken" role="img" aria-label={`${counts.PASS ?? 0} of ${total} gates passed`}>
          <div className="bg-pass" style={{ width: `${((counts.PASS ?? 0) / total) * 100}%` }} />
          <div className="bg-fail" style={{ width: `${((counts.FAIL ?? 0) / total) * 100}%` }} />
          <div className="bg-warn" style={{ width: `${((counts.UNKNOWN ?? 0) / total) * 100}%` }} />
        </div>
        <div className="mt-2 flex flex-wrap gap-x-4 gap-y-1 text-xs text-muted">
          <span><b className="text-pass">{counts.PASS ?? 0}</b> passed</span>
          <span><b className="text-fail">{counts.FAIL ?? 0}</b> failed</span>
          <span><b className="text-warn">{counts.UNKNOWN ?? 0}</b> unknown</span>
          <span>{counts.NOT_APPLICABLE ?? 0} not applicable</span>
          {d.costs && <span>· round-trip costs <b className="text-ink">{(d.costs.round_trip_fraction * 100).toFixed(2)}%</b></span>}
        </div>
      </div>

      {ok && (
        <Callout tone="info" className="mt-4" title="Approved is not an order">
          An admin must still approve it on Paper trading, and all 24 gates run again on fresh data right before the simulated fill.
        </Callout>
      )}

      <div className="mt-5 flex items-center justify-between">
        <h3 className="text-sm font-semibold">Gates</h3>
        <Segmented<"problems" | "all">
          label="Gates shown"
          value={onlyProblems ? "problems" : "all"}
          onChange={(v) => setOnlyProblems(v === "problems")}
          options={[
            { value: "problems", label: "Problems" },
            { value: "all", label: `All ${total}` },
          ]}
        />
      </div>
      <Table className="mt-2">
        <thead>
          <tr>
            <Th>#</Th>
            <Th>Gate</Th>
            <Th>Result</Th>
            <Th align="right" className="hidden sm:table-cell">Value</Th>
            <Th align="right" className="hidden sm:table-cell">Threshold</Th>
            <Th className="hidden md:table-cell">Why</Th>
          </tr>
        </thead>
        <tbody>
          {shown.map((g) => (
            <tr key={g.order} className="align-top">
              <Td mono className="text-subtle">{g.order}</Td>
              <Td>
                <span className="font-mono text-[13px]">{g.name}</span>
                <span className="block text-xs text-muted md:hidden">{g.reason}</span>
              </Td>
              <Td><GateBadge s={g.status} /></Td>
              <Td align="right" mono className="hidden sm:table-cell">{fmtGate(g.value)}</Td>
              <Td align="right" mono className="hidden text-muted sm:table-cell">{fmtGate(g.threshold)}</Td>
              <Td className="hidden text-muted md:table-cell">{g.reason}</Td>
            </tr>
          ))}
          {shown.length === 0 && (
            <tr>
              <Td colSpan={6} className="text-muted">No failing or unknown gates.</Td>
            </tr>
          )}
        </tbody>
      </Table>
      <p className="mt-3 font-mono text-[11px] text-subtle">
        {d.engine_version} · hash {d.decision_hash.slice(0, 16)}
      </p>
    </Card>
  );
}

export default function TradePage() {
  usePageTitle("New trade");
  const { guard, health } = useSession();
  const toast = useToast();
  const [catalog, setCatalog] = useState<GateCatalog | null>(null);
  const [portfolios, setPortfolios] = useState<PortfolioSummary[] | null>(null);
  const [stocks, setStocks] = useState<StockSummary[]>([]);
  const [rows, setRows] = useState<ProposalRow[]>([]);
  const [result, setResult] = useState<TradeDecision | null>(null);
  const [costs, setCosts] = useState<CostResult | null>(null);
  const [busy, setBusy] = useState(false);
  const [costBusy, setCostBusy] = useState(false);
  const [f, setF] = useState({
    portfolio_id: "",
    ticker: "",
    side: "buy" as "buy" | "sell",
    quantity: "",
    entry_price: "",
    stop_loss: "",
    target: "",
    horizon_days: "20",
    quoted_spread_bps: "",
    rationale: "",
  });

  useEffect(() => {
    const p = new URLSearchParams(window.location.search);
    setF((x) => ({
      ...x,
      ticker: p.get("ticker") ?? x.ticker,
      entry_price: p.get("entry") ?? x.entry_price,
      stop_loss: p.get("stop") ?? x.stop_loss,
      target: p.get("target") ?? x.target,
      quantity: p.get("qty") ?? x.quantity,
      side: p.get("side") === "sell" ? "sell" : x.side,
    }));
  }, []);

  const load = useCallback(async () => {
    try {
      const [c, p, r, s] = await Promise.all([
        guard((t) => api.tradeGates(t)),
        guard((t) => api.portfolios(t)),
        guard((t) => api.proposals(t)),
        guard((t) => api.stocks(t)),
      ]);
      if (c) setCatalog(c);
      if (p) {
        setPortfolios(p);
        const preferred = p.find((x) => x.kind === "paper") ?? p[0];
        setF((x) => (x.portfolio_id || !preferred ? x : { ...x, portfolio_id: String(preferred.id) }));
      }
      if (r) setRows(r);
      if (s) setStocks(s);
    } catch (err) {
      toast({ tone: "error", title: "Could not load the page", body: err instanceof Error ? err.message : undefined });
    }
  }, [guard, toast]);

  useEffect(() => {
    void load();
  }, [load]);

  const set = (k: keyof typeof f) => (e: React.ChangeEvent<HTMLInputElement | HTMLSelectElement | HTMLTextAreaElement>) => {
    setF({ ...f, [k]: e.target.value });
    setCosts(null);
  };

  const preview = useMemo(() => {
    const q = Number(f.quantity);
    const e = Number(f.entry_price);
    const s = Number(f.stop_loss);
    const t = Number(f.target);
    if (!(q > 0) || !(e > 0)) return null;
    const value = q * e;
    const risk = s > 0 ? Math.abs(e - s) * q : null;
    const reward = t > 0 ? Math.abs(t - e) * q : null;
    const rr = risk && reward ? reward / risk : null;
    const badStop = f.side === "buy" && s > 0 && s >= e;
    const badTarget = f.side === "buy" && t > 0 && t <= e;
    return { value, risk, reward, rr, badStop, badTarget };
  }, [f]);

  const selectedPf = portfolios?.find((p) => String(p.id) === f.portfolio_id);
  const canSubmit = !!(f.ticker.trim() && Number(f.quantity) > 0 && Number(f.entry_price) > 0 && f.portfolio_id);

  async function estimate() {
    setCostBusy(true);
    try {
      const r = await guard((t) =>
        api.tradeCosts(t, {
          ticker: f.ticker.trim().toUpperCase(),
          quantity: Number(f.quantity),
          entry_price: f.entry_price,
          horizon_days: Number(f.horizon_days),
          quoted_spread_bps: f.quoted_spread_bps === "" ? null : Number(f.quoted_spread_bps),
        }),
      );
      if (r) setCosts(r);
    } catch (err) {
      toast({ tone: "error", title: "Could not estimate costs", body: err instanceof ApiError ? err.message : undefined });
    } finally {
      setCostBusy(false);
    }
  }

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    try {
      const d = await guard((t) =>
        api.submitProposal(t, {
          ticker: f.ticker.trim().toUpperCase(),
          side: f.side,
          quantity: Number(f.quantity),
          entry_price: f.entry_price,
          stop_loss: f.stop_loss || null,
          target: f.target || null,
          horizon_days: Number(f.horizon_days),
          portfolio_id: Number(f.portfolio_id),
          mode: "paper",
          quoted_spread_bps: f.quoted_spread_bps === "" ? null : Number(f.quoted_spread_bps),
          rationale: f.rationale.trim() || undefined,
        }),
      );
      if (d) {
        setResult(d);
        toast({
          tone: d.decision === "APPROVED" ? "success" : "warning",
          title: `Proposal ${d.decision.toLowerCase()}`,
          body: d.decision === "APPROVED" ? "It now waits for human approval on Paper trading." : `First failed gate: ${d.first_failure}`,
        });
        setTimeout(() => document.getElementById("decision")?.scrollIntoView({ behavior: "smooth", block: "start" }), 50);
      }
      await load();
    } catch (err) {
      toast({ tone: "error", title: "Evaluation failed", body: err instanceof ApiError ? err.message : undefined });
    } finally {
      setBusy(false);
    }
  }

  async function open(id: number) {
    try {
      const d = await guard((t) => api.decision(t, id));
      if (d) {
        setResult(d);
        setTimeout(() => document.getElementById("decision")?.scrollIntoView({ behavior: "smooth", block: "start" }), 50);
      }
    } catch (err) {
      toast({ tone: "error", title: "Could not open the decision", body: err instanceof Error ? err.message : undefined });
    }
  }

  return (
    <div className="space-y-6">
      <PageHeader
        title="New trade"
        description="Propose a paper trade and let the deterministic Trade Risk Engine decide. No agent, person or language model can override a gate."
      />

      {health && health.system_mode !== "paper" && (
        <Callout tone="warn" icon={<CircleHelp size={16} />} title={`System mode is “${health.system_mode}”`}>
          Every proposal will fail the execution-mode gate until the server runs with AEGIS_SYSTEM_MODE=paper. You can still evaluate to see the other gates.
        </Callout>
      )}

      <div className="grid gap-6 xl:grid-cols-3">
        <Card className="xl:col-span-2" title="Trade proposal" description="Paper mode only. Prices in rupees.">
          {portfolios?.length === 0 ? (
            <EmptyState
              title="You need a portfolio first"
              body="Create a paper portfolio to hold simulated positions."
              action={<LinkButton href="/paper" variant="primary">Create a paper portfolio</LinkButton>}
            />
          ) : (
            <form onSubmit={submit} className="space-y-5">
              <div className="grid gap-4 sm:grid-cols-2">
                <Field label="Portfolio" hint={selectedPf ? `Cash ${inr(selectedPf.cash, 0)} · ${selectedPf.kind}` : undefined}>
                  {(id) => (
                    <Select id={id} value={f.portfolio_id} onChange={set("portfolio_id")}>
                      {(portfolios ?? []).map((p) => (
                        <option key={p.id} value={p.id}>
                          {p.name} ({p.kind})
                        </option>
                      ))}
                    </Select>
                  )}
                </Field>
                <div className="flex flex-col gap-1.5">
                  <span className="text-xs font-medium text-muted">Side</span>
                  <Segmented<"buy" | "sell">
                    label="Side"
                    size="md"
                    value={f.side}
                    onChange={(v) => setF({ ...f, side: v })}
                    options={[
                      { value: "buy", label: "Buy · entry" },
                      { value: "sell", label: "Sell · exit" },
                    ]}
                  />
                </div>
              </div>

              <div className="grid gap-4 sm:grid-cols-3">
                <Field label="Ticker">
                  {(id) => (
                    <>
                      <Input id={id} list="trade-stocks" placeholder="TCS.NS" value={f.ticker} onChange={set("ticker")} className="font-mono uppercase" autoComplete="off" required />
                      <datalist id="trade-stocks">
                        {stocks.map((s) => (
                          <option key={s.ticker} value={s.ticker}>{s.name ?? ""}</option>
                        ))}
                      </datalist>
                    </>
                  )}
                </Field>
                <Field label="Quantity (shares)">
                  {(id) => <Input id={id} inputMode="numeric" value={f.quantity} onChange={set("quantity")} className="font-mono" required />}
                </Field>
                <Field label="Limit price (₹)">
                  {(id) => <Input id={id} inputMode="decimal" value={f.entry_price} onChange={set("entry_price")} className="font-mono" required />}
                </Field>
                <Field label="Stop-loss (₹)" error={preview?.badStop ? "For a buy, the stop must be below the entry." : undefined}>
                  {(id) => <Input id={id} inputMode="decimal" value={f.stop_loss} onChange={set("stop_loss")} className="font-mono" />}
                </Field>
                <Field label="Target (₹)" error={preview?.badTarget ? "For a buy, the target must be above the entry." : undefined}>
                  {(id) => <Input id={id} inputMode="decimal" value={f.target} onChange={set("target")} className="font-mono" />}
                </Field>
                <Field label="Holding period (trading days)">
                  {(id) => <Input id={id} inputMode="numeric" value={f.horizon_days} onChange={set("horizon_days")} className="font-mono" />}
                </Field>
              </div>

              <details className="group rounded-lg border border-line">
                <summary className="flex cursor-pointer list-none items-center justify-between px-4 py-3 text-sm font-medium">
                  More options
                  <ChevronDown size={16} className="text-subtle transition-transform group-open:rotate-180" aria-hidden />
                </summary>
                <div className="grid gap-4 border-t border-line px-4 py-4 sm:grid-cols-2">
                  <Field label="Quoted spread (bps)" hint="From a live quote. Without it the spread gate is UNKNOWN.">
                    {(id) => <Input id={id} inputMode="decimal" value={f.quoted_spread_bps} onChange={set("quoted_spread_bps")} className="font-mono" />}
                  </Field>
                  <Field label="Rationale (optional)" hint="Stored with the proposal for the audit trail.">
                    {(id) => <Input id={id} value={f.rationale} onChange={set("rationale")} maxLength={500} />}
                  </Field>
                </div>
              </details>

              {preview && (
                <div className="grid grid-cols-2 gap-3 rounded-lg bg-sunken p-4 sm:grid-cols-4">
                  {[
                    ["Order value", inr(preview.value, 0)],
                    ["Risk to stop", preview.risk === null ? "—" : inr(preview.risk, 0)],
                    ["Reward to target", preview.reward === null ? "—" : inr(preview.reward, 0)],
                    ["Reward : risk", preview.rr === null ? "—" : `${num(preview.rr, 2)} : 1`],
                  ].map(([k, v]) => (
                    <div key={k}>
                      <div className="text-xs text-muted">{k}</div>
                      <div className="mt-0.5 font-mono text-sm font-medium">{v}</div>
                    </div>
                  ))}
                  <p className="col-span-full text-[11px] text-subtle">Arithmetic on your inputs, before costs. The engine applies its own sizing and cost model.</p>
                </div>
              )}

              {costs && (
                <div className="rounded-lg border border-line p-4">
                  <div className="flex flex-wrap items-baseline justify-between gap-2">
                    <span className="text-sm font-medium">Estimated round-trip cost</span>
                    <span className="font-mono text-sm">
                      {(costs.round_trip_fraction * 100).toFixed(3)}% · {inr(costs.round_trip_fraction * costs.order_value)}
                    </span>
                  </div>
                  <div className="mt-3 grid gap-x-6 gap-y-1 text-xs sm:grid-cols-2">
                    {Object.entries(costs.items_bps).map(([k, v]) => (
                      <div key={k} className="flex justify-between">
                        <span className="text-muted">{humanize(k)}</span>
                        <span className="font-mono">{v.toFixed(2)} bps</span>
                      </div>
                    ))}
                  </div>
                  <p className="mt-2 text-[11px] text-subtle">Schedule “{costs.schedule}”. {costs.notice}</p>
                </div>
              )}

              <div className="flex flex-wrap justify-end gap-2 border-t border-line pt-5">
                <Button type="button" onClick={estimate} loading={costBusy} disabled={!canSubmit} icon={<Calculator size={15} />}>
                  Estimate costs
                </Button>
                <Button type="submit" variant="primary" loading={busy} disabled={!canSubmit} icon={<ShieldCheck size={15} />}>
                  {busy ? "Evaluating…" : "Evaluate with risk engine"}
                </Button>
              </div>
            </form>
          )}
        </Card>

        <Card title="How a trade happens">
          <ol className="space-y-5">
            {STEPS.map((s, i) => (
              <li key={s.title} className="flex gap-3">
                <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-accent-soft text-accent">
                  <s.icon size={16} aria-hidden />
                </span>
                <div>
                  <p className="text-sm font-medium">
                    {i + 1}. {s.title}
                  </p>
                  <p className="text-xs text-muted">{s.body}</p>
                </div>
              </li>
            ))}
          </ol>
          {catalog && (
            <p className={cx("mt-5 flex items-center gap-1.5 border-t border-line pt-4 text-xs", catalog.self_test.passed ? "text-pass" : "text-fail")}>
              {catalog.self_test.passed ? <CheckCircle2 size={14} aria-hidden /> : <XCircle size={14} aria-hidden />}
              Engine self-test: {catalog.self_test.detail}
            </p>
          )}
        </Card>
      </div>

      {result && <Decision key={result.decision_id} d={result} />}

      <div className="grid items-start gap-6 xl:grid-cols-3">
        <Card className="xl:col-span-2" title="Recent proposals" description="Select one to see its full gate decision." bodyClassName="pb-2">
          {rows.length === 0 ? (
            <EmptyState compact icon={<FileSearch size={20} />} title="No proposals yet" />
          ) : (
            <Table>
              <thead>
                <tr>
                  <Th>#</Th>
                  <Th>Trade</Th>
                  <Th align="right" className="hidden sm:table-cell">Limit</Th>
                  <Th>Decision</Th>
                  <Th className="hidden md:table-cell">When</Th>
                </tr>
              </thead>
              <tbody>
                {rows.map((r) => (
                  <tr key={r.proposal_id} className="cursor-pointer hover:bg-hover" onClick={() => open(r.decision_id)}>
                    <Td mono className="text-subtle">{r.proposal_id}</Td>
                    <Td>
                      <button className="text-left" onClick={(e) => { e.stopPropagation(); void open(r.decision_id); }}>
                        <span className="capitalize">{r.side}</span> <span className="font-mono">{r.quantity}</span>{" "}
                        <span className="font-mono font-semibold">{r.ticker}</span>
                      </button>
                    </Td>
                    <Td align="right" mono className="hidden sm:table-cell">{inr(r.entry_price)}</Td>
                    <Td>
                      {r.decision === "APPROVED" ? (
                        <Badge tone="pass" icon={<CheckCircle2 size={12} aria-hidden />}>Approved</Badge>
                      ) : (
                        <Badge tone="fail" icon={<XCircle size={12} aria-hidden />} title={r.first_failure ?? undefined}>
                          Rejected{r.first_failure ? ` · ${r.first_failure}` : ""}
                        </Badge>
                      )}
                    </Td>
                    <Td className="hidden text-muted md:table-cell">{istDateTime(r.created_at)}</Td>
                  </tr>
                ))}
              </tbody>
            </Table>
          )}
        </Card>

        <Card title={`The ${catalog?.gates.length ?? 24} gates`} description={catalog?.rule}>
          {catalog && (
            <ol className="max-h-[520px] space-y-2.5 overflow-y-auto pr-1 text-sm">
              {catalog.gates.map((g) => (
                <li key={g.name} className="flex gap-2.5">
                  <span className="w-5 shrink-0 text-right font-mono text-xs text-subtle">{g.order}</span>
                  <span className="min-w-0">
                    <span className="font-mono text-[13px]">{g.name}</span>
                    {!g.applies_to_exits && <span className="ml-1.5 text-[11px] text-subtle">entries only</span>}
                    <span className="block text-xs text-muted">{g.description}</span>
                  </span>
                </li>
              ))}
            </ol>
          )}
          <p className="mt-4 text-xs text-muted">
            See <Link href="/system" className="text-accent hover:underline">System</Link> for live readiness and the kill switch.
          </p>
        </Card>
      </div>
    </div>
  );
}
