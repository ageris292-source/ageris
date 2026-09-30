"use client";

import { NotebookPen, Pencil, Trash2 } from "lucide-react";
import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import { useSession } from "@/components/providers/SessionProvider";
import { useToast } from "@/components/providers/ToastProvider";
import { ConfirmDialog, Dialog } from "@/components/ui/Dialog";
import { Badge, Button, EmptyState, Field, IconButton, Input, LoadingRows, Select, Textarea, cx, type Tone } from "@/components/ui/core";
import { api, ApiError, type JournalEntryOut, type JournalKind, type StockSummary } from "@/lib/api";
import { ago, inr, istDateTime } from "@/lib/format";

export const KINDS: Record<JournalKind, { label: string; tone: Tone; hint: string }> = {
  note: { label: "Research note", tone: "neutral", hint: "Anything you learned or want to remember" },
  entry: { label: "Entry reason", tone: "info", hint: "Why you are buying: thesis, trigger, plan" },
  exit: { label: "Exit reason", tone: "warn", hint: "Why you sold or plan to sell" },
  review: { label: "Review / lesson", tone: "pass", hint: "What went right or wrong, in hindsight" },
};

const CHANGED = "aegis:journal-changed";
const errMsg = (err: unknown) => (err instanceof ApiError ? err.message : undefined);

export type JournalFilter = { ticker?: string; kind?: JournalKind; order_id?: number; tag?: string; q?: string };

export function useJournal(filter: JournalFilter) {
  const { guard, token } = useSession();
  const [items, setItems] = useState<JournalEntryOut[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const key = JSON.stringify(filter);
  const load = useCallback(async () => {
    try {
      const r = await guard((t) => api.journal(t, JSON.parse(key) as JournalFilter));
      if (r) setItems(r);
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not load the journal");
    }
  }, [guard, key]);
  useEffect(() => {
    if (!token) return;
    void load();
    window.addEventListener(CHANGED, load);
    return () => window.removeEventListener(CHANGED, load);
  }, [token, load]);
  return { items, error, reload: load };
}

export function JournalEditor({
  open,
  onClose,
  entry,
  ticker,
  orderId,
  orderLabel,
  stocks,
  defaultKind = "note",
}: {
  open: boolean;
  onClose: () => void;
  entry?: JournalEntryOut | null;
  ticker?: string;
  orderId?: number;
  orderLabel?: string;
  stocks?: StockSummary[] | null;
  defaultKind?: JournalKind;
}) {
  const { guard } = useSession();
  const toast = useToast();
  const [tk, setTk] = useState("");
  const [kind, setKind] = useState<JournalKind>(defaultKind);
  const [title, setTitle] = useState("");
  const [body, setBody] = useState("");
  const [tags, setTags] = useState("");
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (!open) return;
    setTk(entry?.ticker ?? ticker ?? "");
    setKind(entry?.kind ?? defaultKind);
    setTitle(entry?.title ?? "");
    setBody(entry?.body ?? "");
    setTags((entry?.tags ?? []).join(", "));
  }, [open, entry, ticker, defaultKind]);

  const fixedStock = !!entry || !!ticker || !!orderId;

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    if (!body.trim()) return;
    const tagList = tags
      .split(",")
      .map((t) => t.trim())
      .filter(Boolean);
    setBusy(true);
    try {
      if (entry) {
        await guard((t) => api.updateJournal(t, entry.id, { kind, title: title.trim() || "", body, tags: tagList }));
      } else {
        await guard((t) =>
          api.createJournal(t, {
            ticker: orderId ? null : tk.trim().toUpperCase() || null,
            order_id: orderId ?? null,
            kind,
            title: title.trim() || null,
            body,
            tags: tagList,
          }),
        );
      }
      toast({ tone: "success", title: entry ? "Entry updated" : "Saved to your journal" });
      window.dispatchEvent(new Event(CHANGED));
      onClose();
    } catch (err) {
      toast({ tone: "error", title: "Not saved", body: errMsg(err) });
    } finally {
      setBusy(false);
    }
  }

  return (
    <Dialog
      open={open}
      onClose={onClose}
      size="lg"
      title={entry ? "Edit journal entry" : "New journal entry"}
      description="Private to you. Write your reasoning in your own words: it's what makes the review useful later."
      footer={
        <>
          <Button onClick={onClose} disabled={busy}>
            Cancel
          </Button>
          <Button variant="primary" type="submit" form="journal-form" loading={busy} disabled={!body.trim()}>
            {entry ? "Save changes" : "Save entry"}
          </Button>
        </>
      }
    >
      <form id="journal-form" onSubmit={submit} className="grid gap-4 sm:grid-cols-2">
        <Field label="Type" hint={KINDS[kind].hint}>
          {(id) => (
            <Select id={id} value={kind} onChange={(e) => setKind(e.target.value as JournalKind)}>
              {(Object.keys(KINDS) as JournalKind[]).map((k) => (
                <option key={k} value={k}>
                  {KINDS[k].label}
                </option>
              ))}
            </Select>
          )}
        </Field>
        <Field label="Stock (optional)" hint={orderLabel ?? (fixedStock ? undefined : "Leave empty for a general note")}>
          {(id) =>
            fixedStock ? (
              <Input id={id} value={orderLabel ? (entry?.ticker ?? ticker ?? "") : tk} readOnly className="font-mono" />
            ) : (
              <>
                <Input id={id} list="journal-stocks" value={tk} onChange={(e) => setTk(e.target.value)} placeholder="e.g. INFY.NS" className="font-mono uppercase" />
                <datalist id="journal-stocks">
                  {(stocks ?? []).map((s) => (
                    <option key={s.ticker} value={s.ticker}>
                      {s.name ?? ""}
                    </option>
                  ))}
                </datalist>
              </>
            )
          }
        </Field>
        <Field label="Title (optional)" className="sm:col-span-2">
          {(id) => <Input id={id} value={title} onChange={(e) => setTitle(e.target.value)} maxLength={160} />}
        </Field>
        <Field label="Entry" className="sm:col-span-2">
          {(id) => <Textarea id={id} rows={7} value={body} onChange={(e) => setBody(e.target.value)} maxLength={20000} required />}
        </Field>
        <Field label="Tags (optional)" hint="Comma-separated, e.g. earnings, breakout" className="sm:col-span-2">
          {(id) => <Input id={id} value={tags} onChange={(e) => setTags(e.target.value)} />}
        </Field>
      </form>
    </Dialog>
  );
}

