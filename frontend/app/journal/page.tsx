"use client";

import { Download, NotebookPen, Plus, Search } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { JournalEditor, JournalList, KINDS, useJournal } from "@/components/Journal";
import { usePageTitle } from "@/components/usePageTitle";
import { useSession } from "@/components/providers/SessionProvider";
import { useToast } from "@/components/providers/ToastProvider";
import { Button, Card, EmptyState, Input, PageHeader, Segmented, StatCard } from "@/components/ui/core";
import { api, ApiError, type JournalKind, type StockSummary } from "@/lib/api";

type KindFilter = "all" | JournalKind;

export default function JournalPage() {
  usePageTitle("Journal");
  const { guard, token } = useSession();
  const toast = useToast();
  const [kind, setKind] = useState<KindFilter>("all");
  const [q, setQ] = useState("");
  const [query, setQuery] = useState("");
  const [tag, setTag] = useState<string | null>(null);
  const [open, setOpen] = useState(false);
  const [stocks, setStocks] = useState<StockSummary[] | null>(null);

  // Debounce the search box.
  useEffect(() => {
    const id = setTimeout(() => setQuery(q.trim()), 300);
    return () => clearTimeout(id);
  }, [q]);

  useEffect(() => {
    if (!token) return;
    guard((t) => api.stocks(t))
      .then((r) => r && setStocks(r))
      .catch(() => setStocks([]));
  }, [guard, token]);

  const filter = useMemo(
    () => ({ kind: kind === "all" ? undefined : kind, q: query || undefined, tag: tag ?? undefined }),
    [kind, query, tag],
  );
  const { items, error } = useJournal(filter);
  const all = useJournal({});
  const counts = useMemo(() => {
    const c: Record<string, number> = { note: 0, entry: 0, exit: 0, review: 0 };
    for (const e of all.items ?? []) c[e.kind] += 1;
    return c;
  }, [all.items]);
  const tags = useMemo(() => {
    const m = new Map<string, number>();
    for (const e of all.items ?? []) for (const t of e.tags) m.set(t, (m.get(t) ?? 0) + 1);
    return [...m.entries()].sort((a, b) => b[1] - a[1]).slice(0, 12);
  }, [all.items]);

  const filtered = kind !== "all" || !!query || !!tag;

  return (
    <div className="space-y-6">
      <PageHeader
        title="Journal"
        description="Your private research notes and trade journal. Write why you enter, why you exit, and what you learned."
        actions={
          <>
            <Button
              icon={<Download size={15} />}
              onClick={() =>
                guard((t) => api.exportCsv(t, "journal")).catch((err) =>
                  toast({ tone: "error", title: "Export failed", body: err instanceof ApiError ? err.message : undefined }),
                )
              }
            >
              Export CSV
            </Button>
            <Button variant="primary" icon={<Plus size={15} />} onClick={() => setOpen(true)}>
              New entry
            </Button>
          </>
        }
      />

      <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
        {(Object.keys(KINDS) as JournalKind[]).map((k) => (
          <StatCard key={k} label={KINDS[k].label} value={all.items ? counts[k] : "—"} />
        ))}
      </div>

      <Card>
        <div className="mb-4 flex flex-col gap-3 lg:flex-row lg:items-center">
          <div className="relative flex-1">
            <Search size={15} className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-subtle" aria-hidden />
            <Input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Search your entries…" aria-label="Search the journal" className="pl-9" />
          </div>
          <Segmented<KindFilter>
            label="Filter by type"
            value={kind}
            onChange={setKind}
            options={[{ value: "all", label: "All" }, ...(Object.keys(KINDS) as JournalKind[]).map((k) => ({ value: k, label: KINDS[k].label }))]}
          />
        </div>
        {tags.length > 0 && (
          <div className="mb-4 flex flex-wrap gap-2" aria-label="Filter by tag">
            {tags.map(([t, n]) => (
              <button
                key={t}
                type="button"
                aria-pressed={tag === t}
                onClick={() => setTag(tag === t ? null : t)}
                className={
                  "h-9 rounded-full border px-3 text-xs font-medium transition-colors sm:h-7 " +
                  (tag === t ? "border-accent/40 bg-accent-soft text-accent" : "border-line text-muted hover:bg-hover hover:text-ink")
                }
              >
                #{t} <span className="text-subtle">{n}</span>
              </button>
            ))}
          </div>
        )}
        <JournalList
          items={items}
          error={error}
          empty={
            filtered ? (
              <EmptyState icon={<Search size={20} />} title="No entries match" body="Try another search or clear the filters." compact />
            ) : (
              <EmptyState
                icon={<NotebookPen size={20} />}
                title="Start your journal"
                body="Note why you like a stock, log the reason for each paper trade, and review what happened. Entries can link to a stock or a paper order."
                action={
                  <Button variant="primary" icon={<Plus size={15} />} onClick={() => setOpen(true)}>
                    Write the first entry
                  </Button>
                }
              />
            )
          }
        />
      </Card>
      <JournalEditor open={open} onClose={() => setOpen(false)} stocks={stocks} />
    </div>
  );
}
