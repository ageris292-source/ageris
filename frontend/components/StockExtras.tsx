"use client";

import { useCallback, useEffect, useState } from "react";
import { api, ApiError, type Basis, type IngestionRun, type ModelEstimate, type ReportHistoryRow } from "@/lib/api";

type Guard = <T>(fn: (t: string) => Promise<T>) => Promise<T | undefined>;

const pct = (v: number | undefined, d = 1) => (v === undefined ? "—" : `${(v * 100).toFixed(d)}%`);
const ist = (iso: string) => new Date(iso).toLocaleString("en-IN", { timeZone: "Asia/Kolkata" });

function Panel({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section className="rounded-lg border border-line bg-panel p-5">
      <h3 className="mb-3 text-xs font-semibold uppercase tracking-wider text-muted">{title}</h3>
      {children}
    </section>
  );
}

/** Model estimate, research report history and (admin) licensed CSV import. */
export function StockExtras({
  ticker,
  guard,
  isAdmin,
  onImported,
}: {
  ticker: string;
  guard: Guard;
  isAdmin: boolean;
  onImported: () => void;
}) {
  const [est, setEst] = useState<ModelEstimate | null>(null);
  const [hist, setHist] = useState<ReportHistoryRow[]>([]);
  const [file, setFile] = useState<File | null>(null);
  const [source, setSource] = useState("");
  const [basis, setBasis] = useState<Basis>("raw");
  const [result, setResult] = useState<{ tone: "ok" | "fail"; text: string } | null>(null);
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    const [e, h] = await Promise.all([
      guard((t) => api.modelEstimate(t, ticker)).catch(() => undefined),
      guard((t) => api.analysisHistory(t, ticker)).catch(() => undefined),
    ]);
    if (e) setEst(e);
    if (h) setHist(h);
  }, [guard, ticker]);

  useEffect(() => {
    void load();
  }, [load]);

  async function upload(ev: React.FormEvent) {
    ev.preventDefault();
    if (!file) return;
    setBusy(true);
    setResult(null);
    try {
      const run: IngestionRun | undefined = await guard((t) => api.importCsv(t, ticker, file, source.trim(), basis));
      if (run) {
        setResult({
          tone: run.status.startsWith("succeeded") ? "ok" : "fail",
          text: `${run.status}: ${run.rows_inserted} new, ${run.rows_revised} revised, ${run.rows_rejected} rejected`,
        });
        onImported();
      }
    } catch (err) {
      setResult({ tone: "fail", text: err instanceof ApiError ? err.message : "Import failed" });
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="mb-4 grid gap-4 md:grid-cols-2">
      <Panel title="Model estimate (20 trading days)">
        {est === null ? (
          <p className="text-sm text-muted">Loading…</p>
        ) : est.available ? (
          <>
            <div className="grid grid-cols-3 gap-3">
              {[
                ["P(profit)", pct(est.p_profit)],
                ["P(beat NIFTY)", pct(est.p_outperform)],
                ["Expected return", pct(est.expected_return, 2)],
              ].map(([k, v]) => (
                <div key={k}><div className="text-xs text-muted">{k}</div><div className="font-mono text-lg">{v}</div></div>
              ))}
            </div>
            <p className="mt-2 text-xs text-muted">
              Model {est.model_id} · features as of {est.as_of_date} · out-of-sample calibration error {est.calibration_error?.toFixed(3)} over {est.oos_periods} folds.
              A model estimate, not a guarantee; the 24 gates decide.
            </p>
          </>
        ) : (
          <p className="text-sm text-unknown">
            <span aria-hidden>? </span>No estimate: {est.reason}. Probability gates are UNKNOWN, so every entry is rejected.
          </p>
        )}
      </Panel>

      <Panel title="Research report history">
        <ul className="max-h-56 space-y-1 overflow-y-auto text-xs">
          {hist.map((r) => (
            <li key={r.report_id} className="flex flex-wrap justify-between gap-2 border-t border-line pt-1 first:border-0">
              <span className="font-mono">#{r.report_id} · {ist(r.created_at)}</span>
              <span>
                {r.stance.replaceAll("_", " ").toLowerCase()}
                {r.composite_score !== null && ` · ${r.composite_score.toFixed(1)}`}
                {r.confidence !== null && ` · conf ${r.confidence.toFixed(2)}`}
              </span>
            </li>
          ))}
          {hist.length === 0 && <li className="text-muted">No reports yet. Run one above, or wait for the daily ranking.</li>}
        </ul>
      </Panel>

      {isAdmin && (
        <div className="md:col-span-2">
          <Panel title="Import licensed prices (CSV, admin)">
            <form onSubmit={upload} className="flex flex-wrap items-end gap-3 text-sm">
              <label className="flex flex-col gap-1">
                <span className="text-xs text-muted">CSV file (date, open, high, low, close, volume; max 5 MB)</span>
                <input type="file" accept=".csv,text/csv" onChange={(e) => setFile(e.target.files?.[0] ?? null)} required />
              </label>
              <label className="flex flex-col gap-1">
                <span className="text-xs text-muted">Source (who licensed / published it)</span>
                <input className="rounded border border-line bg-surface px-2 py-1" value={source} onChange={(e) => setSource(e.target.value)} placeholder="e.g. NSE bhavcopy export" minLength={1} maxLength={60} required />
              </label>
              <label className="flex flex-col gap-1">
                <span className="text-xs text-muted">Price basis</span>
                <select className="rounded border border-line bg-surface px-2 py-1" value={basis} onChange={(e) => setBasis(e.target.value as Basis)}>
                  <option value="raw">raw (as traded)</option>
                  <option value="split_adjusted">split-adjusted</option>
                  <option value="total_return">total return</option>
                </select>
              </label>
              <button className="rounded bg-ink px-3 py-1.5 text-surface disabled:opacity-40" disabled={busy || !file} type="submit">
                {busy ? "Importing…" : "Import"}
              </button>
            </form>
            {result && <p className={`mt-2 text-sm ${result.tone === "ok" ? "text-pass" : "text-fail"}`}>{result.text}</p>}
            <p className="mt-2 text-xs text-muted">
              You attest the file comes from a licensed or official source. Rows are validated, versioned and audited; NSE stocks also receive licensed data automatically every weekday evening.
            </p>
          </Panel>
        </div>
      )}
    </div>
  );
}
