"use client";

import { BellPlus, BellRing, Pause, Play, RefreshCw, Trash2 } from "lucide-react";
import { useCallback, useEffect, useState } from "react";
import { useSession } from "@/components/providers/SessionProvider";
import { useToast } from "@/components/providers/ToastProvider";
import { Dialog } from "@/components/ui/Dialog";
import { Badge, Button, EmptyState, Field, IconButton, Input, LoadingRows, Select, cx } from "@/components/ui/core";
import { api, ApiError, type PriceAlertRule, type PriceCondition, type StockSummary } from "@/lib/api";
import { ago, istDate, istDateTime } from "@/lib/format";

export const CONDITIONS: { value: PriceCondition; label: string; unit: string; hint: string }[] = [
  { value: "price_above", label: "Closes above a price", unit: "₹", hint: "Rupees, e.g. 3500" },
  { value: "price_below", label: "Closes below a price", unit: "₹", hint: "Rupees, e.g. 3200" },
  { value: "day_change_up", label: "Rises in a day by", unit: "%", hint: "Percent, e.g. 3 for +3%" },
  { value: "day_change_down", label: "Falls in a day by", unit: "%", hint: "Percent, e.g. 3 for −3%" },
  { value: "rsi_above", label: "RSI(14) goes above", unit: "RSI", hint: "0–100, e.g. 70 (overbought)" },
  { value: "rsi_below", label: "RSI(14) goes below", unit: "RSI", hint: "0–100, e.g. 30 (oversold)" },
];

const CHANGED = "aegis:price-alerts-changed";
const errMsg = (err: unknown) => (err instanceof ApiError ? err.message : undefined);

