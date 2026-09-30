"use client";

import { Download, KeyRound, LogOut, Monitor, Moon, ShieldAlert, ShieldCheck, Sun, UserRound, XCircle } from "lucide-react";
import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import { ChangePasswordForm } from "@/components/shell/AuthScreens";
import { usePageTitle } from "@/components/usePageTitle";
import { useSession } from "@/components/providers/SessionProvider";
import { useTheme, type ThemePref } from "@/components/providers/ThemeProvider";
import { useToast } from "@/components/providers/ToastProvider";
import { ConfirmDialog } from "@/components/ui/Dialog";
import { Badge, Button, Card, KeyValues, LoadingRows, PageHeader, cx } from "@/components/ui/core";
import { api, ApiError, type ExportKind, type SignInItem } from "@/lib/api";
import { ago, istDateTime } from "@/lib/format";

/** A short, human label for a browser user-agent string. */
function device(agent: string | null): string {
  if (!agent) return "Unknown device";
  if (/python|curl|httpx|okhttp/i.test(agent)) return "Script or API client";
  const os = /iPhone|iPad/.test(agent) ? "iPhone/iPad" : /Android/.test(agent) ? "Android" : /Mac OS X/.test(agent) ? "Mac" : /Windows/.test(agent) ? "Windows" : /Linux/.test(agent) ? "Linux" : "Other";
  const br = /Edg\//.test(agent) ? "Edge" : /Chrome\//.test(agent) ? "Chrome" : /Firefox\//.test(agent) ? "Firefox" : /Safari\//.test(agent) ? "Safari" : /python|curl|httpx|okhttp/i.test(agent) ? "Script" : "Browser";
  return `${br} on ${os}`;
}

const ACTION_LABEL: Record<string, string> = {
  "auth.login": "Signed in",
  "auth.login_failed": "Failed sign-in attempt",
  "auth.logout_all": "Signed out everywhere",
  "user.change_password": "Password changed",
};

function SecurityCard() {
  const { guard, token, signIn } = useSession();
  const toast = useToast();
  const [items, setItems] = useState<SignInItem[] | null>(null);
  const [failed, setFailed] = useState(0);
  const [confirm, setConfirm] = useState(false);
  const [busy, setBusy] = useState(false);
  const load = useCallback(async () => {
    try {
      const r = await guard((t) => api.signIns(t));
      if (r) {
        setItems(r.items);
        setFailed(r.failed_recent);
      }
    } catch {
      setItems([]);
    }
  }, [guard]);
  useEffect(() => {
    if (token) void load();
  }, [token, load]);

  return (
    <Card
      title={<span className="flex items-center gap-2"><ShieldCheck size={15} aria-hidden /> Sign-in activity</span>}
      description="Your recent sign-ins and any failed attempts on your email."
      actions={
        <Button variant="danger" size="sm" icon={<LogOut size={14} />} onClick={() => setConfirm(true)}>
          Sign out everywhere
        </Button>
      }
    >
      {failed > 0 && (
        <p className="mb-3 flex items-center gap-2 rounded-lg bg-warn-soft px-3 py-2 text-xs text-warn">
          <ShieldAlert size={14} aria-hidden /> {failed} failed attempt{failed > 1 ? "s" : ""} in this list. If that wasn&apos;t you, change your password.
        </p>
      )}
      {items === null ? (
        <LoadingRows rows={3} />
      ) : items.length === 0 ? (
        <p className="text-sm text-muted">No sign-ins recorded yet.</p>
      ) : (
        <ul className="divide-y divide-line">
          {items.slice(0, 10).map((i) => (
            <li key={i.id} className="flex items-center gap-3 py-2.5 text-sm">
              {i.action === "auth.login_failed" ? <XCircle size={15} className="shrink-0 text-fail" aria-hidden /> : <ShieldCheck size={15} className="shrink-0 text-pass" aria-hidden />}
              <div className="min-w-0 flex-1">
                <p className="truncate">{ACTION_LABEL[i.action] ?? i.action}{i.action.startsWith("auth.login") && ` · ${device(i.agent)}`}</p>
                <p className="text-xs text-muted">{i.client ? `IP ${i.client} · ` : ""}{istDateTime(i.occurred_at)}</p>
              </div>
              <span className="shrink-0 text-xs text-subtle">{ago(i.occurred_at)}</span>
            </li>
          ))}
        </ul>
      )}
      <p className="mt-3 text-xs text-subtle">
        Full history: <Link href="/activity" className="-my-3 inline-block py-3 text-accent hover:underline">Activity log</Link>
      </p>
      <ConfirmDialog
        open={confirm}
        onClose={() => setConfirm(false)}
        title="Sign out on every device?"
        body="Every session for your account ends now, including other phones and browsers. This device stays signed in."
        confirmLabel="Sign out everywhere"
        tone="danger"
        busy={busy}
        onConfirm={async () => {
          setBusy(true);
          try {
            const r = await guard((t) => api.logoutEverywhere(t));
            if (r) signIn(r.access_token);
            toast({ tone: "success", title: "Signed out everywhere else" });
            setConfirm(false);
            void load();
          } catch (err) {
            toast({ tone: "error", title: "Could not sign out other sessions", body: err instanceof ApiError ? err.message : undefined });
          } finally {
            setBusy(false);
          }
        }}
      />
    </Card>
  );
}

