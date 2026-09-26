"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import { Login } from "@/components/Login";
import { Nav } from "@/components/Nav";
import { useSession } from "@/components/useSession";
import { api, type AlertChannels, type AlertOut, type AlertSeverity } from "@/lib/api";

// Severity is never color alone: icon + word + color.
const SEV: Record<AlertSeverity, { cls: string; icon: string; word: string }> = {
  critical: { cls: "border-fail/50 text-fail", icon: "✕", word: "Critical" },
  warning: { cls: "border-unknown/50 text-unknown", icon: "!", word: "Warning" },
  info: { cls: "border-line text-muted", icon: "i", word: "Info" },
};

export default function AlertsPage() {
  const { token, ready, me, health, signIn, signOut, guard } = useSession();
  const [items, setItems] = useState<AlertOut[]>([]);
  const [unread, setUnread] = useState(0);
  const [unreadOnly, setUnreadOnly] = useState(false);
  const [channels, setChannels] = useState<AlertChannels | null>(null);
  const [msg, setMsg] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      const [r, c] = await Promise.all([
        guard((t) => api.alerts(t, unreadOnly, 200)),
        guard((t) => api.alertChannels(t)),
      ]);
      if (r) {
        setItems(r.alerts);
        setUnread(r.unread);
      }
      if (c) setChannels(c);
    } catch (err) {
      setMsg(err instanceof Error ? err.message : "Request failed");
    }
  }, [guard, unreadOnly]);

  useEffect(() => {
    if (token) void load();
  }, [token, load]);

  async function markRead(id?: number) {
    await guard<unknown>((t) => (id === undefined ? api.readAllAlerts(t) : api.readAlert(t, id)));
    window.dispatchEvent(new Event("aegis:alerts-changed"));
    await load();
  }

  if (!ready) return null;
  if (!token) return <Login onToken={signIn} />;

  return (
    <main className="mx-auto max-w-4xl px-4 py-8">
      <Nav mode={health?.system_mode} email={me?.email} role={me?.role} onSignOut={signOut} />
      <div className="mb-4 flex flex-wrap items-end justify-between gap-3">
        <div>
          <h2 className="mb-1 text-2xl font-semibold">Alerts</h2>
          <p className="text-sm text-muted">{unread} unread. Alerts inform; they never trade.</p>
        </div>
        <div className="flex gap-2 text-sm">
          <button className="rounded border border-line px-3 py-1.5" aria-pressed={unreadOnly} onClick={() => setUnreadOnly((v) => !v)}>
            {unreadOnly ? "Show all" : "Unread only"}
          </button>
          <button className="rounded border border-line px-3 py-1.5 disabled:opacity-40" disabled={unread === 0} onClick={() => markRead()}>
            Mark all read
          </button>
        </div>
      </div>
      {msg && <p className="mb-4 text-sm text-fail">{msg}</p>}

      {channels && (
        <p className="mb-4 text-xs text-muted">
          Channels: in-app ✓ ·{" "}
          {(["telegram", "email"] as const).map((k) => (
            <span key={k} title={channels[k].reason ?? undefined} className="mr-2">
              {k} {channels[k].available ? "✓" : "✕ off"}
            </span>
          ))}
          · pushes at {channels.min_severity_to_push} and above
        </p>
      )}

      <ul className="space-y-2">
        {items.map((a) => {
          const s = SEV[a.severity];
          return (
            <li key={a.id} className={`rounded-lg border bg-panel p-4 ${a.read_at ? "border-line opacity-70" : "border-line"}`}>
              <div className="flex flex-wrap items-start justify-between gap-2">
                <div className="flex items-center gap-2">
                  <span className={`inline-flex items-center gap-1 rounded border px-1.5 py-0.5 text-xs ${s.cls}`}>
                    <span aria-hidden>{s.icon}</span>
                    {s.word}
                  </span>
                  <span className="font-semibold">{a.title}</span>
                </div>
                <span className="text-xs text-muted">
                  {a.created_at ? new Date(a.created_at).toLocaleString("en-IN", { timeZone: "Asia/Kolkata" }) : ""}
                </span>
              </div>
              <p className="mt-2 whitespace-pre-line text-sm text-muted">{a.body}</p>
              <div className="mt-2 flex flex-wrap items-center gap-3 text-xs text-muted">
                {a.link && <Link className="underline" href={a.link}>Open</Link>}
                <span>
                  {Object.entries(a.deliveries).map(([k, v]) => `${k}: ${v}`).join(" · ")}
                </span>
                {!a.read_at && (
                  <button className="ml-auto underline" onClick={() => markRead(a.id)}>Mark read</button>
                )}
              </div>
            </li>
          );
        })}
        {items.length === 0 && <li className="text-sm text-muted">No alerts.</li>}
      </ul>
    </main>
  );
}