export function JournalList({
  items,
  error,
  showStock = true,
  empty,
}: {
  items: JournalEntryOut[] | null;
  error: string | null;
  showStock?: boolean;
  empty?: React.ReactNode;
}) {
  const { guard } = useSession();
  const toast = useToast();
  const [editing, setEditing] = useState<JournalEntryOut | null>(null);
  const [deleting, setDeleting] = useState<JournalEntryOut | null>(null);
  const [busy, setBusy] = useState(false);

  if (error) return <p className="text-sm text-fail">{error}</p>;
  if (items === null) return <LoadingRows rows={3} />;
  if (items.length === 0)
    return <>{empty ?? <EmptyState icon={<NotebookPen size={20} />} title="No entries yet" body="Write down why you do what you do. Future you will thank you." compact />}</>;

  return (
    <>
      <ul className="space-y-3">
        {items.map((e) => (
          <li key={e.id} className="rounded-lg border border-line p-3.5 sm:p-4">
            <div className="flex items-start gap-2">
              <div className="min-w-0 flex-1">
                <div className="flex flex-wrap items-center gap-2 text-xs text-muted">
                  <Badge tone={KINDS[e.kind].tone}>{KINDS[e.kind].label}</Badge>
                  {showStock && e.ticker && (
                    <Link href={`/stocks/${encodeURIComponent(e.ticker)}`} className="-my-3 py-3 font-mono font-semibold text-ink hover:text-accent">
                      {e.ticker}
                    </Link>
                  )}
                  {e.order && (
                    <span className="font-mono">
                      Order #{e.order.id} · {e.order.side.toUpperCase()} {e.order.quantity} @ {inr(e.order.limit_price)}
                    </span>
                  )}
                  <span title={istDateTime(e.created_at)}>{ago(e.created_at)}</span>
                  {e.updated_at && e.created_at && new Date(e.updated_at).getTime() - new Date(e.created_at).getTime() > 60_000 && <span>· edited</span>}
                </div>
                {e.title && <h3 className="mt-2 text-sm font-semibold">{e.title}</h3>}
                <p className={cx("whitespace-pre-line text-sm text-ink/90", e.title ? "mt-1" : "mt-2")}>{e.body}</p>
                {e.tags.length > 0 && (
                  <div className="mt-2 flex flex-wrap gap-1.5">
                    {e.tags.map((t) => (
                      <span key={t} className="rounded-full bg-sunken px-2 py-0.5 text-[11px] text-muted">
                        #{t}
                      </span>
                    ))}
                  </div>
                )}
              </div>
              <IconButton label="Edit entry" onClick={() => setEditing(e)}>
                <Pencil size={15} />
              </IconButton>
              <IconButton label="Delete entry" onClick={() => setDeleting(e)}>
                <Trash2 size={15} />
              </IconButton>
            </div>
          </li>
        ))}
      </ul>
      <JournalEditor open={!!editing} onClose={() => setEditing(null)} entry={editing} orderLabel={editing?.order ? `Linked to order #${editing.order.id}` : undefined} />
      <ConfirmDialog
        open={!!deleting}
        onClose={() => setDeleting(null)}
        title="Delete this entry?"
        body="It is removed from your journal permanently."
        confirmLabel="Delete"
        tone="danger"
        busy={busy}
        onConfirm={async () => {
          if (!deleting) return;
          setBusy(true);
          try {
            await guard((t) => api.deleteJournal(t, deleting.id));
            toast({ tone: "success", title: "Entry deleted" });
            window.dispatchEvent(new Event(CHANGED));
            setDeleting(null);
          } catch (err) {
            toast({ tone: "error", title: "Not deleted", body: errMsg(err) });
          } finally {
            setBusy(false);
          }
        }}
      />
    </>
  );
}