const EXPORTS: { kind: ExportKind; label: string; hint: string }[] = [
  { kind: "watchlist", label: "Watchlist", hint: "Your first list" },
  { kind: "journal", label: "Journal", hint: "Notes and trade journal" },
  { kind: "price-alerts", label: "Price alerts", hint: "Your rules and their status" },
  { kind: "activity", label: "Activity", hint: "Your audit trail" },
];

function ExportsCard() {
  const { guard } = useSession();
  const toast = useToast();
  const [busy, setBusy] = useState<ExportKind | null>(null);
  return (
    <Card title={<span className="flex items-center gap-2"><Download size={15} aria-hidden /> Your data</span>} description="Download CSV files that open in Excel or Google Sheets. Paper-trading exports are on the Paper trading page.">
      <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
        {EXPORTS.map((x) => (
          <button
            key={x.kind}
            type="button"
            disabled={busy === x.kind}
            onClick={async () => {
              setBusy(x.kind);
              try {
                await guard((t) => api.exportCsv(t, x.kind));
              } catch (err) {
                toast({ tone: "error", title: "Export failed", body: err instanceof ApiError ? err.message : undefined });
              } finally {
                setBusy(null);
              }
            }}
            className="flex flex-col items-start gap-1 rounded-xl border border-line p-3.5 text-left transition-colors hover:bg-hover disabled:opacity-50"
          >
            <span className="flex items-center gap-1.5 text-sm font-medium"><Download size={14} aria-hidden /> {x.label}</span>
            <span className="text-xs text-muted">{x.hint}</span>
          </button>
        ))}
      </div>
    </Card>
  );
}

const THEMES: { v: ThemePref; label: string; icon: React.ReactNode; hint: string }[] = [
  { v: "light", label: "Light", icon: <Sun size={18} />, hint: "Bright and crisp" },
  { v: "dark", label: "Dark", icon: <Moon size={18} />, hint: "Easy on the eyes" },
  { v: "system", label: "System", icon: <Monitor size={18} />, hint: "Follows your device" },
];

export default function AccountPage() {
  usePageTitle("Account settings");
  const { me, signOut } = useSession();
  const { pref, setPref } = useTheme();
  const toast = useToast();

  return (
    <div className="space-y-6">
      <PageHeader title="Account settings" description="Your profile, password, security and display preferences." />

      <div className="grid gap-6 xl:grid-cols-3">
        <Card title={<span className="flex items-center gap-2"><UserRound size={15} aria-hidden /> Profile</span>}>
          <div className="mb-5 flex items-center gap-3">
            <span className="flex h-12 w-12 items-center justify-center rounded-full bg-accent text-base font-semibold text-on-accent">{(me?.email ?? "?").slice(0, 2).toUpperCase()}</span>
            <div className="min-w-0">
              <p className="truncate font-medium">{me?.email}</p>
              <Badge tone="info" className="mt-1 capitalize">{me?.role}</Badge>
            </div>
          </div>
          <KeyValues
            items={[
              ["Member since", istDateTime(me?.created_at)],
              ["Last sign-in", istDateTime(me?.last_login_at)],
            ]}
          />
          <Button className="mt-6 w-full" variant="secondary" icon={<LogOut size={15} />} onClick={signOut}>Sign out</Button>
          <p className="mt-4 text-center text-xs text-subtle sm:hidden">Tip: add Aegis to your home screen from your browser&apos;s Share or ⋮ menu for a full-screen app.</p>
        </Card>

        <Card className="xl:col-span-2" title={<span className="flex items-center gap-2"><KeyRound size={15} aria-hidden /> Change password</span>} description="Use at least 12 characters.">
          <div className="max-w-md">
            <ChangePasswordForm onDone={() => toast({ tone: "success", title: "Password updated", body: "Other sessions were signed out." })} />
          </div>
        </Card>
      </div>

      <SecurityCard />

      <Card title="Appearance" description="Saved on this device.">
        <div role="radiogroup" aria-label="Theme" className="grid gap-3 sm:grid-cols-3">
          {THEMES.map((t) => (
            <button
              key={t.v}
              role="radio"
              aria-checked={pref === t.v}
              onClick={() => setPref(t.v)}
              className={cx(
                "flex items-center gap-3 rounded-xl border p-4 text-left transition-colors",
                pref === t.v ? "border-accent bg-accent-soft" : "border-line hover:bg-hover",
              )}
            >
              <span className={cx("flex h-10 w-10 items-center justify-center rounded-lg", pref === t.v ? "bg-accent text-on-accent" : "bg-sunken text-muted")}>{t.icon}</span>
              <span>
                <span className="block text-sm font-medium">{t.label}</span>
                <span className="block text-xs text-muted">{t.hint}</span>
              </span>
            </button>
          ))}
        </div>
      </Card>

      <ExportsCard />

      <Card title="Keyboard shortcuts" className="hidden sm:block">
        <ul className="grid gap-3 text-sm sm:grid-cols-2">
          {[
            ["⌘ K  or  Ctrl K", "Search stocks and pages"],
            ["/", "Open search"],
            ["Esc", "Close dialogs and search"],
            ["↑ ↓  Enter", "Move and choose in search"],
          ].map(([k, v]) => (
            <li key={k} className="flex items-center justify-between gap-3 rounded-lg bg-sunken px-3 py-2">
              <span className="text-muted">{v}</span>
              <kbd className="rounded border border-line bg-panel px-2 py-0.5 font-mono text-xs">{k}</kbd>
            </li>
          ))}
        </ul>
      </Card>
    </div>
  );
}
