"use client";

import { Check, ListPlus, Pencil, Plus, Star, Trash2 } from "lucide-react";
import { useCallback, useEffect, useState } from "react";
import { useSession } from "@/components/providers/SessionProvider";
import { useToast } from "@/components/providers/ToastProvider";
import { Dialog } from "@/components/ui/Dialog";
import { Button, IconButton, Input, cx } from "@/components/ui/core";
import { api, ApiError, type WatchlistList, type WatchlistRow } from "@/lib/api";

const CHANGED = "aegis:watchlist-changed";
const changed = () => window.dispatchEvent(new Event(CHANGED));
const errMsg = (err: unknown) => (err instanceof ApiError ? err.message : undefined);

/** The signed-in user's named watchlists. */
export function useWatchlists() {
  const { guard, token } = useSession();
  const [lists, setLists] = useState<WatchlistList[] | null>(null);
  const load = useCallback(async () => {
    try {
      const r = await guard((t) => api.watchlists(t));
      if (r) setLists(r);
    } catch {
      setLists((l) => l ?? []);
    }
  }, [guard]);
  useEffect(() => {
    if (!token) return;
    void load();
    window.addEventListener(CHANGED, load);
    return () => window.removeEventListener(CHANGED, load);
  }, [token, load]);
  return { lists, reload: load };
}

/** One watchlist's rows (null list = the default, first list). */
export function useWatchlist(listId: number | null = null) {
  const { guard, token } = useSession();
  const toast = useToast();
  const [rows, setRows] = useState<WatchlistRow[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      const r = await guard((t) => api.watchlist(t, listId));
      if (r) setRows(r);
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not load the watchlist");
    }
  }, [guard, listId]);

  useEffect(() => {
    if (!token) return;
    setRows(null);
    void load();
    window.addEventListener(CHANGED, load);
    return () => window.removeEventListener(CHANGED, load);
  }, [token, load]);

  const has = useCallback((ticker: string) => !!rows?.some((r) => r.ticker === ticker), [rows]);

  const toggle = useCallback(
    async (ticker: string, listName = "your watchlist") => {
      const on = has(ticker);
      try {
        if (on) await guard((t) => api.unwatch(t, ticker, listId));
        else await guard((t) => api.watch(t, ticker, undefined, listId));
        toast({ tone: "success", title: on ? `Removed ${ticker} from ${listName}` : `Added ${ticker} to ${listName}` });
        changed();
      } catch (err) {
        toast({ tone: "error", title: "Watchlist not updated", body: errMsg(err) });
      }
    },
    [guard, has, toast, listId],
  );

  return { rows, error, has, toggle, reload: load };
}

export function WatchStar({
  on,
  onToggle,
  ticker,
  size = 16,
  withLabel,
}: {
  on: boolean;
  onToggle: () => void;
  ticker: string;
  size?: number;
  withLabel?: boolean;
}) {
  return (
    <button
      onClick={(e) => {
        e.preventDefault();
        e.stopPropagation();
        onToggle();
      }}
      aria-pressed={on}
      aria-label={on ? `Remove ${ticker} from watchlist` : `Add ${ticker} to watchlist`}
      title={on ? "On your watchlist" : "Add to watchlist"}
      className={cx(
        "inline-flex items-center gap-1.5 rounded-md transition-colors",
        withLabel ? "h-11 w-11 justify-center border border-line bg-panel text-sm font-medium shadow-sm hover:bg-hover sm:h-9 sm:w-auto sm:px-3" : "p-3 hover:bg-hover sm:p-1",
        on ? "text-[#c98500]" : "text-subtle hover:text-ink",
      )}
    >
      <Star size={size} fill={on ? "currentColor" : "none"} aria-hidden />
      {withLabel && <span className="hidden sm:inline">{on ? "Watching" : "Watch"}</span>}
    </button>
  );
}

