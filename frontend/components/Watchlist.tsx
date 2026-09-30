"use client";

import { Star } from "lucide-react";
import { useCallback, useEffect, useState } from "react";
import { useSession } from "@/components/providers/SessionProvider";
import { useToast } from "@/components/providers/ToastProvider";
import { cx } from "@/components/ui/core";
import { api, ApiError, type WatchlistRow } from "@/lib/api";

/** The signed-in user's watchlist, shared across pages via a window event. */
export function useWatchlist() {
  const { guard, token } = useSession();
  const toast = useToast();
  const [rows, setRows] = useState<WatchlistRow[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      const r = await guard((t) => api.watchlist(t));
      if (r) setRows(r);
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not load the watchlist");
    }
  }, [guard]);

  useEffect(() => {
    if (!token) return;
    void load();
    window.addEventListener("aegis:watchlist-changed", load);
    return () => window.removeEventListener("aegis:watchlist-changed", load);
  }, [token, load]);

  const has = useCallback((ticker: string) => !!rows?.some((r) => r.ticker === ticker), [rows]);

  const toggle = useCallback(
    async (ticker: string) => {
      const on = has(ticker);
      try {
        if (on) await guard((t) => api.unwatch(t, ticker));
        else await guard((t) => api.watch(t, ticker));
        toast({ tone: "success", title: on ? `Removed ${ticker} from your watchlist` : `Added ${ticker} to your watchlist` });
        window.dispatchEvent(new Event("aegis:watchlist-changed"));
      } catch (err) {
        toast({ tone: "error", title: "Watchlist not updated", body: err instanceof ApiError ? err.message : undefined });
      }
    },
    [guard, has, toast],
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
