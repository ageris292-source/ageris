"use client";

import { KeyRound, LogOut, Monitor, Moon, Sun, UserRound } from "lucide-react";
import { ChangePasswordForm } from "@/components/shell/AuthScreens";
import { usePageTitle } from "@/components/usePageTitle";
import { useSession } from "@/components/providers/SessionProvider";
import { useTheme, type ThemePref } from "@/components/providers/ThemeProvider";
import { useToast } from "@/components/providers/ToastProvider";
import { Badge, Button, Card, KeyValues, PageHeader, cx } from "@/components/ui/core";
import { istDateTime } from "@/lib/format";

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
      <PageHeader title="Account settings" description="Your profile, password and display preferences." />

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
        </Card>

        <Card className="xl:col-span-2" title={<span className="flex items-center gap-2"><KeyRound size={15} aria-hidden /> Change password</span>} description="Use at least 12 characters.">
          <div className="max-w-md">
            <ChangePasswordForm onDone={() => toast({ tone: "success", title: "Password updated", body: "Other sessions were signed out." })} />
          </div>
        </Card>
      </div>

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

      <Card title="Keyboard shortcuts">
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
