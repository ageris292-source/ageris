"use client";

import { ArrowDown, ArrowUp, ChevronsUpDown, LineChart, Plus, RefreshCw, Search } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useCallback, useEffect, useMemo, useState } from "react";
import { usePageTitle } from "@/components/usePageTitle";
import { useWatchlist, WatchStar } from "@/components/Watchlist";
import { useSession } from "@/components/providers/SessionProvider";
import { useToast } from "@/components/providers/ToastProvider";
import { Dialog } from "@/components/ui/Dialog";
import { Sparkline } from "@/components/ui/Sparkline";
import { FreshnessBadge } from "@/components/ui/Status";
import {
  Button,
  Card,
  EmptyState,
  Field,
  IconButton,
  Input,
  LoadingRows,
  PageHeader,
  Segmented,
  Table,
  Td,
  Th,
  cx,
} from "@/components/ui/core";
import { ApiError, api, type StockSummary } from "@/lib/api";
import { humanize, inr, istDate, signedPct, toneOf } from "@/lib/format";

type Filter = "all" | "watch" | "stale";
type SortKey = "ticker" | "change" | "last";

function AddStockDialog({ open, onClose, onAdded }: { open: boolean; onClose: () => void; onAdded: (t: string) => void }) {
  const { guard } = useSession();
  const toast = useToast();
  const [ticker, setTicker] = useState("");
  const [fetchNow, setFetchNow] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const valid = /^[A-Z0-9&\-]{1,20}\.(NS|BO)$/.test(ticker.trim().toUpperCase());

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    const t = ticker.trim().toUpperCase();
    setBusy(true);
    setError(null);
    try {
      await guard((tok) => api.addStock(tok, t));
      if (fetchNow) {
        const run = await guard((tok) => api.ingest(tok, t));
        if (run && (run.status === "failed" || run.status === "rejected")) {
          toast({ tone: "warning", title: `${t} added, but the price fetch ${run.status}`, body: run.error ?? undefined });
        } else {
          toast({ tone: "success", title: `${t} added`, body: run ? `${run.rows_inserted} sessions of prices stored.` : undefined });
        }
      } else {
        toast({ tone: "success", title: `${t} added to the universe` });
      }
      setTicker("");
      onAdded(t);
      onClose();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not add the stock");
    } finally {
      setBusy(false);
    }
  }

  return (
    <Dialog
      open={open}
      onClose={onClose}
      title="Add a stock"
      description="NSE tickers end in .NS, BSE tickers in .BO. Indian equities only."
      footer={
        <>
          <Button onClick={onClose} disabled={busy}>Cancel</Button>
          <Button variant="primary" type="submit" form="add-stock" loading={busy} disabled={!valid}>
            {fetchNow ? "Add and fetch prices" : "Add stock"}
          </Button>
        </>
      }
    >
      <form id="add-stock" onSubmit={submit} className="space-y-4">
        <Field label="Ticker" error={error ?? (ticker && !valid ? "Use SYMBOL.NS or SYMBOL.BO, e.g. TCS.NS" : undefined)}>
          {(id) => (
            <Input id={id} value={ticker} onChange={(e) => setTicker(e.target.value)} placeholder="TCS.NS" className="font-mono uppercase" autoComplete="off" />
          )}
        </Field>
        <label className="flex items-start gap-2.5 text-sm">
          <input type="checkbox" checked={fetchNow} onChange={(e) => setFetchNow(e.target.checked)} className="mt-0.5 h-4 w-4 accent-[var(--accent)]" />
          <span>
            Fetch five years of prices now
            <span className="block text-xs text-muted">Research-only source. Licensed NSE data also arrives from the evening feeder.</span>
          </span>
        </label>
      </form>
    </Dialog>
  );
}

