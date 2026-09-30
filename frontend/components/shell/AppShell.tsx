"use client";

import {
  Bell,
  ChevronDown,
  LayoutDashboard,
  LayoutGrid,
  LineChart,
  LogOut,
  Monitor,
  Moon,
  OctagonPause,
  Search,
  LifeBuoy,
  Settings2,
  ShieldCheck,
  Sun,
  TriangleAlert,
  Trophy,
  Wallet,
} from "lucide-react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { useCallback, useEffect, useRef, useState } from "react";
import { useSession } from "@/components/providers/SessionProvider";
import { useTheme, type ThemePref } from "@/components/providers/ThemeProvider";
import { ForcedPasswordScreen, LoginScreen } from "@/components/shell/AuthScreens";
import { WelcomeGuide } from "@/components/shell/WelcomeGuide";
import { Brand, BrandMark } from "@/components/shell/Brand";
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
    <nav aria-label="Main" className="flex-1 space-y-4 overflow-y-auto px-3 py-3">
      {NAV.map((g) => {
        // Help lives in the sidebar footer next to Account settings.
        const items = g.items.filter((i) => (!i.adminOnly || isAdmin) && i.href !== "/help");
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
                        "flex items-center gap-2.5 rounded-lg px-2.5 py-1.5 text-sm font-medium transition-colors",
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

const TABS = [
  { href: "/", label: "Home", icon: LayoutDashboard },
  { href: "/stocks", label: "Stocks", icon: LineChart },
  { href: "/ranking", label: "Ideas", icon: Trophy },
  { href: "/paper", label: "Paper", icon: Wallet },
];

/** Thumb-reachable navigation for phones and tablets. */
function BottomNav({ onMore, moreOpen, unread }: { onMore: () => void; moreOpen: boolean; unread: number | null }) {
  const path = usePathname();
  const inTabs = TABS.some((t) => isActive(path, t.href));
  return (
    <nav aria-label="Primary" className="pb-safe fixed inset-x-0 bottom-0 z-40 border-t border-line bg-panel/95 backdrop-blur-md lg:hidden">
      <ul className="mx-auto flex max-w-lg">
        {TABS.map((t) => {
          const active = isActive(path, t.href) && !moreOpen;
          return (
            <li key={t.href} className="flex-1">
              <Link
                href={t.href}
                aria-current={active ? "page" : undefined}
                className={cx("flex h-16 flex-col items-center justify-center gap-1 text-[11px] font-medium", active ? "text-accent" : "text-subtle active:text-ink")}
              >
                <t.icon size={22} strokeWidth={active ? 2.3 : 1.9} aria-hidden />
                {t.label}
              </Link>
            </li>
          );
        })}
        <li className="flex-1">
          <button
            onClick={onMore}
            aria-expanded={moreOpen}
            aria-haspopup="dialog"
            className={cx("relative flex h-16 w-full flex-col items-center justify-center gap-1 text-[11px] font-medium", moreOpen || !inTabs ? "text-accent" : "text-subtle")}
          >
            <LayoutGrid size={22} strokeWidth={moreOpen || !inTabs ? 2.3 : 1.9} aria-hidden />
            More
            {unread !== null && unread > 0 && <span className="absolute right-[calc(50%-18px)] top-2.5 h-2 w-2 rounded-full bg-fail" aria-label={`${unread} unread alerts`} />}
          </button>
        </li>
      </ul>
    </nav>
  );
}

function MoreSheet({ open, onClose, unread, risk }: { open: boolean; onClose: () => void; unread: number | null; risk: RiskStatus | null }) {
  const path = usePathname();
  const { isAdmin, me, signOut } = useSession();
  useEffect(() => {
    if (!open) return;
    const esc = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    document.addEventListener("keydown", esc);
    document.body.style.overflow = "hidden";
    return () => {
      document.removeEventListener("keydown", esc);
      document.body.style.overflow = "";
    };
  }, [open, onClose]);
  if (!open) return null;
  const items = [...NAV.flatMap((g) => g.items).filter((i) => !i.adminOnly || isAdmin), ACCOUNT_ITEM];
  return (
    <div className="fixed inset-0 z-30 lg:hidden" role="dialog" aria-modal="true" aria-label="All sections">
      <div className="absolute inset-0 bg-black/40" onClick={onClose} aria-hidden />
      <div className="animate-sheet absolute inset-x-0 bottom-[calc(4rem+env(safe-area-inset-bottom))] max-h-[calc(100dvh-8rem)] overflow-y-auto rounded-t-2xl border-t border-line bg-panel px-4 pb-4 pt-3 shadow-[var(--shadow-pop)]">
        <div className="mx-auto mb-3 h-1 w-10 rounded-full bg-line-strong" aria-hidden />
        <div className="mb-3 flex items-center justify-between">
          <div className="min-w-0">
            <p className="truncate text-sm font-medium">{me?.email}</p>
            <p className="text-xs capitalize text-muted">{me?.role}</p>
          </div>
          <ThemeSwitch />
        </div>
        <ul className="grid grid-cols-3 gap-2">
          {items.map((i) => {
            const active = isActive(path, i.href);
            return (
              <li key={i.href}>
                <Link
                  href={i.href}
                  onClick={onClose}
                  aria-current={active ? "page" : undefined}
                  className={cx(
                    "relative flex h-[76px] flex-col items-center justify-center gap-1.5 rounded-xl border px-1 text-center text-xs font-medium",
                    active ? "border-accent/40 bg-accent-soft text-accent" : "border-line text-muted active:bg-hover",
                  )}
                >
                  <i.icon size={20} aria-hidden />
                  <span className="leading-tight">{i.label}</span>
                  {i.href === "/alerts" && unread !== null && unread > 0 && (
                    <span className="absolute right-2 top-2 rounded-full bg-fail px-1.5 text-[10px] font-semibold leading-4 text-white">{unread > 99 ? "99+" : unread}</span>
                  )}
                </Link>
              </li>
            );
          })}
        </ul>
        <div className="mt-3">
          <TradingStatus risk={risk} />
        </div>
        <button onClick={signOut} className="mt-3 flex h-11 w-full items-center justify-center gap-2 rounded-lg border border-line text-sm font-medium text-fail active:bg-hover">
          <LogOut size={16} aria-hidden /> Sign out
        </button>
      </div>
    </div>
  );
}

export function AppShell({ children }: { children: React.ReactNode }) {
  const { token, ready, me, health } = useSession();
  const [palette, setPalette] = useState(false);
  const [more, setMore] = useState(false);
  const path = usePathname();
  const unread = useUnreadAlerts();
  const risk = useRisk();

  useEffect(() => {
    setMore(false);
  }, [path]);

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
  // Legal pages are readable before signing in.
  if (!token && path.startsWith("/legal")) {
    return (
      <div className="min-h-screen">
        <header className="pt-safe border-b border-line bg-panel">
          <div className="mx-auto flex h-14 max-w-3xl items-center justify-between px-4">
            <Link href="/" aria-label="Aegis sign in">
              <Brand />
            </Link>
            <Link href="/" className="text-sm font-medium text-accent">
              Sign in
            </Link>
          </div>
        </header>
        <main id="main" className="pb-safe mx-auto max-w-3xl px-4 py-8">
          {children}
        </main>
      </div>
    );
  }
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
      <SidebarNav unread={unread} />
      <div className="space-y-2 border-t border-line p-3">
        <TradingStatus risk={risk} />
        <div className="flex gap-1">
          <Link
            href={ACCOUNT_ITEM.href}
            className={cx(
              "flex flex-1 items-center gap-2.5 rounded-lg px-2.5 py-2 text-sm font-medium",
              isActive(path, ACCOUNT_ITEM.href) ? "bg-accent-soft text-accent" : "text-muted hover:bg-hover hover:text-ink",
            )}
          >
            <Settings2 size={17} aria-hidden /> Account
          </Link>
          <Link
            href="/help"
            className={cx(
              "flex items-center gap-2 rounded-lg px-2.5 py-2 text-sm font-medium",
              isActive(path, "/help") ? "bg-accent-soft text-accent" : "text-muted hover:bg-hover hover:text-ink",
            )}
          >
            <LifeBuoy size={17} aria-hidden /> Help
          </Link>
        </div>
      </div>
    </>
  );

  return (
    <div className="min-h-screen lg:pl-64">
      <a href="#main" className="sr-only focus:not-sr-only focus:fixed focus:left-3 focus:top-3 focus:z-[90] focus:rounded-md focus:bg-panel focus:px-3 focus:py-2">
        Skip to content
      </a>

      <aside className="fixed inset-y-0 left-0 z-30 hidden w-64 flex-col border-r border-line bg-panel lg:flex">{sidebar}</aside>

      <header className="pt-safe sticky top-0 z-20 border-b border-line bg-surface/85 backdrop-blur-md">
        <div className="flex h-14 items-center gap-2 px-3 sm:h-16 sm:gap-3 sm:px-6">
        <Link href="/" aria-label="Aegis home" className="shrink-0 p-1 lg:hidden">
          <BrandMark size={28} />
        </Link>
        <button
          onClick={() => setPalette(true)}
          className="flex h-10 w-full max-w-md items-center gap-2 rounded-lg border border-line bg-panel px-3 text-sm text-subtle transition-colors hover:border-line-strong sm:h-9"
        >
          <Search size={16} aria-hidden />
          <span className="flex-1 truncate text-left"><span className="sm:hidden">Search</span><span className="hidden sm:inline">Search stocks, pages…</span></span>
          <kbd className="hidden rounded border border-line px-1.5 text-[10px] lg:inline">⌘K</kbd>
        </button>
        <div className="ml-auto flex items-center gap-0.5 sm:gap-2">
          {risk?.kill_switch.active && (
            <Link href="/system" aria-label="Trading halted" className="inline-flex h-10 items-center gap-1.5 rounded-full bg-fail-soft px-2.5 text-xs font-medium text-fail sm:h-auto sm:py-1">
              <OctagonPause size={15} aria-hidden /> <span className="hidden md:inline">Trading halted</span>
            </Link>
          )}
          <Link href="/alerts" className="relative flex h-11 w-11 items-center justify-center rounded-lg text-muted hover:bg-hover hover:text-ink sm:h-auto sm:w-auto sm:p-2" aria-label={unread ? `Alerts, ${unread} unread` : "Alerts"}>
            <Bell size={19} />
            {unread !== null && unread > 0 && (
              <span className="absolute right-1 top-1 flex h-4 min-w-4 items-center justify-center rounded-full bg-fail px-1 text-[10px] font-semibold text-white">
                {unread > 9 ? "9+" : unread}
              </span>
            )}
          </Link>
          <div className="hidden lg:block">
            <UserMenu />
          </div>
          <Link href="/account" aria-label="Account settings" className="flex h-11 w-11 items-center justify-center lg:hidden">
            <span className="flex h-8 w-8 items-center justify-center rounded-full bg-accent text-xs font-semibold text-on-accent">{(me.email ?? "?").slice(0, 2).toUpperCase()}</span>
          </Link>
        </div>
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

      <main id="main" className="mx-auto w-full min-w-0 max-w-[1400px] px-4 py-5 sm:px-6 sm:py-6 lg:px-8 lg:py-8">
        {children}
      </main>
      <footer className="mx-auto max-w-[1400px] px-4 pb-[calc(5.5rem+env(safe-area-inset-bottom))] text-center text-xs text-subtle sm:px-6 lg:px-8 lg:pb-8">
        <p>Aegis is a research tool, not investment advice. Past results do not predict future results. Live trading is disabled.</p>
        <nav aria-label="Footer" className="mt-2 flex flex-wrap justify-center gap-x-2">
          <Link href="/help" className="inline-block px-1.5 py-3 hover:text-ink">Help</Link>
          <Link href="/legal#disclaimer" className="inline-block px-1.5 py-3 hover:text-ink">Risk disclaimer</Link>
          <Link href="/legal#terms" className="inline-block px-1.5 py-3 hover:text-ink">Terms</Link>
          <Link href="/legal#privacy" className="inline-block px-1.5 py-3 hover:text-ink">Privacy</Link>
        </nav>
      </footer>
      <WelcomeGuide />

      <MoreSheet open={more} onClose={() => setMore(false)} unread={unread} risk={risk} />
      <BottomNav onMore={() => setMore((v) => !v)} moreOpen={more} unread={unread} />
      <CommandPalette open={palette} onClose={() => setPalette(false)} />
    </div>
  );
}
