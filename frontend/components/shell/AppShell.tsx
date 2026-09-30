"use client";

import {
  Bell,
  ChevronDown,
  LogOut,
  Menu,
  Monitor,
  Moon,
  OctagonPause,
  Search,
  Settings2,
  ShieldCheck,
  Sun,
  TriangleAlert,
  X,
} from "lucide-react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { useCallback, useEffect, useRef, useState } from "react";
import { useSession } from "@/components/providers/SessionProvider";
import { useTheme, type ThemePref } from "@/components/providers/ThemeProvider";
import { ForcedPasswordScreen, LoginScreen } from "@/components/shell/AuthScreens";
import { Brand } from "@/components/shell/Brand";
import { CommandPalette } from "@/components/shell/CommandPalette";
import { ACCOUNT_ITEM, NAV, isActive } from "@/components/shell/nav";
import { cx } from "@/components/ui/core";
import { api, type RiskStatus } from "@/lib/api";

/* Unread alert count, refreshed every minute and whenever a page says alerts changed. */
function useUnreadAlerts() {
  const { guard, token } = useSession();
  const [unread, setUnread] = useState<number | null>(null);
  useEffect(() => {
    if (!token) return;
    let stop = false;
    const tick = async () => {
      try {
        const r = await guard((t) => api.alerts(t, true, 1));
        if (!stop && r) setUnread(r.unread);
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
  }, [guard, token]);
  return unread;
}

/* Kill switch / execution readiness, shared by the sidebar footer. */
function useRisk() {
  const { guard, token } = useSession();
  const [risk, setRisk] = useState<RiskStatus | null>(null);
  useEffect(() => {
    if (!token) return;
    const load = () => guard((t) => api.riskStatus(t)).then((r) => r && setRisk(r)).catch(() => setRisk(null));
    void load();
    const id = setInterval(load, 60_000);
    window.addEventListener("aegis:risk-changed", load);
    return () => {
      clearInterval(id);
      window.removeEventListener("aegis:risk-changed", load);
    };
  }, [guard, token]);
  return risk;
}

function SidebarNav({ onNavigate, unread }: { onNavigate?: () => void; unread: number | null }) {
  const path = usePathname();
  const { isAdmin } = useSession();
  return (
    <nav aria-label="Main" className="flex-1 space-y-6 overflow-y-auto px-3 py-4">
      {NAV.map((g) => {
        const items = g.items.filter((i) => !i.adminOnly || isAdmin);
        if (!items.length) return null;
        return (
          <div key={g.group}>
            <p className="mb-1.5 px-2.5 text-[11px] font-semibold uppercase tracking-wider text-subtle">{g.group}</p>
            <ul className="space-y-0.5">
              {items.map((i) => {
                const active = isActive(path, i.href);
                return (
                  <li key={i.href}>
                    <Link
                      href={i.href}
                      onClick={onNavigate}
                      aria-current={active ? "page" : undefined}
                      className={cx(
                        "flex items-center gap-2.5 rounded-lg px-2.5 py-2 text-sm font-medium transition-colors",
                        active ? "bg-accent-soft text-accent" : "text-muted hover:bg-hover hover:text-ink",
                      )}
                    >
                      <i.icon size={17} aria-hidden />
                      <span className="flex-1">{i.label}</span>
                      {i.href === "/alerts" && unread !== null && unread > 0 && (
                        <span className="rounded-full bg-fail px-1.5 text-[10px] font-semibold leading-[18px] text-white">
                          {unread > 99 ? "99+" : unread}
                        </span>
                      )}
                    </Link>
                  </li>
                );
              })}
            </ul>
          </div>
        );
      })}
    </nav>
  );
}

function TradingStatus({ risk }: { risk: RiskStatus | null }) {
  const { health } = useSession();
  const halted = risk?.kill_switch.active;
  return (
    <Link href="/system" className="block rounded-lg border border-line bg-sunken/60 p-3 text-xs hover:border-line-strong">
      <div className="flex items-center justify-between">
        <span className="text-subtle">Mode</span>
        <span className="font-medium uppercase tracking-wide">{health?.system_mode ?? "—"}</span>
      </div>
      <div className="mt-1.5 flex items-center justify-between">
        <span className="text-subtle">Trading</span>
        {risk === null ? (
          <span className="text-subtle">—</span>
        ) : halted ? (
          <span className="inline-flex items-center gap-1 font-medium text-fail">
            <OctagonPause size={13} aria-hidden /> Halted
          </span>
        ) : (
          <span className="inline-flex items-center gap-1 font-medium text-pass">
            <ShieldCheck size={13} aria-hidden /> Enabled
          </span>
        )}
      </div>
      <div className="mt-1.5 flex items-center justify-between">
        <span className="text-subtle">Live orders</span>
        <span className="font-medium text-muted">Off by design</span>
      </div>
    </Link>
  );
}

function ThemeSwitch() {
  const { pref, setPref } = useTheme();
  const opts: { v: ThemePref; icon: React.ReactNode; label: string }[] = [
    { v: "light", icon: <Sun size={14} />, label: "Light theme" },
    { v: "system", icon: <Monitor size={14} />, label: "Match system theme" },
    { v: "dark", icon: <Moon size={14} />, label: "Dark theme" },
  ];
  return (
    <div role="group" aria-label="Theme" className="inline-flex rounded-lg bg-sunken p-0.5">
      {opts.map((o) => (
        <button
          key={o.v}
          onClick={() => setPref(o.v)}
          aria-pressed={pref === o.v}
          aria-label={o.label}
          title={o.label}
          className={cx("rounded-md p-1.5", pref === o.v ? "bg-panel text-ink shadow-sm" : "text-subtle hover:text-ink")}
        >
          {o.icon}
        </button>
      ))}
    </div>
  );
}

function UserMenu() {
  const { me, signOut } = useSession();
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!open) return;
    const close = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false);
    };
    const esc = (e: KeyboardEvent) => e.key === "Escape" && setOpen(false);
    document.addEventListener("mousedown", close);
    document.addEventListener("keydown", esc);
    return () => {
      document.removeEventListener("mousedown", close);
      document.removeEventListener("keydown", esc);
    };
  }, [open]);
  const initials = (me?.email ?? "?").slice(0, 2).toUpperCase();
  return (
    <div ref={ref} className="relative">
      <button
        onClick={() => setOpen((v) => !v)}
        aria-expanded={open}
        aria-haspopup="menu"
        className="flex items-center gap-2 rounded-lg p-1 pr-2 hover:bg-hover"
      >
        <span className="flex h-8 w-8 items-center justify-center rounded-full bg-accent text-xs font-semibold text-on-accent">{initials}</span>
        <ChevronDown size={14} className="hidden text-subtle sm:block" aria-hidden />
        <span className="sr-only">Account menu</span>
      </button>
      {open && (
        <div role="menu" className="animate-in absolute right-0 z-50 mt-2 w-64 rounded-xl border border-line bg-elevated p-1.5 shadow-[var(--shadow-pop)]">
          <div className="px-3 py-2.5">
            <p className="truncate text-sm font-medium">{me?.email}</p>
            <p className="text-xs capitalize text-muted">{me?.role}</p>
          </div>
          <div className="my-1 border-t border-line" />
          <div className="flex items-center justify-between px-3 py-2 text-sm">
            <span className="text-muted">Theme</span>
            <ThemeSwitch />
          </div>
          <Link role="menuitem" href="/account" onClick={() => setOpen(false)} className="flex items-center gap-2.5 rounded-lg px-3 py-2 text-sm hover:bg-hover">
            <Settings2 size={16} aria-hidden /> Account settings
          </Link>
          <button role="menuitem" onClick={signOut} className="flex w-full items-center gap-2.5 rounded-lg px-3 py-2 text-left text-sm text-fail hover:bg-hover">
            <LogOut size={16} aria-hidden /> Sign out
          </button>
        </div>
      )}
    </div>
  );
}