export function usePriceAlerts(ticker?: string) {
  const { guard, token } = useSession();
  const [rules, setRules] = useState<PriceAlertRule[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const load = useCallback(async () => {
    try {
      const r = await guard((t) => api.priceAlerts(t, ticker));
      if (r) setRules(r);
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not load price alerts");
    }
  }, [guard, ticker]);
  useEffect(() => {
    if (!token) return;
    void load();
    window.addEventListener(CHANGED, load);
    return () => window.removeEventListener(CHANGED, load);
  }, [token, load]);
  return { rules, error, reload: load };
}

export function NewPriceAlertDialog({
  open,
  onClose,
  ticker,
  stocks,
  lastClose,
}: {
  open: boolean;
  onClose: () => void;
  ticker?: string;
  stocks?: StockSummary[] | null;
  lastClose?: number | null;
}) {
  const { guard } = useSession();
  const toast = useToast();
  const [tk, setTk] = useState(ticker ?? "");
  const [condition, setCondition] = useState<PriceCondition>("price_above");
  const [threshold, setThreshold] = useState("");
  const [note, setNote] = useState("");
  const [repeat, setRepeat] = useState(false);
  const [high, setHigh] = useState(false);
  const [busy, setBusy] = useState(false);
  const meta = CONDITIONS.find((c) => c.value === condition)!;

  useEffect(() => {
    if (open) {
      setTk(ticker ?? "");
      setThreshold("");
      setNote("");
    }
  }, [open, ticker]);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    const n = Number(threshold);
    if (!tk.trim() || !(n > 0)) return;
    setBusy(true);
    try {
      await guard((t) =>
        api.createPriceAlert(t, {
          ticker: tk.trim().toUpperCase(),
          condition,
          threshold: n,
          note: note.trim() || null,
          repeat,
          importance: high ? "high" : "normal",
        }),
      );
      toast({ tone: "success", title: "Price alert saved", body: "Checked after each end-of-day price update." });
      window.dispatchEvent(new Event(CHANGED));
      onClose();
    } catch (err) {
      toast({ tone: "error", title: "Alert not saved", body: errMsg(err) });
    } finally {
      setBusy(false);
    }
  }

  return (
    <Dialog
      open={open}
      onClose={onClose}
      title="New price alert"
      description="Aegis checks each new daily close and tells you when your rule is met. Alerts inform only; they never place orders."
      footer={
        <>
          <Button onClick={onClose} disabled={busy}>
            Cancel
          </Button>
          <Button variant="primary" type="submit" form="price-alert-form" loading={busy} icon={<BellPlus size={15} />} disabled={!tk.trim() || !(Number(threshold) > 0)}>
            Save alert
          </Button>
        </>
      }
    >
      <form id="price-alert-form" onSubmit={submit} className="grid gap-4 sm:grid-cols-2">
        <Field label="Stock" className="sm:col-span-2">
          {(id) =>
            ticker ? (
              <Input id={id} value={ticker} readOnly className="font-mono" />
            ) : (
              <>
                <Input id={id} list="pa-stocks" value={tk} onChange={(e) => setTk(e.target.value)} placeholder="e.g. TCS.NS" className="font-mono uppercase" required />
                <datalist id="pa-stocks">
                  {(stocks ?? []).map((s) => (
                    <option key={s.ticker} value={s.ticker}>
                      {s.name ?? ""}
                    </option>
                  ))}
                </datalist>
              </>
            )
          }
        </Field>
        <Field label="When the stock…">
          {(id) => (
            <Select id={id} value={condition} onChange={(e) => setCondition(e.target.value as PriceCondition)}>
              {CONDITIONS.map((c) => (
                <option key={c.value} value={c.value}>
                  {c.label}
                </option>
              ))}
            </Select>
          )}
        </Field>
        <Field
          label={`Level (${meta.unit})`}
          hint={condition.startsWith("price") && lastClose ? `${meta.hint}. Last close ₹${lastClose.toLocaleString("en-IN")}` : meta.hint}
        >
          {(id) => (
            <Input id={id} type="number" inputMode="decimal" min="0" step="any" value={threshold} onChange={(e) => setThreshold(e.target.value)} required className="font-mono" />
          )}
        </Field>
        <Field label="Note to self (optional)" className="sm:col-span-2">
          {(id) => <Input id={id} value={note} onChange={(e) => setNote(e.target.value)} maxLength={200} placeholder="e.g. revisit the thesis" />}
        </Field>
        <label className="flex items-start gap-3 text-sm sm:col-span-2">
          <input type="checkbox" checked={repeat} onChange={(e) => setRepeat(e.target.checked)} className="mt-0.5 h-5 w-5 accent-[var(--color-accent)] sm:h-4 sm:w-4" />
          <span>
            <span className="font-medium">Keep watching after it fires</span>
            <span className="block text-xs text-muted">Fires again only after the condition has cleared. Off = one-shot.</span>
          </span>
        </label>
        <label className="flex items-start gap-3 text-sm sm:col-span-2">
          <input type="checkbox" checked={high} onChange={(e) => setHigh(e.target.checked)} className="mt-0.5 h-5 w-5 accent-[var(--color-accent)] sm:h-4 sm:w-4" />
          <span>
            <span className="font-medium">High importance</span>
            <span className="block text-xs text-muted">Also pushed to Telegram / email when those channels are set up for the team.</span>
          </span>
        </label>
      </form>
    </Dialog>
  );
}

function statusBadge(r: PriceAlertRule) {
  if (!r.is_active) return <Badge>{r.trigger_count > 0 ? "Fired · off" : "Paused"}</Badge>;
  if (r.last_status?.startsWith("not checked")) return <Badge tone="warn">Waiting for fresh data</Badge>;
  if (!r.armed) return <Badge tone="info">Fired · re-arms when it clears</Badge>;
  return <Badge tone="pass">Watching</Badge>;
}

