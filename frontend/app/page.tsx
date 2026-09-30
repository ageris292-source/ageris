"use client";

import {
  ArrowRight,
  Bell,
  CheckCircle2,
  CircleHelp,
  Gauge,
  Plus,
  Search,
  ShieldCheck,
  Star,
  Trophy,
  Wallet,
  XCircle,
} from "lucide-react";
import Link from "next/link";
import { useCallback, useEffect, useMemo, useState } from "react";
import { EquityChart } from "@/components/charts";
import { usePageTitle } from "@/components/usePageTitle";
import { useWatchlist, WatchStar } from "@/components/Watchlist";
import { useSession } from "@/components/providers/SessionProvider";
import { useToast } from "@/components/providers/ToastProvider";
import { Sparkline } from "@/components/ui/Sparkline";
import { FreshnessBadge, StanceBadge } from "@/components/ui/Status";
import {
  Badge,
  Button,
  Card,
  EmptyState,
  Input,
  LinkButton,
  LoadingRows,
  Skeleton,
  StatCard,
  Table,
  Td,
  Th,
  cx,
} from "@/components/ui/core";
import {
  api,
  type AlertOut,
  type PaperPortfolioOut,
  type PortfolioSummary,
  type RankingRun,
  type Regime,
  type RiskStatus,
  type StockSummary,
} from "@/lib/api";
import { ago, inr, pct, signedPct, toneOf, humanize } from "@/lib/format";

function greeting() {
  const h = Number(new Date().toLocaleString("en-IN", { hour: "numeric", hour12: false, timeZone: "Asia/Kolkata" }));
  return h < 12 ? "Good morning" : h < 17 ? "Good afternoon" : "Good evening";
}

function WatchlistCard({ stocks }: { stocks: StockSummary[] | null }) {
  const { rows, error, toggle, has } = useWatchlist();
  const toast = useToast();
  const [adding, setAdding] = useState("");
  const candidates = useMemo(() => (stocks ?? []).filter((s) => !has(s.ticker)), [stocks, has]);

  async function add(e: React.FormEvent) {
    e.preventDefault();
    const t = adding.trim().toUpperCase();
    if (!t) return;
    if (!stocks?.some((s) => s.ticker === t)) {
      toast({ tone: "warning", title: `${t} isn't in the universe yet`, body: "Pick a stock from the list, or ask an admin to add it on the Stocks page." });
      return;
    }
    await toggle(t);
    setAdding("");
  }

  return (
    <Card
      title={
        <span className="flex items-center gap-2">
          <Star size={15} className="text-[#c98500]" fill="currentColor" aria-hidden /> Your watchlist
        </span>
      }
      description="Last close, day change and 30-session trend. Stance comes from the latest research report."
      actions={
        <form onSubmit={add} className="flex gap-2">
          <Input
            list="watch-candidates"
            value={adding}
            onChange={(e) => setAdding(e.target.value)}
            placeholder="Add ticker…"
            aria-label="Add a stock to your watchlist"
            className="h-8 w-36 font-mono text-xs uppercase"
          />
          <datalist id="watch-candidates">
            {candidates.map((s) => (
              <option key={s.ticker} value={s.ticker}>
                {s.name ?? ""}
              </option>
            ))}
          </datalist>
          <Button size="sm" type="submit" icon={<Plus size={14} />} disabled={!adding.trim()}>
            Add
          </Button>
        </form>
      }
      bodyClassName="pb-2"
    >
      {error && <p className="text-sm text-fail">{error}</p>}
      {rows === null && !error && <LoadingRows rows={4} />}
      {rows?.length === 0 && (
        <EmptyState
          icon={<Star size={20} />}
          title="Nothing on your watchlist yet"
          body="Star stocks on the Stocks page or add a ticker above to track them here."
          action={<LinkButton href="/stocks" size="sm" icon={<Search size={14} />}>Browse stocks</LinkButton>}
          compact
        />
      )}
      {rows && rows.length > 0 && (
        <Table>
          <thead>
            <tr>
              <Th>Stock</Th>
              <Th className="hidden sm:table-cell">Trend</Th>
              <Th align="right">Last</Th>
              <Th align="right">Day</Th>
              <Th className="hidden md:table-cell">Research stance</Th>
              <Th className="hidden 2xl:table-cell">Data</Th>
              <Th />
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => (
              <tr key={r.ticker} className="group hover:bg-hover">
                <Td>
                  <Link href={`/stocks/${encodeURIComponent(r.ticker)}`} className="block">
                    <span className="font-mono text-[13px] font-semibold">{r.ticker}</span>
                    <span className="block max-w-[110px] truncate text-xs text-muted sm:max-w-[180px]">{r.name ?? r.exchange}</span>
                  </Link>
                </Td>
                <Td className="hidden sm:table-cell">
                  <Sparkline values={r.sparkline} width={84} />
                </Td>
                <Td align="right" mono>
                  {inr(r.last_close)}
                </Td>
                <Td align="right" mono className={toneOf(r.change_pct)}>
                  {signedPct(r.change_pct)}
                </Td>
                <Td className="hidden md:table-cell" title={r.report_at ? `Report ${ago(r.report_at)}` : undefined}>
                  <StanceBadge stance={r.stance} />
                </Td>
                <Td className="hidden 2xl:table-cell">
                  <FreshnessBadge f={r.freshness} />
                </Td>
                <Td align="right">
                  <WatchStar on ticker={r.ticker} onToggle={() => toggle(r.ticker)} />
                </Td>
              </tr>
            ))}
          </tbody>
        </Table>
      )}
    </Card>
  );
}

