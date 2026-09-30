"use client";

import { ArrowRight, Bell, CheckCheck, CheckCircle2, Info, Mail, MessageCircle, Smartphone, TriangleAlert, XCircle } from "lucide-react";
import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import { usePageTitle } from "@/components/usePageTitle";
import { useSession } from "@/components/providers/SessionProvider";
import { useToast } from "@/components/providers/ToastProvider";
import { Badge, Button, Card, EmptyState, LoadingRows, PageHeader, Segmented, cx, type Tone } from "@/components/ui/core";
import { api, type AlertChannels, type AlertOut, type AlertSeverity } from "@/lib/api";
import { ago, istDateTime } from "@/lib/format";

// Severity is never colour alone: icon + word + colour.
const SEV: Record<AlertSeverity, { tone: Tone; icon: React.ReactNode; word: string; bar: string }> = {
  critical: { tone: "fail", icon: <XCircle size={12} aria-hidden />, word: "Critical", bar: "bg-fail" },
  warning: { tone: "warn", icon: <TriangleAlert size={12} aria-hidden />, word: "Warning", bar: "bg-warn" },
  info: { tone: "neutral", icon: <Info size={12} aria-hidden />, word: "Info", bar: "bg-line-strong" },
};

type Filter = "all" | "unread" | "critical";

export default function AlertsPage() {
  usePageTitle("Alerts");
  const { guard } = useSession();
  const toast = useToast();
  const [items, setItems] = useState<AlertOut[] | null>(null);
  const [unread, setUnread] = useState(0);
  const [filter, setFilter] = useState<Filter>("all");
  const [channels, setChannels] = useState<AlertChannels | null>(null);

  const load = useCallback(async () => {
    try {
      const [r, c] = await Promise.all([guard((t) => api.alerts(t, filter === "unread", 200)), guard((t) => api.alertChannels(t))]);
      if (r) {
        setItems(r.alerts);
        setUnread(r.unread);
      }
      if (c) setChannels(c);
    } catch (err) {
      toast({ tone: "error", title: "Could not load alerts", body: err instanceof Error ? err.message : undefined });
    }
  }, [guard, filter, toast]);

  useEffect(() => {
    void load();
  }, [load]);

  async function markRead(id?: number) {
    await guard<unknown>((t) => (id === undefined ? api.readAllAlerts(t) : api.readAlert(t, id)));
    window.dispatchEvent(new Event("aegis:alerts-changed"));
    await load();
  }

  const shown = (items ?? []).filter((a) => filter !== "critical" || a.severity === "critical");

  const channelRow = (icon: React.ReactNode, name: string, ch: { available: boolean; reason: string | null }) => (
    <li className="flex items-start gap-3">
      <span className="mt-0.5 text-subtle">{icon}</span>
      <div className="min-w-0 flex-1">
        <p className="text-sm font-medium">{name}</p>
        {ch.reason && <p className="text-xs text-muted">{ch.reason}</p>}
      </div>
      {ch.available ? (
        <Badge tone="pass" icon={<CheckCircle2 size={12} aria-hidden />}>On</Badge>
      ) : (
        <Badge icon={<XCircle size={12} aria-hidden />}>Off</Badge>
      )}
    </li>
  );

  return (
    <div className="space-y-6">
      <PageHeader
        title="Alerts"
        description="Rankings, thesis events, model health and system changes. Alerts inform; they never trade."
        actions={
          <Button icon={<CheckCheck size={15} />} disabled={unread === 0} onClick={() => markRead()}>
            Mark all read
          </Button>
        }
      />

      <div className="grid gap-6 xl:grid-cols-3">
        <div className="space-y-4 xl:col-span-2">
          <Segmented<Filter>
            label="Filter alerts"
            size="md"
            value={filter}
            onChange={setFilter}
            options={[
              { value: "all", label: "All" },
              { value: "unread", label: `Unread · ${unread}` },
              { value: "critical", label: "Critical" },
            ]}
          />
          {items === null && <LoadingRows rows={5} />}
          {items && shown.length === 0 && (
            <Card>
              <EmptyState icon={<Bell size={20} />} title={filter === "unread" ? "You're all caught up" : "No alerts"} />
            </Card>
          )}
          <ul className="space-y-3">
            {shown.map((a) => {
              const s = SEV[a.severity];
              return (
                <li key={a.id} className={cx("relative overflow-hidden rounded-xl border border-line bg-panel shadow-[var(--shadow-card)]", a.read_at && "opacity-70")}>
                  <span className={cx("absolute inset-y-0 left-0 w-1", s.bar)} aria-hidden />
                  <div className="p-4 pl-5">
                    <div className="flex flex-wrap items-start justify-between gap-2">
                      <div className="flex min-w-0 items-center gap-2">
                        <Badge tone={s.tone} icon={s.icon}>{s.word}</Badge>
                        {!a.read_at && <span className="h-2 w-2 rounded-full bg-accent" aria-label="Unread" />}
                        <h2 className="min-w-0 text-sm font-semibold">{a.title}</h2>
                      </div>
                      <span className="text-xs text-subtle" title={istDateTime(a.created_at)}>{ago(a.created_at)}</span>
                    </div>
                    <p className="mt-2 whitespace-pre-line text-sm text-muted">{a.body}</p>
                    <div className="mt-3 flex flex-wrap items-center gap-3 text-xs">
                      {a.link && (
                        <Link href={a.link} className="-my-3 inline-flex items-center gap-1 py-3 pr-3 font-medium text-accent hover:underline" onClick={() => !a.read_at && void markRead(a.id)}>
                          Open <ArrowRight size={12} />
                        </Link>
                      )}
                      {Object.keys(a.deliveries).length > 0 && (
                        <span className="text-subtle">
                          {Object.entries(a.deliveries).map(([k, v]) => `${k}: ${v}`).join(" · ")}
                        </span>
                      )}
                      {!a.read_at && (
                        <button className="-my-3 ml-auto py-3 pl-4 font-medium text-muted hover:text-ink" onClick={() => markRead(a.id)}>
                          Mark read
                        </button>
                      )}
                    </div>
                  </div>
                </li>
              );
            })}
          </ul>
        </div>

        <Card title="Delivery channels" description={channels ? `Pushes at ${channels.min_severity_to_push} and above.` : undefined}>
          {channels ? (
            <ul className="space-y-4">
              {channelRow(<Smartphone size={16} />, "In-app", { available: true, reason: "Always on" })}
              {channelRow(<MessageCircle size={16} />, "Telegram", channels.telegram)}
              {channelRow(<Mail size={16} />, "Email", channels.email)}
            </ul>
          ) : (
            <LoadingRows rows={3} />
          )}
          <p className="mt-5 border-t border-line pt-4 text-xs text-muted">
            Telegram and email are configured on the server (AEGIS_TELEGRAM_* and AEGIS_SMTP_URL). Secrets never reach the browser.
          </p>
        </Card>
      </div>
    </div>
  );
}
