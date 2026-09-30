"use client";

import {
  CalendarClock,
  CheckCircle2,
  Cpu,
  Database,
  OctagonPause,
  Play,
  Plus,
  RefreshCw,
  Server,
  ShieldOff,
  XCircle,
} from "lucide-react";
import { useCallback, useEffect, useState } from "react";
import { usePageTitle } from "@/components/usePageTitle";
import { useSession } from "@/components/providers/SessionProvider";
import { useToast } from "@/components/providers/ToastProvider";
import { Dialog } from "@/components/ui/Dialog";
import { GateBadge } from "@/components/ui/Status";
import {
  Badge,
  Button,
  Card,
  DesktopOnly,
  Field,
  Input,
  KeyValues,
  LoadingRows,
  MobileItem,
  MobileList,
  PageHeader,
  Table,
  Td,
  Th,
  cx,
} from "@/components/ui/core";
import { api, ApiError, type LiveStatus, type MacroRow, type ProviderInfo, type RiskStatus } from "@/lib/api";
import { humanize, istDateTime } from "@/lib/format";

function Flag({ ok, yes, no }: { ok: boolean | null | undefined; yes: string; no: string }) {
  if (ok === null || ok === undefined) return <GateBadge s="UNKNOWN" />;
  return ok ? <Badge tone="pass" icon={<CheckCircle2 size={12} aria-hidden />}>{yes}</Badge> : <Badge icon={<XCircle size={12} aria-hidden />}>{no}</Badge>;
}

const todayIst = () => new Date(Date.now() + 5.5 * 3600_000).toISOString().slice(0, 10);

const JOBS = [
  ["17:30", "Macro and market series"],
  ["19:10", "Licensed NSE prices & corporate actions (Mac feeder)"],
  ["19:30", "Paper portfolios marked, theses checked"],
  ["19:45", "Daily ranking through the 24 gates"],
  ["20:00", "Model monitoring (drift, calibration decay)"],
  ["Every 2 h", "News headlines"],
  ["Saturday", "Fundamentals"],
  ["Sunday", "Walk-forward retrain (candidates only)"],
];

function KillSwitch({ risk, onChange }: { risk: RiskStatus; onChange: () => void }) {
  const { guard, isAdmin } = useSession();
  const toast = useToast();
  const [open, setOpen] = useState<null | "halt" | "resume">(null);
  const [reason, setReason] = useState("");
  const [busy, setBusy] = useState(false);
  const active = risk.kill_switch.active;

  async function submit() {
    setBusy(true);
    try {
      await guard((t) => api.setKillSwitch(t, open === "halt", reason.trim()));
      toast({ tone: open === "halt" ? "warning" : "success", title: open === "halt" ? "Trading halted" : "Halt cleared" });
      setOpen(null);
      setReason("");
      window.dispatchEvent(new Event("aegis:risk-changed"));
      window.dispatchEvent(new Event("aegis:alerts-changed"));
      onChange();
    } catch (err) {
      toast({ tone: "error", title: "Kill switch not changed", body: err instanceof ApiError ? err.message : undefined });
    } finally {
      setBusy(false);
    }
  }

  return (
    <Card title="Kill switch" description="Stops every order immediately. Anyone can halt; only an admin can resume.">
      <div className={cx("flex items-center gap-3 rounded-lg p-4", active ? "bg-fail-soft" : "bg-pass-soft")}>
        {active ? <OctagonPause size={24} className="text-fail" aria-hidden /> : <CheckCircle2 size={24} className="text-pass" aria-hidden />}
        <div className="min-w-0">
          <p className={cx("font-semibold", active ? "text-fail" : "text-pass")}>{active ? "Active — all trading halted" : "Inactive — trading allowed"}</p>
          <p className="text-xs text-muted">{risk.kill_switch.reason}</p>
        </div>
      </div>
      <div className="mt-4 flex flex-wrap gap-2">
        {!active && <Button variant="danger" icon={<OctagonPause size={15} />} onClick={() => setOpen("halt")} className="w-full sm:w-auto">Halt trading</Button>}
        {active && isAdmin && <Button variant="primary" icon={<Play size={15} />} onClick={() => setOpen("resume")} className="w-full sm:w-auto">Resume trading</Button>}
        {active && !isAdmin && <p className="text-xs text-muted">Only an admin can resume after reviewing.</p>}
      </div>
      <p className="mt-3 text-xs text-subtle">Resuming only clears the halt. It never enables live trading.</p>

      <Dialog
        open={open !== null}
        onClose={() => !busy && setOpen(null)}
        title={open === "halt" ? "Halt all trading?" : "Resume trading?"}
        description={open === "halt" ? "Every order will be refused until an admin resumes. The reason is recorded in the audit log." : "Paper orders will be accepted again if every other readiness check passes."}
        size="sm"
        footer={
          <>
            <Button onClick={() => setOpen(null)} disabled={busy}>Cancel</Button>
            <Button variant={open === "halt" ? "danger" : "primary"} loading={busy} disabled={reason.trim().length < 5} onClick={submit}>
              {open === "halt" ? "Halt trading" : "Resume trading"}
            </Button>
          </>
        }
      >
        <Field label="Reason" hint="At least 5 characters.">
          {(id) => <Input id={id} value={reason} onChange={(e) => setReason(e.target.value)} placeholder={open === "halt" ? "e.g. Unexpected data gap in prices" : "e.g. Reviewed data, all clear"} />}
        </Field>
      </Dialog>
    </Card>
  );
}

