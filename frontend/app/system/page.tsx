"use client";

import { useCallback, useEffect, useState } from "react";
import { Login } from "@/components/Login";
import { Nav } from "@/components/Nav";
import { useSession } from "@/components/useSession";
import { api, ApiError, type LiveStatus, type MacroRow, type ProviderInfo } from "@/lib/api";

const ist = (iso: string | null) =>
  iso ? new Date(iso).toLocaleString("en-IN", { timeZone: "Asia/Kolkata" }) : "—";

function Panel({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section className="mb-4 rounded-lg border border-line bg-panel p-5">
      <h3 className="mb-3 text-xs font-semibold uppercase tracking-wider text-muted">{title}</h3>
      {children}
    </section>
  );
}

// Never color alone: icon + word + color.
function Flag({ ok, yes, no }: { ok: boolean | null | undefined; yes: string; no: string }) {
  if (ok === null || ok === undefined) return <span className="text-unknown">? unknown</span>;
  return ok ? <span className="text-pass">✓ {yes}</span> : <span className="text-fail">✕ {no}</span>;
}

const todayIst = () => new Date(Date.now() + 5.5 * 3600_000).toISOString().slice(0, 10);

export default function SystemPage() {
  const { token, ready, me, health, signIn, signOut, guard } = useSession();
  const [providers, setProviders] = useState<ProviderInfo[]>([]);
  const [live, setLive] = useState<LiveStatus | null>(null);
  const [nlp, setNlp] = useState<Record<string, string> | null>(null);
  const [narrator, setNarrator] = useState<{ available: boolean; reason?: string; provider?: string; model?: string | null } | null>(null);
  const [macro, setMacro] = useState<MacroRow[]>([]);
  const [msg, setMsg] = useState<{ tone: "ok" | "fail"; text: string } | null>(null);
  const [busy, setBusy] = useState(false);
  const [entry, setEntry] = useState({ series: "repo_rate", period_date: todayIst(), value: "", unit: "fraction", source: "", published_at: "" });
  const isAdmin = me?.role === "admin";

  const load = useCallback(async () => {
    try {
      const [p, l, n, r, m] = await Promise.all([
        guard((t) => api.providers(t)),
        guard((t) => api.liveStatus(t)),
        guard((t) => api.nlpStatus(t)),
        guard((t) => api.narratorStatus(t)),
        guard((t) => api.macroSummary(t)),
      ]);
      if (p) setProviders(p);
      if (l) setLive(l);
      if (n) setNlp(n);
      if (r) setNarrator(r);
      if (m) setMacro(m);
    } catch (err) {
      setMsg({ tone: "fail", text: err instanceof Error ? err.message : "Request failed" });
    }
  }, [guard]);

  useEffect(() => {
    if (token) void load();
  }, [token, load]);

  async function refreshMacro() {
    setBusy(true);
    setMsg(null);
    try {
      const r = await guard((t) => api.macroIngest(t));
      if (r) {
        const failed = Object.entries(r).filter(([, v]) => v.startsWith("failed"));
        setMsg({
          tone: failed.length ? "fail" : "ok",
          text: failed.length ? `Refreshed; failed: ${failed.map(([k]) => k).join(", ")}` : "Macro and market series refreshed.",
        });
      }
      await load();
    } catch (err) {
      setMsg({ tone: "fail", text: err instanceof Error ? err.message : "Refresh failed" });
    } finally {
      setBusy(false);
    }
  }

  async function addManual(e: React.FormEvent) {
    e.preventDefault();
    setMsg(null);
    const value = Number(entry.value);
    if (!Number.isFinite(value)) {
      setMsg({ tone: "fail", text: "Value must be a number." });
      return;
    }
    try {
      const published = new Date(entry.published_at);
      const r = await guard((t) =>
        api.macroManual(t, { ...entry, value, published_at: published.toISOString() }),
      );
      if (r) setMsg({ tone: "ok", text: `Recorded ${r.series} (version ${r.version}).` });
      await load();
    } catch (err) {
      setMsg({ tone: "fail", text: err instanceof ApiError ? err.message : "Could not record the figure" });
    }
  }

  if (!ready) return null;
  if (!token) return <Login onToken={signIn} />;

  return (
    <main className="mx-auto max-w-5xl px-4 py-8">
      <Nav mode={health?.system_mode} email={me?.email} role={me?.role} onSignOut={signOut} />
      <h2 className="mb-1 text-2xl font-semibold">System</h2>
      <p className="mb-6 text-sm text-muted">Where the data comes from, what the analysis engines can do, and why live trading is off.</p>
      {msg && <p className={`mb-4 text-sm ${msg.tone === "ok" ? "text-pass" : "text-fail"}`}>{msg.text}</p>}

      <div className="grid gap-4 md:grid-cols-2">
        <Panel title="Price data sources">
          <ul className="space-y-2 text-sm">
            {providers.map((p) => (
              <li key={p.name} className="border-t border-line pt-2 first:border-0 first:pt-0">
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <span className="font-mono">{p.name}</span>
                  <span className="flex gap-3 text-xs">
                    <Flag ok={p.enabled} yes="enabled" no="disabled" />
                    <Flag ok={p.licensed} yes="licensed" no="research only" />
                  </span>
                </div>
                <div className="text-xs text-muted">{p.reason}</div>
              </li>
            ))}
          </ul>
          <p className="mt-3 text-xs text-muted">
            Licensed NSE end-of-day data arrives each weekday evening from the feeder; only licensed prices can pass the paper-trading gates.
          </p>
        </Panel>

        <Panel title="Live trading">
          {live ? (
            <>
              <div className="mb-2 text-sm">
                <Flag ok={live.live_orders_permitted} yes="live orders permitted" no="live orders not permitted" />
              </div>
              <div className="mb-2 text-xs text-muted">Broker adapter: <span className="font-mono">{live.broker}</span> · {live.broker_reason}</div>
              <ul className="list-inside list-disc text-xs text-unknown">
                {live.blocking_reasons.map((r) => <li key={r}>{r}</li>)}
              </ul>
              <p className="mt-3 text-xs text-muted">Disabled by design in this build: paper trading only, and every order needs human approval.</p>
            </>
          ) : (
            <p className="text-sm text-muted">Loading…</p>
          )}
        </Panel>

        <Panel title="Analysis engines">
          <ul className="space-y-2 text-sm">
            <li className="flex flex-wrap justify-between gap-2">
              <span>News sentiment (FinBERT)</span>
              <span className="text-xs">{nlp?.sentiment ?? "—"}</span>
            </li>
            <li className="flex flex-wrap justify-between gap-2">
              <span>Document search embeddings</span>
              <span className="text-xs">{nlp?.embedder ?? "—"}</span>
            </li>
            <li className="flex flex-wrap justify-between gap-2">
              <span>LLM narrator (prose only, never decides)</span>
              <span className="text-xs">
                {narrator?.available ? `✓ ${narrator.provider} ${narrator.model ?? ""}` : `✕ ${narrator?.reason ?? "—"}`}
              </span>
            </li>
          </ul>
        </Panel>

        <Panel title="Scheduled jobs (IST, weekdays)">
          <ul className="space-y-1 text-xs text-muted">
            <li>19:10 · licensed NSE prices and corporate actions (Mac feeder)</li>
            <li>19:30 · paper portfolios marked, theses checked</li>
            <li>19:45 · daily ranking through the 24 gates</li>
            <li>20:00 · model monitoring (drift, calibration decay)</li>
            <li>17:30 · macro and market series · every 2 h · news</li>
            <li>Saturday · fundamentals · Sunday · walk-forward retrain (candidates only)</li>
          </ul>
        </Panel>
      </div>

      <Panel title="Macro and market series">
        <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
          <p className="text-xs text-muted">Latest observation per series, as stored (point in time, versioned).</p>
          {isAdmin && (
            <button className="rounded border border-line px-3 py-1.5 text-sm disabled:opacity-40" disabled={busy} onClick={refreshMacro}>
              {busy ? "Refreshing…" : "Refresh now"}
            </button>
          )}
        </div>
        <div className="overflow-x-auto">
          <table className="w-full text-xs">
            <thead className="text-left text-muted">
              <tr>{["Series", "Latest date", "Value", "Observations", "Source", "Retrieved"].map((h) => <th key={h} className="py-1 pr-3 font-normal">{h}</th>)}</tr>
            </thead>
            <tbody>
              {macro.map((m) => (
                <tr key={m.series} className="border-t border-line">
                  <td className="py-1 pr-3 font-mono">{m.series}</td>
                  <td className="py-1 pr-3">{m.latest_date ?? "—"}</td>
                  <td className="py-1 pr-3 font-mono">{m.latest_value === null ? "—" : m.latest_value.toLocaleString("en-IN", { maximumFractionDigits: 4 })}</td>
                  <td className="py-1 pr-3 font-mono">{m.observations}</td>
                  <td className="py-1 pr-3">{m.licensed ? "official" : "research only"}</td>
                  <td className="py-1 pr-3 text-muted">{ist(m.retrieved_at)}</td>
                </tr>
              ))}
              {macro.length === 0 && <tr><td colSpan={6} className="py-2 text-muted">No macro data yet.</td></tr>}
            </tbody>
          </table>
        </div>

        {isAdmin && (
          <form onSubmit={addManual} className="mt-4 border-t border-line pt-4 text-sm">
            <div className="mb-2 text-xs font-semibold text-muted">Record an official figure (e.g. an RBI repo-rate decision). It is never estimated: give its real source and publication time.</div>
            <div className="grid gap-3 sm:grid-cols-3">
              {(
                [
                  ["series", "Series", "text", "repo_rate"],
                  ["period_date", "Effective date", "date", ""],
                  ["value", "Value", "text", "0.055 for 5.50%"],
                  ["unit", "Unit", "text", "fraction"],
                  ["source", "Source", "text", "RBI MPC statement, 6 Aug 2026"],
                  ["published_at", "Published at (local time)", "datetime-local", ""],
                ] as const
              ).map(([key, label, type, ph]) => (
                <label key={key} className="flex flex-col gap-1">
                  <span className="text-xs text-muted">{label}</span>
                  <input
                    className="rounded border border-line bg-surface px-2 py-1"
                    type={type}
                    placeholder={ph}
                    value={entry[key]}
                    onChange={(e) => setEntry({ ...entry, [key]: e.target.value })}
                    required
                  />
                </label>
              ))}
            </div>
            <button className="mt-3 rounded bg-ink px-3 py-1.5 text-surface" type="submit">Record figure</button>
          </form>
        )}
      </Panel>
    </main>
  );
}
