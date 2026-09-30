"use client";

import { Download, History, UserRound } from "lucide-react";
import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import { usePageTitle } from "@/components/usePageTitle";
import { useSession } from "@/components/providers/SessionProvider";
import { useToast } from "@/components/providers/ToastProvider";
import { Badge, Button, Card, EmptyState, LoadingRows, PageHeader, Select, cx, type Tone } from "@/components/ui/core";
import { api, ApiError, type ActivityItem, type ActivityPage } from "@/lib/api";
import { ago, istDateTime } from "@/lib/format";

/** Plain-English labels. Unknown actions fall back to the raw name. */
const LABELS: Record<string, string> = {
  "auth.login": "Signed in",
  "auth.login_failed": "Failed sign-in",
  "auth.logout_all": "Signed out everywhere",
  "user.create": "Invited a user",
  "user.update": "Changed a user",
  "user.reset_password": "Reset a password",
  "user.change_password": "Changed own password",
  "kill_switch.activate": "Halted trading",
  "kill_switch.deactivate": "Resumed trading",
  "kill_switch.deactivate_denied": "Resume refused",
  "trade.proposal.evaluated": "Evaluated a trade",
  "paper.order.filled": "Paper order filled",
  "paper.order.rejected": "Paper order rejected",
  "paper.thesis.event": "Thesis event",
  "portfolio.create": "Created a portfolio",
  "portfolio.cash.set": "Set portfolio cash",
  "portfolio.position.set": "Set a position",
  "ranking.run": "Ran the ranking",
  "analysis.report": "Research report",
  "watchlist.add": "Added to watchlist",
  "watchlist.remove": "Removed from watchlist",
  "watchlist.list_create": "Created a watchlist",
  "watchlist.list_update": "Renamed a watchlist",
  "watchlist.list_delete": "Deleted a watchlist",
  "price_alert.create": "Created a price alert",
  "price_alert.update": "Changed a price alert",
  "price_alert.delete": "Deleted a price alert",
  "journal.create": "Wrote a journal entry",
  "journal.update": "Edited a journal entry",
  "journal.delete": "Deleted a journal entry",
  "export.csv": "Exported CSV",
  "alert.read": "Read an alert",
  "alert.read_all": "Marked alerts read",
  "stock.add": "Added a stock",
  "live.order.refused": "Live order refused",
  "backtest.run": "Ran a backtest",
};

function tone(action: string): Tone {
  if (action.includes("failed") || action.includes("refused") || action.includes("denied") || action.endsWith("rejected")) return "fail";
  if (action.startsWith("kill_switch")) return "warn";
  if (action.startsWith("paper.") || action.startsWith("trade.")) return "info";
  return "neutral";
}

function summary(i: ActivityItem): string | null {
  const d = i.details as Record<string, unknown>;
  const bits: string[] = [];
  for (const k of ["ticker", "email", "role", "name", "list", "condition", "threshold", "reason", "count", "rows", "client"]) {
    const v = d[k];
    if (v !== undefined && v !== null && v !== "") bits.push(k === "client" ? `IP ${v}` : k === "condition" ? String(v).replaceAll("_", " ") : String(v));
  }
  if (i.action === "export.csv" && i.entity_id) bits.unshift(i.entity_id);
  return bits.length ? bits.join(" · ") : null;
}