export default function SystemPage() {
  usePageTitle("System");
  const { guard, isAdmin, health, refreshHealth } = useSession();
  const toast = useToast();
  const [risk, setRisk] = useState<RiskStatus | null>(null);
  const [providers, setProviders] = useState<ProviderInfo[] | null>(null);
  const [live, setLive] = useState<LiveStatus | null>(null);
  const [nlp, setNlp] = useState<Record<string, string> | null>(null);
  const [narrator, setNarrator] = useState<{ available: boolean; reason?: string; provider?: string; model?: string | null } | null>(null);
  const [macro, setMacro] = useState<MacroRow[] | null>(null);
  const [busy, setBusy] = useState(false);
  const [manualOpen, setManualOpen] = useState(false);
  const [entry, setEntry] = useState({ series: "repo_rate", period_date: todayIst(), value: "", unit: "fraction", source: "", published_at: "" });

  const load = useCallback(async () => {
    try {
      const [rk, p, l, n, r, m] = await Promise.all([
        guard((t) => api.riskStatus(t)),
        guard((t) => api.providers(t)),
        guard((t) => api.liveStatus(t)),
        guard((t) => api.nlpStatus(t)),
        guard((t) => api.narratorStatus(t)),
        guard((t) => api.macroSummary(t)),
      ]);
      if (rk) setRisk(rk);
      if (p) setProviders(p);
      if (l) setLive(l);
      if (n) setNlp(n);
      if (r) setNarrator(r);
      if (m) setMacro(m);
    } catch (err) {
      toast({ tone: "error", title: "Could not load system status", body: err instanceof Error ? err.message : undefined });
    }
  }, [guard, toast]);

  useEffect(() => {
    void load();
  }, [load]);

  async function refreshMacro() {
    setBusy(true);
    try {
      const r = await guard((t) => api.macroIngest(t));
      if (r) {
        const failed = Object.entries(r).filter(([, v]) => v.startsWith("failed"));
        toast({ tone: failed.length ? "warning" : "success", title: failed.length ? `Refreshed; failed: ${failed.map(([k]) => k).join(", ")}` : "Macro and market series refreshed" });
      }
      await load();
    } catch (err) {
      toast({ tone: "error", title: "Refresh failed", body: err instanceof Error ? err.message : undefined });
    } finally {
      setBusy(false);
    }
  }

  async function addManual(e: React.FormEvent) {
    e.preventDefault();
    const value = Number(entry.value);
    if (!Number.isFinite(value)) {
      toast({ tone: "error", title: "Value must be a number" });
      return;
    }
    try {
      const r = await guard((t) => api.macroManual(t, { ...entry, value, published_at: new Date(entry.published_at).toISOString() }));
      if (r) toast({ tone: "success", title: `Recorded ${r.series}`, body: `Version ${r.version}` });
      setManualOpen(false);
      await load();
    } catch (err) {
      toast({ tone: "error", title: "Could not record the figure", body: err instanceof ApiError ? err.message : undefined });
    }
  }

  return (
    <div className="space-y-6">
      <PageHeader title="System" description="Trading controls, where the data comes from, what the engines can do, and why live trading is off." actions={<Button icon={<RefreshCw size={15} />} onClick={() => { void load(); void refreshHealth(); }}>Refresh</Button>} />

      <div className="grid gap-6 xl:grid-cols-3">
        {risk ? <KillSwitch risk={risk} onChange={load} /> : <Card title="Kill switch"><LoadingRows rows={3} /></Card>}

        <Card className="xl:col-span-2" title="Execution readiness" description="Every check must PASS before an order is accepted. UNKNOWN never passes." bodyClassName="pb-2">
          {!risk ? (
            <LoadingRows rows={5} />
          ) : (
            <>
              <div className="mb-4 flex flex-wrap gap-2">
                <Flag ok={risk.paper_orders_permitted} yes="Paper orders permitted" no="Paper orders blocked" />
                <Flag ok={risk.live_orders_permitted} yes="Live orders permitted" no="Live orders blocked" />
              </div>
              <MobileList className="mb-2">
                {risk.checks.map((c) => (
                  <MobileItem key={c.name}>
                    <div className="flex items-center justify-between gap-3">
                      <span className="text-sm font-medium capitalize">{humanize(c.name)}</span>
                      <GateBadge s={c.status} />
                    </div>
                    <p className="mt-1 break-words text-xs text-muted">{c.reason}</p>
                  </MobileItem>
                ))}
              </MobileList>
              <DesktopOnly>
              <Table>
                <thead>
                  <tr>
                    <Th>Check</Th>
                    <Th>Result</Th>
                    <Th>Why</Th>
                  </tr>
                </thead>
                <tbody>
                  {risk.checks.map((c) => (
                    <tr key={c.name}>
                      <Td className="capitalize">{humanize(c.name)}</Td>
                      <Td><GateBadge s={c.status} /></Td>
                      <Td className="text-muted">{c.reason}</Td>
                    </tr>
                  ))}
                </tbody>
              </Table>
              </DesktopOnly>
              <p className="py-3 font-mono text-[11px] text-subtle">config {risk.config_version} · {risk.config_fingerprint.slice(0, 16)}</p>
            </>
          )}
        </Card>
      </div>

      <div className="grid gap-6 lg:grid-cols-2 xl:grid-cols-3">
        <Card title={<span className="flex items-center gap-2"><Server size={15} aria-hidden /> Infrastructure</span>}>
          {health ? (
            <KeyValues
              items={[
                ...health.components.map((c) => [<span key={c.name} className="capitalize">{c.name}</span>, <Flag key="f" ok={c.healthy} yes="Healthy" no="Unavailable" />] as [React.ReactNode, React.ReactNode]),
                ["Environment", <span key="e" className="capitalize">{health.environment}</span>],
                ["System mode", <span key="m" className="font-medium uppercase">{health.system_mode}</span>],
                ["API version", <span key="v" className="font-mono">{health.version}</span>],
              ]}
            />
          ) : (
            <p className="text-sm text-fail">API unreachable</p>
          )}
        </Card>

        <Card title={<span className="flex items-center gap-2"><ShieldOff size={15} aria-hidden /> Live trading</span>} description="Disabled by design in this build.">
          {live ? (
            <div className="space-y-3">
              <Flag ok={live.live_orders_permitted} yes="Live orders permitted" no="Live orders not permitted" />
              <p className="text-xs text-muted">
                Broker adapter <span className="font-mono text-ink">{live.broker}</span> · {live.broker_reason}
              </p>
              <ul className="list-inside list-disc space-y-1 text-xs text-muted">
                {live.blocking_reasons.map((r) => (
                  <li key={r}>{r}</li>
                ))}
              </ul>
            </div>
          ) : (
            <LoadingRows rows={3} />
          )}
        </Card>

        <Card title={<span className="flex items-center gap-2"><Cpu size={15} aria-hidden /> Analysis engines</span>}>
          <KeyValues
            items={[
              ["News sentiment (FinBERT)", <span key="s" className="text-xs">{nlp?.sentiment ?? "—"}</span>],
              ["Document embeddings", <span key="e" className="text-xs">{nlp?.embedder ?? "—"}</span>],
              [
                "LLM narrator",
                narrator?.available ? (
                  <Badge key="n" tone="pass" icon={<CheckCircle2 size={12} aria-hidden />}>{narrator.provider} {narrator.model ?? ""}</Badge>
                ) : (
                  <span key="n" className="text-xs text-muted">{narrator?.reason ?? "—"}</span>
                ),
              ],
            ]}
          />
          <p className="mt-3 text-xs text-subtle">The narrator only rewrites reports in prose. It never decides and may not add numbers.</p>
        </Card>

        <Card className="lg:col-span-2" title={<span className="flex items-center gap-2"><Database size={15} aria-hidden /> Price data sources</span>} description="Only licensed prices can pass the paper-trading gates.">
          {!providers ? (
            <LoadingRows rows={3} />
          ) : (
            <ul className="divide-y divide-line">
              {providers.map((p) => (
                <li key={p.name} className="flex flex-wrap items-start justify-between gap-2 py-3 first:pt-0 last:pb-0">
                  <div className="min-w-0">
                    <p className="font-mono text-sm">{p.name}</p>
                    <p className="text-xs text-muted">{p.reason}</p>
                  </div>
                  <div className="flex gap-2">
                    <Flag ok={p.enabled} yes="Enabled" no="Disabled" />
                    {p.licensed ? <Badge tone="pass" icon={<CheckCircle2 size={12} aria-hidden />}>Licensed</Badge> : <Badge tone="warn">Research only</Badge>}
                  </div>
                </li>
              ))}
            </ul>
          )}
        </Card>

        <Card title={<span className="flex items-center gap-2"><CalendarClock size={15} aria-hidden /> Scheduled jobs</span>} description="IST, weekdays unless stated.">
          <ul className="space-y-2 text-sm">
            {JOBS.map(([when, what]) => (
              <li key={what} className="flex gap-3">
                <span className="w-20 shrink-0 font-mono text-xs text-subtle">{when}</span>
                <span className="text-muted">{what}</span>
              </li>
            ))}
          </ul>
        </Card>
      </div>

      <Card
        title="Macro and market series"
        description="Latest observation per series, as stored — point in time and versioned."
        actions={
          isAdmin && (
            <>
              <Button size="sm" icon={<Plus size={14} />} onClick={() => setManualOpen(true)}>Record figure</Button>
              <Button size="sm" loading={busy} icon={<RefreshCw size={14} />} onClick={refreshMacro}>Refresh now</Button>
            </>
          )
        }
        bodyClassName="pb-2"
      >
        {!macro ? (
          <LoadingRows rows={4} />
        ) : (
          <>
          <MobileList className="mb-2">
            {macro.map((m) => (
              <MobileItem key={m.series}>
                <div className="flex items-center justify-between gap-3">
                  <span className="font-mono text-[13px]">{m.series}</span>
                  <span className="font-mono text-[13px]">{m.latest_value === null ? "—" : m.latest_value.toLocaleString("en-IN", { maximumFractionDigits: 4 })}</span>
                </div>
                <p className="mt-0.5 text-xs text-muted">{m.latest_date ?? "—"} · {m.observations} obs · {m.licensed ? "official" : "research only"}</p>
              </MobileItem>
            ))}
            {macro.length === 0 && <MobileItem><span className="text-sm text-muted">No macro data yet.</span></MobileItem>}
          </MobileList>
          <DesktopOnly>
          <Table>
            <thead>
              <tr>
                <Th>Series</Th>
                <Th>Latest date</Th>
                <Th align="right">Value</Th>
                <Th align="right" className="hidden sm:table-cell">Observations</Th>
                <Th className="hidden md:table-cell">Source</Th>
                <Th className="hidden lg:table-cell">Retrieved</Th>
              </tr>
            </thead>
            <tbody>
              {macro.map((m) => (
                <tr key={m.series}>
                  <Td mono>{m.series}</Td>
                  <Td>{m.latest_date ?? "—"}</Td>
                  <Td align="right" mono>{m.latest_value === null ? "—" : m.latest_value.toLocaleString("en-IN", { maximumFractionDigits: 4 })}</Td>
                  <Td align="right" mono className="hidden sm:table-cell">{m.observations}</Td>
                  <Td className="hidden md:table-cell">{m.licensed ? <Badge tone="pass">Official</Badge> : <Badge tone="warn">Research only</Badge>}</Td>
                  <Td className="hidden text-muted lg:table-cell">{istDateTime(m.retrieved_at)}</Td>
                </tr>
              ))}
              {macro.length === 0 && (
                <tr>
                  <Td colSpan={6} className="text-muted">No macro data yet.</Td>
                </tr>
              )}
            </tbody>
          </Table>
          </DesktopOnly>
          </>
        )}
      </Card>

      <Dialog
        open={manualOpen}
        onClose={() => setManualOpen(false)}
        title="Record an official figure"
        description="For example an RBI repo-rate decision. Never estimated: give its real source and publication time."
        size="lg"
        footer={
          <>
            <Button onClick={() => setManualOpen(false)}>Cancel</Button>
            <Button variant="primary" type="submit" form="macro-manual">Record figure</Button>
          </>
        }
      >
        <form id="macro-manual" onSubmit={addManual} className="grid gap-4 sm:grid-cols-2">
          {(
            [
              ["series", "Series", "text", "repo_rate"],
              ["period_date", "Effective date", "date", ""],
              ["value", "Value", "text", "0.055 for 5.50%"],
              ["unit", "Unit", "text", "fraction"],
              ["source", "Source", "text", "RBI MPC statement, 6 Aug 2026"],
              ["published_at", "Published at (your local time)", "datetime-local", ""],
            ] as const
          ).map(([key, label, type, ph]) => (
            <Field key={key} label={label}>
              {(id) => <Input id={id} type={type} placeholder={ph} value={entry[key]} onChange={(e) => setEntry({ ...entry, [key]: e.target.value })} required />}
            </Field>
          ))}
        </form>
      </Dialog>
    </div>
  );
}