function ReadinessCard({ risk }: { risk: RiskStatus | null }) {
  if (!risk) {
    return (
      <Card title="Execution readiness">
        <LoadingRows rows={3} />
      </Card>
    );
  }
  const failing = risk.checks.filter((c) => c.status !== "PASS");
  return (
    <Card
      title="Execution readiness"
      description="Whether the system would accept an order right now."
      actions={<LinkButton href="/system" size="sm" variant="ghost">Details <ArrowRight size={14} /></LinkButton>}
    >
      <div className="grid grid-cols-2 gap-3">
        {[
          ["Paper orders", risk.paper_orders_permitted],
          ["Live orders", risk.live_orders_permitted],
        ].map(([k, ok]) => (
          <div key={String(k)} className="rounded-lg bg-sunken px-3 py-2.5">
            <div className="text-xs text-muted">{k}</div>
            <div className={cx("mt-0.5 flex items-center gap-1.5 text-sm font-medium", ok ? "text-pass" : "text-fail")}>
              {ok ? <CheckCircle2 size={15} aria-hidden /> : <XCircle size={15} aria-hidden />}
              {ok ? "Permitted" : "Blocked"}
            </div>
          </div>
        ))}
      </div>
      {failing.length > 0 ? (
        <ul className="mt-4 space-y-2 text-sm">
          {failing.slice(0, 4).map((c) => (
            <li key={c.name} className="flex gap-2">
              {c.status === "FAIL" ? <XCircle size={15} className="mt-0.5 shrink-0 text-fail" aria-hidden /> : <CircleHelp size={15} className="mt-0.5 shrink-0 text-warn" aria-hidden />}
              <span className="min-w-0">
                <span className="block font-medium first-letter:uppercase">{humanize(c.name)}</span>
                <span className="block text-xs text-muted">{c.reason}</span>
              </span>
            </li>
          ))}
        </ul>
      ) : (
        <p className="mt-4 flex items-center gap-2 text-sm text-pass">
          <CheckCircle2 size={15} aria-hidden /> Every readiness check passes.
        </p>
      )}
    </Card>
  );
}

