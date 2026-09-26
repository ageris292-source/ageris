"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import { readToken } from "@/lib/auth";

const LINKS = [
  { href: "/", label: "Dashboard" },
  { href: "/stocks", label: "Stocks" },
  { href: "/portfolios", label: "Portfolios" },
  { href: "/backtests", label: "Backtests" },
  { href: "/trade", label: "Trade risk" },
  { href: "/paper", label: "Paper trading" },
  { href: "/ranking", label: "Ranking" },
];

/** Unread alert count, refreshed every minute and when an alert is read. */
function AlertsBell({ active }: { active: boolean }) {
  const [unread, setUnread] = useState<number | null>(null);
  useEffect(() => {
    let stop = false;
    const tick = async () => {
      const t = readToken();
      if (!t) return;
      try {
        const r = await api.alerts(t, true, 1);
        if (!stop) setUnread(r.unread);
      } catch {
        if (!stop) setUnread(null); // unknown, never a fake zero
      }
    };
    void tick();
    const id = setInterval(tick, 60_000);
    window.addEventListener("aegis:alerts-changed", tick);
    return () => {
      stop = true;
      clearInterval(id);
      window.removeEventListener("aegis:alerts-changed", tick);
    };
  }, []);
  const label = unread === null ? "Alerts" : `Alerts, ${unread} unread`;
  return (
    <Link
      href="/alerts"
      aria-label={label}
      title={label}
      aria-current={active ? "page" : undefined}
      className={`relative inline-flex items-center gap-1 ${active ? "text-ink" : "text-muted hover:text-ink"}`}
    >
      <svg aria-hidden width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
        <path d="M6 8a6 6 0 0 1 12 0c0 7 3 9 3 9H3s3-2 3-9" />
        <path d="M10.3 21a1.94 1.94 0 0 0 3.4 0" />
      </svg>
      {unread !== null && unread > 0 && (
        <span className="rounded-full bg-fail px-1.5 font-mono text-[10px] leading-4 text-surface">
          {unread > 99 ? "99+" : unread}
        </span>
      )}
    </Link>
  );
}

export function Nav({
  mode,
  email,
  role,
  onSignOut,
}: {
  mode?: string;
  email?: string;
  role?: string;
  onSignOut: () => void;
}) {
  const path = usePathname();
  return (
    <header className="mb-8 flex flex-wrap items-center justify-between gap-4">
      <div className="flex items-center gap-6">
        <div className="flex items-center gap-3">
          <Link href="/" className="text-2xl font-semibold">Aegis</Link>
          {mode && (
            <span className="rounded border border-line px-2 py-0.5 font-mono text-xs uppercase">
              {mode} mode
            </span>
          )}
        </div>
        <nav className="flex flex-wrap gap-x-4 gap-y-1 text-sm">
          {[...LINKS, ...(role === "admin" ? [{ href: "/monitoring", label: "Monitoring" }] : [])].map((l) => {
            const active = l.href === "/" ? path === "/" : path.startsWith(l.href);
            return (
              <Link
                key={l.href}
                href={l.href}
                className={active ? "text-ink" : "text-muted hover:text-ink"}
                aria-current={active ? "page" : undefined}
              >
                {l.label}
              </Link>
            );
          })}
        </nav>
      </div>
      <div className="flex items-center gap-4 text-sm text-muted">
        <AlertsBell active={path.startsWith("/alerts")} />
        {email && <span>{email} · {role}</span>}
        <button className="underline" onClick={onSignOut}>Sign out</button>
      </div>
    </header>
  );
}