export default function ActivityPageView() {
  usePageTitle("Activity log");
  const { guard, token, isAdmin } = useSession();
  const toast = useToast();
  const [group, setGroup] = useState("");
  const [who, setWho] = useState<"all" | "me">("all");
  const [page, setPage] = useState<ActivityPage | null>(null);
  const [items, setItems] = useState<ActivityItem[] | null>(null);
  const [more, setMore] = useState(false);

  const load = useCallback(
    async (before?: number) => {
      if (before) setMore(true);
      try {
        const r = await guard((t) => api.activity(t, { action: group || undefined, actor: who === "me" ? "me" : undefined, before_id: before, limit: 50 }));
        if (r) {
          setPage(r);
          setItems((prev) => (before && prev ? [...prev, ...r.items] : r.items));
        }
      } catch (err) {
        toast({ tone: "error", title: "Could not load activity", body: err instanceof ApiError ? err.message : undefined });
        setItems((p) => p ?? []);
      } finally {
        setMore(false);
      }
    },
    [guard, group, who, toast],
  );

  useEffect(() => {
    if (!token) return;
    setItems(null);
    void load();
  }, [token, load]);

  const groups = page?.groups ?? {};
  const groupOptions = Object.entries(groups).filter(([, label], i, arr) => arr.findIndex(([, l]) => l === label) === i);

  return (
    <div className="space-y-6">
      <PageHeader
        title="Activity log"
        description={
          isAdmin
            ? "Everything people and the system did, from the append-only audit trail. Nothing here can be edited or deleted."
            : "Everything you did, from the append-only audit trail. Admins can see the whole team's activity."
        }
        actions={
          <Button
            icon={<Download size={15} />}
            onClick={() =>
              guard((t) => api.exportCsv(t, "activity")).catch((err) =>
                toast({ tone: "error", title: "Export failed", body: err instanceof ApiError ? err.message : undefined }),
              )
            }
          >
            Export CSV
          </Button>
        }
      />
      <Card>
        <div className="mb-4 grid gap-3 sm:flex sm:items-center">
          <Select value={group} onChange={(e) => setGroup(e.target.value)} aria-label="Filter by kind of action" className="sm:w-56">
            <option value="">All actions</option>
            {groupOptions.map(([prefix, label]) => (
              <option key={prefix} value={prefix}>
                {label}
              </option>
            ))}
          </Select>
          {isAdmin && (
            <Select value={who} onChange={(e) => setWho(e.target.value as "all" | "me")} aria-label="Whose activity" className="sm:w-44">
              <option value="all">Everyone</option>
              <option value="me">Only me</option>
            </Select>
          )}
        </div>
        {items === null ? (
          <LoadingRows rows={8} />
        ) : items.length === 0 ? (
          <EmptyState icon={<History size={20} />} title="Nothing recorded yet" compact />
        ) : (
          <ol className="relative space-y-0">
            {items.map((i) => {
              const s = summary(i);
              return (
                <li key={i.id} className="flex gap-3 border-b border-line py-3 last:border-0">
                  <div className="min-w-0 flex-1">
                    <div className="flex flex-wrap items-center gap-2">
                      <Badge tone={tone(i.action)}>{LABELS[i.action] ?? i.action}</Badge>
                      {s && <span className="min-w-0 truncate text-sm">{s}</span>}
                    </div>
                    <p className="mt-1 flex flex-wrap items-center gap-x-2 text-xs text-muted">
                      <span className="inline-flex items-center gap-1">
                        <UserRound size={12} aria-hidden /> {i.actor_email ?? "System"}
                      </span>
                      <span title={istDateTime(i.occurred_at)}>{istDateTime(i.occurred_at)}</span>
                      <span className="text-subtle">· {i.system_mode} mode</span>
                      {i.entity_type === "stock" && typeof i.details.ticker === "string" && (
                        <Link href={`/stocks/${encodeURIComponent(i.details.ticker)}`} className="-my-3 py-3 text-accent hover:underline">
                          Open stock
                        </Link>
                      )}
                    </p>
                  </div>
                  <span className={cx("hidden shrink-0 text-xs text-subtle sm:block")}>{ago(i.occurred_at)}</span>
                </li>
              );
            })}
          </ol>
        )}
        {page?.next_before_id && (
          <div className="mt-4 flex justify-center">
            <Button loading={more} onClick={() => load(page.next_before_id ?? undefined)} className="w-full sm:w-auto">
              Load older activity
            </Button>
          </div>
        )}
      </Card>
    </div>
  );
}