export function PriceAlertList({ ticker, compact }: { ticker?: string; compact?: boolean }) {
  const { guard } = useSession();
  const toast = useToast();
  const { rules, error } = usePriceAlerts(ticker);
  const [busy, setBusy] = useState<number | null>(null);

  async function act(id: number, fn: (t: string) => Promise<unknown>, ok: string) {
    setBusy(id);
    try {
      await guard(fn);
      toast({ tone: "success", title: ok });
      window.dispatchEvent(new Event(CHANGED));
    } catch (err) {
      toast({ tone: "error", title: "Not updated", body: errMsg(err) });
    } finally {
      setBusy(null);
    }
  }

  if (error) return <p className="text-sm text-fail">{error}</p>;
  if (rules === null) return <LoadingRows rows={compact ? 2 : 4} />;
  if (rules.length === 0)
    return (
      <EmptyState
        icon={<BellRing size={20} />}
        title="No price alerts yet"
        body={ticker ? "Get told when this stock crosses a level, moves sharply, or its RSI hits an extreme." : "Set one here or from any stock's page."}
        compact
      />
    );
  return (
    <ul className="divide-y divide-line">
      {rules.map((r) => (
        <li key={r.id} className={cx("flex items-start gap-3 py-3", !r.is_active && "opacity-70")}>
          <div className="min-w-0 flex-1">
            <p className="text-sm">
              {!ticker && <span className="mr-1.5 font-mono font-semibold">{r.ticker}</span>}
              {r.description}
              {r.importance === "high" && <span className="ml-1.5 text-xs text-warn">· high</span>}
            </p>
            <div className="mt-1 flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-muted">
              {statusBadge(r)}
              {r.last_value !== null && r.last_session && (
                <span title={r.last_checked_at ? `Checked ${istDateTime(r.last_checked_at)}` : undefined}>
                  Last: {r.condition.startsWith("price") ? `₹${r.last_value.toLocaleString("en-IN", { maximumFractionDigits: 2 })}` : r.condition.startsWith("day") ? `${r.last_value > 0 ? "+" : ""}${r.last_value.toFixed(2)}%` : r.last_value.toFixed(1)} on {istDate(r.last_session)}
                </span>
              )}
              {r.last_triggered_at && <span>Fired {ago(r.last_triggered_at)}{r.trigger_count > 1 ? ` · ${r.trigger_count}×` : ""}</span>}
              {r.last_status?.startsWith("not checked") && <span className="basis-full text-subtle">{r.last_status}</span>}
              {r.note && <span className="basis-full italic">“{r.note}”</span>}
            </div>
          </div>
          <IconButton
            label={r.is_active ? "Pause alert" : "Turn alert back on"}
            disabled={busy === r.id}
            onClick={() => act(r.id, (t) => api.updatePriceAlert(t, r.id, { is_active: !r.is_active }), r.is_active ? "Alert paused" : "Alert back on")}
          >
            {r.is_active ? <Pause size={15} /> : <Play size={15} />}
          </IconButton>
          <IconButton label="Delete alert" disabled={busy === r.id} onClick={() => act(r.id, (t) => api.deletePriceAlert(t, r.id), "Alert deleted")}>
            <Trash2 size={15} />
          </IconButton>
        </li>
      ))}
    </ul>
  );
}

export function CheckNowButton() {
  const { guard } = useSession();
  const toast = useToast();
  const [busy, setBusy] = useState(false);
  return (
    <Button
      icon={<RefreshCw size={15} />}
      loading={busy}
      onClick={async () => {
        setBusy(true);
        try {
          const r = await guard((t) => api.checkPriceAlerts(t));
          if (r)
            toast({
              tone: r.fired ? "success" : "info",
              title: r.fired ? `${r.fired} alert${r.fired > 1 ? "s" : ""} fired` : "Nothing new",
              body: `Checked ${r.checked} active rule${r.checked === 1 ? "" : "s"} against the latest stored close.`,
            });
          window.dispatchEvent(new Event(CHANGED));
          window.dispatchEvent(new Event("aegis:alerts-changed"));
        } catch (err) {
          toast({ tone: "error", title: "Check failed", body: errMsg(err) });
        } finally {
          setBusy(false);
        }
      }}
    >
      Check now
    </Button>
  );
}
