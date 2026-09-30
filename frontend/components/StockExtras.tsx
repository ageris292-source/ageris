"use client";

import { Brain, CircleHelp, Upload } from "lucide-react";
import { useState } from "react";
import { useToast } from "@/components/providers/ToastProvider";
import { Button, Card, Field, Input, Select } from "@/components/ui/core";
import { api, ApiError, type Basis, type ModelEstimate } from "@/lib/api";
import { pct, signedPct, toneOf } from "@/lib/format";

type Guard = <T>(fn: (t: string) => Promise<T>) => Promise<T | undefined>;

export function ModelEstimateCard({ est }: { est: ModelEstimate | null | undefined }) {
  return (
    <Card
      title={
        <span className="flex items-center gap-2">
          <Brain size={15} className="text-accent" aria-hidden /> Model estimate
        </span>
      }
      description={est?.horizon_days ? `Next ${est.horizon_days} trading days` : "Walk-forward LightGBM, calibrated"}
    >
      {est === undefined && <div className="skeleton h-20 rounded-lg" />}
      {est === null && <p className="text-sm text-muted">Could not load the estimate.</p>}
      {est && est.available && (
        <>
          <div className="grid grid-cols-3 gap-3">
            {[
              ["P(profit)", pct(est.p_profit), ""],
              ["P(beat NIFTY)", pct(est.p_outperform), ""],
              ["Expected", signedPct(est.expected_return), toneOf(est.expected_return)],
            ].map(([k, v, tone]) => (
              <div key={k} className="rounded-lg bg-sunken px-3 py-2.5">
                <div className="text-xs text-muted">{k}</div>
                <div className={`mt-0.5 text-lg font-semibold tabular-nums ${tone}`}>{v}</div>
              </div>
            ))}
          </div>
          <p className="mt-3 text-xs text-muted">
            Model {est.model_id} · features as of {est.as_of_date} · out-of-sample calibration error {est.calibration_error?.toFixed(3)} over {est.oos_periods} folds. An estimate, not a promise — the 24 gates decide.
          </p>
        </>
      )}
      {est && !est.available && (
        <div className="flex gap-2 text-sm text-warn">
          <CircleHelp size={16} className="mt-0.5 shrink-0" aria-hidden />
          <p>
            No estimate: {est.reason}.<span className="block text-xs text-muted">Probability gates are UNKNOWN, so every entry is rejected until a healthy model is active.</span>
          </p>
        </div>
      )}
    </Card>
  );
}

export function CsvImportCard({ ticker, guard, onImported }: { ticker: string; guard: Guard; onImported: () => void }) {
  const toast = useToast();
  const [file, setFile] = useState<File | null>(null);
  const [source, setSource] = useState("");
  const [basis, setBasis] = useState<Basis>("raw");
  const [busy, setBusy] = useState(false);

  async function upload(ev: React.FormEvent) {
    ev.preventDefault();
    if (!file) return;
    setBusy(true);
    try {
      const run = await guard((t) => api.importCsv(t, ticker, file, source.trim(), basis));
      if (run) {
        toast({
          tone: run.status.startsWith("succeeded") ? "success" : "error",
          title: `Import ${run.status.replaceAll("_", " ")}`,
          body: `${run.rows_inserted} new, ${run.rows_revised} revised, ${run.rows_rejected} rejected`,
        });
        onImported();
      }
    } catch (err) {
      toast({ tone: "error", title: "Import failed", body: err instanceof ApiError ? err.message : undefined });
    } finally {
      setBusy(false);
    }
  }

  return (
    <Card title="Import licensed prices" description="Admin only · CSV with date, open, high, low, close, volume (max 5 MB)">
      <form onSubmit={upload} className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4 lg:items-end">
        <Field label="CSV file">
          {(id) => (
            <input
              id={id}
              type="file"
              accept=".csv,text/csv"
              required
              onChange={(e) => setFile(e.target.files?.[0] ?? null)}
              className="text-sm file:mr-3 file:rounded-md file:border file:border-line file:bg-panel file:px-3 file:py-1.5 file:text-sm file:text-ink"
            />
          )}
        </Field>
        <Field label="Source (who licensed / published it)">
          {(id) => <Input id={id} value={source} onChange={(e) => setSource(e.target.value)} placeholder="e.g. NSE bhavcopy export" maxLength={60} required />}
        </Field>
        <Field label="Price basis">
          {(id) => (
            <Select id={id} value={basis} onChange={(e) => setBasis(e.target.value as Basis)}>
              <option value="raw">Raw (as traded)</option>
              <option value="split_adjusted">Split-adjusted</option>
              <option value="total_return">Total return</option>
            </Select>
          )}
        </Field>
        <Button type="submit" variant="primary" loading={busy} disabled={!file || !source.trim()} icon={<Upload size={15} />}>
          Import
        </Button>
      </form>
      <p className="mt-3 text-xs text-muted">
        You attest the file comes from a licensed or official source. Rows are validated, versioned and audited.
      </p>
    </Card>
  );
}