export default function Dashboard() {
  usePageTitle("Dashboard");
  const { me, guard, isAdmin } = useSession();
  const [risk, setRisk] = useState<RiskStatus | null>(null);
  const [regime, setRegime] = useState<Regime | null | undefined>(undefined);
  const [ranking, setRanking] = useState<RankingRun | null | undefined>(undefined);
  const [paper, setPaper] = useState<{ pf: PortfolioSummary; data: PaperPortfolioOut } | null | undefined>(undefined);
  const [alerts, setAlerts] = useState<{ unread: number; alerts: AlertOut[] } | null>(null);
  const [stocks, setStocks] = useState<StockSummary[] | null>(null);

  const load = useCallback(async () => {
    guard((t) => api.riskStatus(t)).then((r) => r && setRisk(r)).catch(() => {});
    guard((t) => api.regime(t)).then((r) => r !== undefined && setRegime(r)).catch(() => setRegime(null));
    guard((t) => api.latestRanking(t))
      .then((r) => r !== undefined && setRanking(r))
      .catch(() => setRanking(null)); // 404 = no ranking run yet
    guard((t) => api.alerts(t, false, 5)).then((r) => r && setAlerts(r)).catch(() => {});
    guard((t) => api.stocks(t)).then((s) => s && setStocks(s)).catch(() => setStocks([]));
    try {
      const pfs = await guard((t) => api.portfolios(t));
      const pf = pfs?.find((p) => p.kind === "paper");
      if (!pf) {
        setPaper(null);
        return;
      }
      const data = await guard((t) => api.paperPortfolio(t, pf.id));
      setPaper(data ? { pf, data } : null);
    } catch {
      setPaper(null);
    }
  }, [guard]);

  useEffect(() => {
    void load();
  }, [load]);

  const name = me?.email.split("@")[0] ?? "";
  const equity = paper?.data.analysis.metrics.equity ?? null;
  const qualified = ranking?.rows?.filter((r) => r.qualified) ?? [];
  const topRows = (ranking?.rows ?? []).slice(0, 5);
  const regimeTone = !regime?.known ? "text-warn" : regime.risk === "risk_off" ? "text-fail" : regime.risk === "risk_on" ? "text-pass" : "";

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <p className="text-sm text-muted">
            {new Date().toLocaleDateString("en-IN", { weekday: "long", day: "numeric", month: "long", timeZone: "Asia/Kolkata" })}
          </p>
          <h1 className="mt-0.5 text-2xl font-semibold tracking-tight">
            {greeting()}, <span className="capitalize">{name}</span>
          </h1>
        </div>
        <div className="flex flex-wrap gap-2">
          <LinkButton href="/stocks" icon={<Search size={15} />}>Research a stock</LinkButton>
          <LinkButton href="/trade" variant="primary" icon={<ShieldCheck size={15} />}>New trade</LinkButton>
        </div>
      </div>

      <div className="grid grid-cols-2 gap-3 lg:grid-cols-4 lg:gap-4">
        <StatCard
          href="/paper"
          icon={<Wallet size={14} aria-hidden />}
          label="Paper equity"
          value={paper === undefined ? <Skeleton className="h-7 w-28" /> : paper ? inr(equity, 0) : "—"}
          sub={
            paper ? (
              <span className={toneOf(paper.data.total_return)}>{signedPct(paper.data.total_return)} since start</span>
            ) : paper === null ? (
              "No paper portfolio yet"
            ) : undefined
          }
        />
        <StatCard
          href="/ranking"
          icon={<Trophy size={14} aria-hidden />}
          label="Qualified today"
          value={ranking === undefined ? <Skeleton className="h-7 w-16" /> : ranking ? `${ranking.qualified}` : "—"}
          sub={ranking ? `of ${ranking.evaluated} evaluated · ${ago(ranking.created_at ?? ranking.as_of)}` : ranking === null ? "No ranking run yet" : undefined}
          tone={ranking && ranking.qualified > 0 ? "text-pass" : undefined}
        />
        <StatCard
          href="/system"
          icon={<Gauge size={14} aria-hidden />}
          label="Market regime"
          value={regime === undefined ? <Skeleton className="h-7 w-32" /> : regime ? <span className={cx("capitalize", regimeTone)}>{humanize(regime.label).toLowerCase()}</span> : "Unknown"}
          sub={regime ? `Trend ${regime.trend} · volatility ${regime.volatility}` : "Macro series not ingested"}
        />
        <StatCard
          href="/alerts"
          icon={<Bell size={14} aria-hidden />}
          label="Unread alerts"
          value={alerts === null ? <Skeleton className="h-7 w-10" /> : alerts.unread}
          sub={alerts?.alerts[0] ? `Latest ${ago(alerts.alerts[0].created_at)}` : "All caught up"}
          tone={alerts && alerts.unread > 0 ? "text-warn" : undefined}
        />
      </div>

      <div className="grid gap-6 xl:grid-cols-3">
        <div className="min-w-0 space-y-6 xl:col-span-2">
          <WatchlistCard stocks={stocks} />
          {paper && paper.data.equity_curve.length > 1 && (
            <Card
              title={`Paper equity · ${paper.pf.name}`}
              description="Marked to market after each session close."
              actions={<LinkButton href="/paper" size="sm" variant="ghost">Open <ArrowRight size={14} /></LinkButton>}
            >
              <EquityChart data={paper.data.equity_curve.map((p) => ({ t: p.taken_at, equity: p.equity }))} />
            </Card>
          )}
        </div>

        <div className="min-w-0 space-y-6">
          <Card
            title="Top opportunities"
            description={ranking ? ranking.headline : "Standardised candidates through the 24 gates."}
            actions={<LinkButton href="/ranking" size="sm" variant="ghost">All <ArrowRight size={14} /></LinkButton>}
          >
            {ranking === undefined && <LoadingRows rows={4} />}
            {ranking === null && (
              <EmptyState
                icon={<Trophy size={20} />}
                title="No ranking yet"
                body={isAdmin ? "Run one from the Opportunities page, or wait for the daily job after the close." : "It runs daily after the market close."}
                compact
              />
            )}
            {ranking && (
              <ul className="-mx-2 space-y-0.5">
                {topRows.map((r) => (
                  <li key={r.ticker}>
                    <Link href={`/stocks/${encodeURIComponent(r.ticker)}`} className="flex items-center gap-3 rounded-lg px-2 py-2 hover:bg-hover">
                      <span className="w-5 text-right font-mono text-xs text-subtle">{r.rank}</span>
                      <span className="min-w-0 flex-1">
                        <span className="block font-mono text-[13px] font-semibold">{r.ticker}</span>
                        <span className="block truncate text-xs text-muted">
                          {r.qualified ? `P(profit) ${pct(r.p_profit)} · exp. ${signedPct(r.expected_net_return)}` : `Blocked: ${humanize(r.first_failure ?? "—")}`}
                        </span>
                      </span>
                      {r.qualified ? (
                        <Badge tone="pass" icon={<CheckCircle2 size={12} aria-hidden />}>Qualified</Badge>
                      ) : (
                        <Badge icon={<XCircle size={12} aria-hidden />}>Blocked</Badge>
                      )}
                    </Link>
                  </li>
                ))}
                {topRows.length === 0 && <li className="px-2 text-sm text-muted">No candidates were evaluated.</li>}
              </ul>
            )}
            {ranking && qualified.length === 0 && topRows.length > 0 && (
              <p className="mt-3 text-xs text-muted">Nothing qualified — “no trade” is a valid, and common, answer.</p>
            )}
          </Card>

          <Card
            title="Recent alerts"
            actions={<LinkButton href="/alerts" size="sm" variant="ghost">All <ArrowRight size={14} /></LinkButton>}
          >
            {alerts === null && <LoadingRows rows={3} />}
            {alerts?.alerts.length === 0 && <EmptyState icon={<Bell size={20} />} title="No alerts" compact />}
            <ul className="space-y-3">
              {alerts?.alerts.map((a) => (
                <li key={a.id} className="flex gap-3">
                  <span
                    className={cx(
                      "mt-1.5 h-2 w-2 shrink-0 rounded-full",
                      a.severity === "critical" ? "bg-fail" : a.severity === "warning" ? "bg-warn" : "bg-subtle",
                    )}
                    aria-hidden
                  />
                  <div className="min-w-0">
                    <p className={cx("text-sm", a.read_at ? "text-muted" : "font-medium")}>
                      <span className="sr-only">{a.severity}: </span>
                      {a.title}
                    </p>
                    <p className="text-xs text-subtle">{ago(a.created_at)}</p>
                  </div>
                </li>
              ))}
            </ul>
          </Card>

          <ReadinessCard risk={risk} />
        </div>
      </div>
    </div>
  );
}
