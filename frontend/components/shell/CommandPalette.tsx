"use client";

import { CornerDownLeft, LineChart, Search } from "lucide-react";
import { useRouter } from "next/navigation";
import { useEffect, useMemo, useRef, useState } from "react";
import { useSession } from "@/components/providers/SessionProvider";
import { ACCOUNT_ITEM, NAV } from "@/components/shell/nav";
import { cx } from "@/components/ui/core";
import { api, type StockSummary } from "@/lib/api";
import { signedPct, toneOf } from "@/lib/format";

interface Result {
  key: string;
  label: string;
  sub?: string;
  href: string;
  icon: React.ReactNode;
  right?: React.ReactNode;
}

/** ⌘K / Ctrl K: jump to any page or stock. */
export function CommandPalette({ open, onClose }: { open: boolean; onClose: () => void }) {
  const { guard, isAdmin } = useSession();
  const router = useRouter();
  const [q, setQ] = useState("");
  const [stocks, setStocks] = useState<StockSummary[] | null>(null);
  const [active, setActive] = useState(0);
  const input = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (!open) return;
    setQ("");
    setActive(0);
    setStocks(null);
    setTimeout(() => input.current?.focus(), 10);
    guard((t) => api.stocks(t))
      .then((s) => s && setStocks(s))
      .catch(() => setStocks([]));
  }, [open, guard]);

  const results = useMemo<Result[]>(() => {
    const needle = q.trim().toLowerCase();
    const pages = [...NAV.flatMap((g) => g.items), ACCOUNT_ITEM]
      .filter((i) => !i.adminOnly || isAdmin)
      .filter((i) => !needle || `${i.label} ${i.keywords ?? ""}`.toLowerCase().includes(needle))
      .map<Result>((i) => ({ key: "p" + i.href, label: i.label, href: i.href, icon: <i.icon size={16} aria-hidden />, sub: "Page" }));
    const st = (stocks ?? [])
      .filter((s) => !needle || s.ticker.toLowerCase().includes(needle) || (s.name ?? "").toLowerCase().includes(needle))
      .slice(0, needle ? 12 : 6)
      .map<Result>((s) => ({
        key: "s" + s.ticker,
        label: s.ticker,
        sub: s.name ?? undefined,
        href: `/stocks/${encodeURIComponent(s.ticker)}`,
        icon: <LineChart size={16} aria-hidden />,
        right: s.change_pct != null ? <span className={cx("font-mono text-xs", toneOf(s.change_pct))}>{signedPct(s.change_pct)}</span> : undefined,
      }));
    return needle ? [...st, ...pages] : [...pages, ...st];
  }, [q, stocks, isAdmin]);

  useEffect(() => setActive(0), [q]);

  function go(r: Result | undefined) {
    if (!r) return;
    onClose();
    router.push(r.href);
  }

  if (!open) return null;
  return (
    <div className="fixed inset-0 z-[75] flex items-start justify-center px-3 pt-[calc(env(safe-area-inset-top)+0.75rem)] sm:px-4 sm:pt-[12vh]">
      <div className="absolute inset-0 bg-black/40 backdrop-blur-[2px]" onClick={onClose} aria-hidden />
      <div role="dialog" aria-modal="true" aria-label="Search" className="animate-in relative w-full max-w-xl overflow-hidden rounded-2xl border border-line bg-elevated shadow-[var(--shadow-pop)]">
        <div className="flex items-center gap-3 border-b border-line px-4">
          <Search size={18} className="text-subtle" aria-hidden />
          <input
            ref={input}
            value={q}
            onChange={(e) => setQ(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Escape") onClose();
              if (e.key === "ArrowDown") {
                e.preventDefault();
                setActive((a) => Math.min(a + 1, results.length - 1));
              }
              if (e.key === "ArrowUp") {
                e.preventDefault();
                setActive((a) => Math.max(a - 1, 0));
              }
              if (e.key === "Enter") go(results[active]);
            }}
            placeholder="Search stocks or jump to a page…"
            className="h-14 flex-1 bg-transparent text-base outline-none placeholder:text-subtle"
            aria-label="Search stocks and pages"
            role="combobox"
            aria-expanded="true"
            aria-controls="palette-results"
          />
          <kbd className="hidden rounded border border-line px-1.5 py-0.5 text-[10px] text-subtle sm:inline">Esc</kbd>
          <button onClick={onClose} className="-mr-2 px-2 py-2 text-sm font-medium text-accent sm:hidden">Cancel</button>
        </div>
        <ul id="palette-results" role="listbox" className="max-h-[60dvh] overflow-y-auto p-2 sm:max-h-[50vh]">
          {results.map((r, i) => (
            <li key={r.key} role="option" aria-selected={i === active}>
              <button
                onMouseEnter={() => setActive(i)}
                onClick={() => go(r)}
                className={cx("flex w-full items-center gap-3 rounded-lg px-3 py-3 text-left sm:py-2.5", i === active ? "bg-hover" : "")}
              >
                <span className="text-subtle">{r.icon}</span>
                <span className="min-w-0 flex-1">
                  <span className="block truncate text-sm font-medium">{r.label}</span>
                  {r.sub && <span className="block truncate text-xs text-muted">{r.sub}</span>}
                </span>
                {r.right}
                {i === active && <CornerDownLeft size={14} className="text-subtle" aria-hidden />}
              </button>
            </li>
          ))}
          {stocks === null && q.trim() !== "" && (
            <li className="flex items-center gap-2 px-3 py-3 text-sm text-muted" role="status">
              <span className="skeleton h-4 w-4 rounded-full" aria-hidden /> Loading stocks…
            </li>
          )}
          {results.length === 0 && stocks !== null && (
            <li className="px-3 py-8 text-center text-sm text-muted">
              No match. {q.includes(".") ? "Only stocks in the universe are searchable — an admin can add it on the Stocks page." : "Try a ticker like TCS.NS."}
            </li>
          )}
        </ul>
      </div>
    </div>
  );
}