/** Tick which of your lists hold this stock. */
export function ListMembership({ ticker }: { ticker: string }) {
  const { guard, token } = useSession();
  const toast = useToast();
  const { lists } = useWatchlists();
  const [member, setMember] = useState<number[] | null>(null);
  const [busy, setBusy] = useState<number | null>(null);

  const load = useCallback(async () => {
    try {
      const r = await guard((t) => api.watchMembership(t, ticker));
      if (r) setMember(r);
    } catch {
      setMember([]);
    }
  }, [guard, ticker]);
  useEffect(() => {
    if (!token) return;
    void load();
    window.addEventListener(CHANGED, load);
    return () => window.removeEventListener(CHANGED, load);
  }, [token, load]);

  async function flip(l: WatchlistList) {
    const on = member?.includes(l.id);
    setBusy(l.id);
    try {
      if (on) await guard((t) => api.unwatch(t, ticker, l.id));
      else await guard((t) => api.watch(t, ticker, undefined, l.id));
      changed();
    } catch (err) {
      toast({ tone: "error", title: "List not updated", body: errMsg(err) });
    } finally {
      setBusy(null);
    }
  }

  if (!lists || !member) return <p className="text-xs text-subtle">Loading lists…</p>;
  return (
    <div className="flex flex-wrap gap-2">
      {lists.map((l) => {
        const on = member.includes(l.id);
        return (
          <button
            key={l.id}
            type="button"
            aria-pressed={on}
            disabled={busy === l.id}
            onClick={() => flip(l)}
            className={cx(
              "inline-flex h-10 items-center gap-1.5 rounded-full border px-3.5 text-sm font-medium transition-colors disabled:opacity-50 sm:h-8 sm:text-xs",
              on ? "border-accent/40 bg-accent-soft text-accent" : "border-line text-muted hover:bg-hover hover:text-ink",
            )}
          >
            {on ? <Check size={13} aria-hidden /> : <Plus size={13} aria-hidden />}
            {l.name}
          </button>
        );
      })}
    </div>
  );
}

/** Create, rename and delete lists. */
export function ManageListsDialog({ open, onClose }: { open: boolean; onClose: () => void }) {
  const { guard } = useSession();
  const toast = useToast();
  const { lists } = useWatchlists();
  const [name, setName] = useState("");
  const [editing, setEditing] = useState<number | null>(null);
  const [draft, setDraft] = useState("");
  const [busy, setBusy] = useState(false);

  async function run(fn: () => Promise<unknown>, ok: string) {
    setBusy(true);
    try {
      await fn();
      toast({ tone: "success", title: ok });
      changed();
      return true;
    } catch (err) {
      toast({ tone: "error", title: "Not saved", body: errMsg(err) });
      return false;
    } finally {
      setBusy(false);
    }
  }

  return (
    <Dialog open={open} onClose={onClose} title="Your watchlists" description="Group stocks however you like. Lists are private to you." footer={<Button onClick={onClose}>Done</Button>}>
      <form
        className="mb-4 flex gap-2"
        onSubmit={async (e) => {
          e.preventDefault();
          const n = name.trim();
          if (n && (await run(() => guard((t) => api.createWatchlist(t, n)), `Created “${n}”`))) setName("");
        }}
      >
        <Input value={name} onChange={(e) => setName(e.target.value)} placeholder="New list name, e.g. Banks" maxLength={60} aria-label="New list name" />
        <Button type="submit" variant="primary" icon={<ListPlus size={15} />} disabled={!name.trim()} loading={busy && !editing}>
          Create
        </Button>
      </form>
      <ul className="divide-y divide-line rounded-lg border border-line">
        {(lists ?? []).map((l) => (
          <li key={l.id} className="flex items-center gap-2 px-3 py-2">
            {editing === l.id ? (
              <form
                className="flex flex-1 gap-2"
                onSubmit={async (e) => {
                  e.preventDefault();
                  if (await run(() => guard((t) => api.updateWatchlist(t, l.id, { name: draft })), "List renamed")) setEditing(null);
                }}
              >
                <Input value={draft} onChange={(e) => setDraft(e.target.value)} maxLength={60} aria-label="List name" autoFocus />
                <Button type="submit" size="sm" disabled={!draft.trim()}>
                  Save
                </Button>
              </form>
            ) : (
              <>
                <span className="min-w-0 flex-1 truncate text-sm font-medium">{l.name}</span>
                <span className="text-xs text-subtle">{l.count} {l.count === 1 ? "stock" : "stocks"}</span>
                <IconButton
                  label={`Rename ${l.name}`}
                  onClick={() => {
                    setEditing(l.id);
                    setDraft(l.name);
                  }}
                >
                  <Pencil size={15} />
                </IconButton>
                <IconButton
                  label={`Delete ${l.name}`}
                  disabled={(lists?.length ?? 0) <= 1}
                  onClick={() => run(() => guard((t) => api.deleteWatchlist(t, l.id)), `Deleted “${l.name}”`)}
                >
                  <Trash2 size={15} />
                </IconButton>
              </>
            )}
          </li>
        ))}
      </ul>
      <p className="mt-3 text-xs text-subtle">The star on Stocks pages adds to your first list. You always keep at least one list.</p>
    </Dialog>
  );
}