function SortHeader({ label, k, sort, onSort, align }: { label: string; k: SortKey; sort: [SortKey, 1 | -1]; onSort: (k: SortKey) => void; align?: "right" }) {
  const active = sort[0] === k;
  const Icon = !active ? ChevronsUpDown : sort[1] === 1 ? ArrowUp : ArrowDown;
  return (
    <Th align={align}>
      <button onClick={() => onSort(k)} className={cx("inline-flex items-center gap-1 hover:text-ink", active && "text-ink")} aria-label={`Sort by ${label}`}>
        {label}
        <Icon size={12} aria-hidden />
      </button>
    </Th>
  );
}

export default function StocksPage() {
  usePageTitle("Stocks");
  const { guard, isAdmin } = useSession();
  const toast = useToast();
  const router = useRouter();
  const { has, toggle } = useWatchlist();
  const [stocks, setStocks] = useState<StockSummary[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [q, setQ] = useState("");
  const [filter, setFilter] = useState<Filter>("all");
  const [sort, setSort] = useState<[SortKey, 1 | -1]>(["ticker", 1]);
  const [busy, setBusy] = useState<string | null>(null);
  const [adding, setAdding] = useState(false);

  const load = useCallback(async () => {
    try {
      const rows = await guard((t) => api.stocks(t));
      if (rows) setStocks(rows);
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not load stocks");
    }
  }, [guard]);

  useEffect(() => {
    void load();
  }, [load]);

  async function refresh(tk: string) {
    setBusy(tk);
    try {
      const run = await guard((t) => api.ingest(t, tk));
      if (run) {
        const bad = run.status === "failed" || run.status === "rejected";
        toast({
          tone: bad ? "error" : "success",
          title: `${tk}: ${humanize(run.status)}`,
          body: `${run.rows_inserted} new, ${run.rows_revised} revised, ${run.rows_rejected} rejected${run.error ? ` — ${run.error}` : ""}`,
        });
      }
      await load();
    } catch (err) {
      toast({ tone: "error", title: `Could not refresh ${tk}`, body: err instanceof Error ? err.message : undefined });
    } finally {
      setBusy(null);
    }
  }

  const rows = useMemo(() => {
    const needle = q.trim().toLowerCase();
    const list = (stocks ?? []).filter((s) => {
      if (needle && !s.ticker.toLowerCase().includes(needle) && !(s.name ?? "").toLowerCase().includes(needle)) return false;
      if (filter === "watch" && !has(s.ticker)) return false;
      if (filter === "stale" && s.freshness.status === "PASS") return false;
      return true;
    });
    const [k, dir] = sort;
    return [...list].sort((a, b) => {
      if (k === "ticker") return a.ticker.localeCompare(b.ticker) * dir;
      const av = k === "change" ? a.change_pct : a.last_close;
      const bv = k === "change" ? b.change_pct : b.last_close;
      if (av == null && bv == null) return 0;
      if (av == null) return 1;
      if (bv == null) return -1;
      return (av - bv) * dir;
    });
  }, [stocks, q, filter, sort, has]);

  const onSort = (k: SortKey) => setSort(([sk, d]) => (sk === k ? [k, d === 1 ? -1 : 1] : [k, k === "ticker" ? 1 : -1]));
  const staleCount = (stocks ?? []).filter((s) => s.freshness.status !== "PASS").length;

  return (
    <>
      <PageHeader
        title="Stocks"
        description="The research universe: NSE (.NS) and BSE (.BO) end-of-day data, validated and versioned."
        actions={isAdmin && <Button variant="primary" icon={<Plus size={16} />} onClick={() => setAdding(true)}>Add stock</Button>}
      />

      <Card bodyClassName="pb-2">
        <div className="mb-4 flex flex-wrap items-center gap-3">
          <div className="relative min-w-[220px] flex-1 sm:max-w-sm">
            <Search size={16} className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-subtle" aria-hidden />
            <Input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Filter by ticker or name" className="pl-9" aria-label="Filter stocks" />
          </div>
          <Segmented<Filter>
            label="Show"
            value={filter}
            onChange={setFilter}
            options={[
              { value: "all", label: `All${stocks ? ` · ${stocks.length}` : ""}` },
              { value: "watch", label: "Watchlist" },
              { value: "stale", label: `Needs data${staleCount ? ` · ${staleCount}` : ""}` },
            ]}
          />
        </div>

        {error && <p className="mb-3 text-sm text-fail">{error}</p>}
        {stocks === null && !error && <LoadingRows rows={6} />}
        {stocks && stocks.length === 0 && (
          <EmptyState
            icon={<LineChart size={20} />}
            title="The universe is empty"
            body={isAdmin ? "Add your first stock, e.g. TCS.NS or RELIANCE.NS." : "Ask an admin to add stocks."}
            action={isAdmin && <Button variant="primary" icon={<Plus size={16} />} onClick={() => setAdding(true)}>Add stock</Button>}
          />
        )}
        {stocks && stocks.length > 0 && rows.length === 0 && (
          <EmptyState compact icon={<Search size={20} />} title="No stocks match" body={filter === "watch" ? "Star stocks to add them to your watchlist." : "Try a different filter."} />
        )}
        {rows.length > 0 && (
          <Table>
            <thead>
              <tr>
                <Th className="w-10" />
                <SortHeader label="Stock" k="ticker" sort={sort} onSort={onSort} />
                <Th className="hidden md:table-cell">30-session trend</Th>
                <SortHeader label="Last close" k="last" sort={sort} onSort={onSort} align="right" />
                <SortHeader label="Day" k="change" sort={sort} onSort={onSort} align="right" />
                <Th className="hidden sm:table-cell">Data</Th>
                <Th className="hidden lg:table-cell">Latest session</Th>
                <Th />
              </tr>
            </thead>
            <tbody>
              {rows.map((s) => (
                <tr
                  key={s.ticker}
                  className="cursor-pointer hover:bg-hover"
                  onClick={() => router.push(`/stocks/${encodeURIComponent(s.ticker)}`)}
                >
                  <Td className="!pr-0">
                    <WatchStar on={has(s.ticker)} ticker={s.ticker} onToggle={() => toggle(s.ticker)} />
                  </Td>
                  <Td>
                    <Link href={`/stocks/${encodeURIComponent(s.ticker)}`} onClick={(e) => e.stopPropagation()} className="block">
                      <span className="font-mono text-[13px] font-semibold">{s.ticker}</span>
                      <span className="block max-w-[140px] truncate text-xs text-muted sm:max-w-[260px]">{s.name ?? `${s.exchange} · name not reported`}</span>
                    </Link>
                  </Td>
                  <Td className="hidden md:table-cell">
                    <Sparkline values={s.sparkline ?? []} width={110} />
                  </Td>
                  <Td align="right" mono>{inr(s.last_close)}</Td>
                  <Td align="right" mono className={toneOf(s.change_pct)}>{signedPct(s.change_pct)}</Td>
                  <Td className="hidden sm:table-cell"><FreshnessBadge f={s.freshness} /></Td>
                  <Td className="hidden text-muted lg:table-cell">{istDate(s.latest_session)}</Td>
                  <Td align="right">
                    <IconButton
                      label={`Refresh ${s.ticker} prices`}
                      disabled={busy !== null}
                      onClick={(e) => {
                        e.stopPropagation();
                        void refresh(s.ticker);
                      }}
                    >
                      <RefreshCw size={15} className={busy === s.ticker ? "animate-spin" : ""} />
                    </IconButton>
                  </Td>
                </tr>
              ))}
            </tbody>
          </Table>
        )}
      </Card>

      <AddStockDialog
        open={adding}
        onClose={() => setAdding(false)}
        onAdded={(t) => {
          void load();
          router.push(`/stocks/${encodeURIComponent(t)}`);
        }}
      />
    </>
  );
}