export function AppShell({ children }: { children: React.ReactNode }) {
  const { token, ready, me, health } = useSession();
  const [drawer, setDrawer] = useState(false);
  const [palette, setPalette] = useState(false);
  const path = usePathname();
  const unread = useUnreadAlerts();
  const risk = useRisk();

  useEffect(() => setDrawer(false), [path]);

  const onKey = useCallback((e: KeyboardEvent) => {
    if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "k") {
      e.preventDefault();
      setPalette((v) => !v);
    }
    if (e.key === "/" && !(e.target instanceof HTMLInputElement) && !(e.target instanceof HTMLTextAreaElement) && !(e.target instanceof HTMLSelectElement)) {
      e.preventDefault();
      setPalette(true);
    }
  }, []);
  useEffect(() => {
    if (!token) return;
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [token, onKey]);

  if (!ready) return <div className="min-h-screen" />;
  if (!token) return <LoginScreen />;
  if (!me) {
    return (
      <div className="flex min-h-screen items-center justify-center" role="status" aria-label="Loading">
        <div className="skeleton h-10 w-10 rounded-full" />
      </div>
    );
  }
  if (me.must_change_password) return <ForcedPasswordScreen />;

  const sidebar = (
    <>
      <div className="flex h-16 items-center px-5">
        <Link href="/" aria-label="Aegis home">
          <Brand />
        </Link>
      </div>
      <SidebarNav unread={unread} onNavigate={() => setDrawer(false)} />
      <div className="space-y-2 border-t border-line p-3">
        <TradingStatus risk={risk} />
        <Link
          href={ACCOUNT_ITEM.href}
          className={cx(
            "flex items-center gap-2.5 rounded-lg px-2.5 py-2 text-sm font-medium",
            isActive(path, ACCOUNT_ITEM.href) ? "bg-accent-soft text-accent" : "text-muted hover:bg-hover hover:text-ink",
          )}
        >
          <Settings2 size={17} aria-hidden /> Account settings
        </Link>
      </div>
    </>
  );

  return (
    <div className="min-h-screen lg:pl-64">
      <a href="#main" className="sr-only focus:not-sr-only focus:fixed focus:left-3 focus:top-3 focus:z-[90] focus:rounded-md focus:bg-panel focus:px-3 focus:py-2">
        Skip to content
      </a>

      <aside className="fixed inset-y-0 left-0 z-30 hidden w-64 flex-col border-r border-line bg-panel lg:flex">{sidebar}</aside>

      {drawer && (
        <div className="fixed inset-0 z-50 lg:hidden">
          <div className="absolute inset-0 bg-black/50" onClick={() => setDrawer(false)} aria-hidden />
          <aside className="animate-in absolute inset-y-0 left-0 flex w-72 max-w-[85vw] flex-col bg-panel shadow-[var(--shadow-pop)]" aria-label="Navigation">
            <button onClick={() => setDrawer(false)} className="absolute right-3 top-4 rounded-md p-1.5 text-subtle hover:bg-hover" aria-label="Close navigation">
              <X size={18} />
            </button>
            {sidebar}
          </aside>
        </div>
      )}

      <header className="sticky top-0 z-20 flex h-16 items-center gap-3 border-b border-line bg-surface/85 px-4 backdrop-blur-md sm:px-6">
        <button onClick={() => setDrawer(true)} className="rounded-md p-2 text-muted hover:bg-hover lg:hidden" aria-label="Open navigation">
          <Menu size={20} />
        </button>
        <button
          onClick={() => setPalette(true)}
          className="flex h-9 w-full max-w-md items-center gap-2 rounded-lg border border-line bg-panel px-3 text-sm text-subtle transition-colors hover:border-line-strong"
        >
          <Search size={16} aria-hidden />
          <span className="flex-1 truncate text-left">Search stocks, pages…</span>
          <kbd className="hidden rounded border border-line px-1.5 text-[10px] sm:inline">⌘K</kbd>
        </button>
        <div className="ml-auto flex items-center gap-1 sm:gap-2">
          {risk?.kill_switch.active && (
            <Link href="/system" className="hidden items-center gap-1.5 rounded-full bg-fail-soft px-2.5 py-1 text-xs font-medium text-fail md:inline-flex">
              <OctagonPause size={13} aria-hidden /> Trading halted
            </Link>
          )}
          <Link href="/alerts" className="relative rounded-lg p-2 text-muted hover:bg-hover hover:text-ink" aria-label={unread ? `Alerts, ${unread} unread` : "Alerts"}>
            <Bell size={19} />
            {unread !== null && unread > 0 && (
              <span className="absolute right-1 top-1 flex h-4 min-w-4 items-center justify-center rounded-full bg-fail px-1 text-[10px] font-semibold text-white">
                {unread > 9 ? "9+" : unread}
              </span>
            )}
          </Link>
          <UserMenu />
        </div>
      </header>

      {health?.demo_data && (
        <div className="flex items-center justify-center gap-2 bg-warn-soft px-4 py-2 text-center text-sm font-semibold text-warn">
          <TriangleAlert size={15} aria-hidden /> Demo data — not for trading
        </div>
      )}
      {health === null && (
        <div className="flex items-center justify-center gap-2 bg-fail-soft px-4 py-2 text-center text-sm text-fail" role="alert">
          <TriangleAlert size={15} aria-hidden /> Can&apos;t reach the Aegis API. Data on this page may be out of date.
        </div>
      )}

      <main id="main" className="mx-auto w-full max-w-[1400px] px-4 py-6 sm:px-6 lg:px-8 lg:py-8">
        {children}
      </main>
      <footer className="mx-auto max-w-[1400px] px-4 pb-8 text-center text-xs text-subtle sm:px-6 lg:px-8">
        Aegis is a research tool, not investment advice. Past results do not predict future results. Live trading is disabled.
      </footer>

      <CommandPalette open={palette} onClose={() => setPalette(false)} />
    </div>
  );
}
