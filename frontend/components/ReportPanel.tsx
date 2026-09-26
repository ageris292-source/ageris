"use client";

import type { AnalysisReport, Stance } from "@/lib/api";

const stanceTone: Record<Stance, string> = {
  POSITIVE_TILT: "text-pass",
  NEGATIVE_TILT: "text-fail",
  NO_CLEAR_TILT: "text-ink",
  INSUFFICIENT_DATA: "text-unknown",
};

export function ReportPanel({
  report,
  busy,
  onRun,
  onDownload,
}: {
  report: AnalysisReport | null;
  busy: boolean;
  onRun: () => void;
  onDownload: () => void;
}) {
  const s = report?.synthesis;
  return (
    <section className="mb-4 rounded-lg border border-line bg-panel p-5">
      <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
        <h3 className="text-xs font-semibold uppercase tracking-wider text-muted">Research report (all agents)</h3>
        <div className="flex gap-2">
          {report && (
            <button className="rounded border border-line px-2.5 py-1 text-xs" onClick={onDownload}>
              Download .md
            </button>
          )}
          <button
            className="rounded bg-ink px-2.5 py-1 text-xs text-surface disabled:opacity-40"
            onClick={onRun}
            disabled={busy}
          >
            {busy ? "Running all agents…" : report ? "Re-run analysis" : "Run full analysis"}
          </button>
        </div>
      </div>
      {!s && <p className="text-sm text-muted">No report yet. Runs every agent at the same point in time and stores an immutable, hash-stamped report.</p>}
      {s && report && (
        <>
          <div className="mb-4 flex flex-wrap items-end gap-8">
            <div>
              <div className="text-xs text-muted">Decision</div>
              <div className="text-2xl font-semibold text-fail">{s.decision.trade}</div>
            </div>
            <div>
              <div className="text-xs text-muted">Research stance</div>
              <div className={`text-lg font-semibold ${stanceTone[s.stance]}`}>{s.stance_text}</div>
            </div>
            <div>
              <div className="text-xs text-muted">Composite</div>
              <div className="font-mono text-lg">{s.composite_score === null ? "—" : s.composite_score.toFixed(1)}<span className="text-xs text-muted">/100</span></div>
            </div>
            <div>
              <div className="text-xs text-muted">Confidence</div>
              <div className="font-mono text-lg">{s.confidence.toFixed(2)}</div>
              <div className="text-[10px] text-muted">heuristic, not calibrated</div>
            </div>
          </div>
          <p className="mb-4 text-xs text-muted">{s.decision.reason}</p>
          {s.insufficient_reasons.map((r) => (
            <p key={r} className="mb-2 text-xs text-unknown">? {r}</p>
          ))}
          <div className="mb-4 overflow-x-auto">
            <table className="w-full font-mono text-xs">
              <thead className="text-left text-muted">
                <tr>
                  {["Agent", "Status", "Score", "Confidence", "Quality", "Weight"].map((h) => (
                    <th key={h} className="py-1 pr-3 font-normal">{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {s.agents.map((a) => (
                  <tr key={a.agent} className="border-t border-line">
                    <td className="py-1 pr-3">{a.agent}</td>
                    <td className={`py-1 pr-3 ${a.status === "ok" ? "" : "text-unknown"}`}>{a.status.replaceAll("_", " ")}</td>
                    <td className="py-1 pr-3">{a.score === null ? "—" : a.score.toFixed(1)}</td>
                    <td className="py-1 pr-3">{a.confidence.toFixed(2)}</td>
                    <td className="py-1 pr-3">{a.data_quality.toFixed(2)}</td>
                    <td className="py-1 pr-3">{a.weight.toFixed(2)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <div className="grid gap-4 md:grid-cols-2">
            {([["Bull case", s.bull_case, "text-pass", "▲"], ["Bear case", s.bear_case, "text-fail", "▼"]] as const).map(
              ([title, pts, tone, icon]) => (
                <div key={title}>
                  <h4 className={`mb-2 text-xs font-semibold uppercase tracking-wider ${tone}`}>{icon} {title}</h4>
                  <ul className="space-y-1.5 text-sm">
                    {pts.map((p, i) => (
                      <li key={i}>
                        <span className="font-mono text-xs text-muted">{p.agent}</span> {p.detail}
                      </li>
                    ))}
                    {pts.length === 0 && <li className="text-muted">None identified.</li>}
                  </ul>
                </div>
              ),
            )}
          </div>
          {s.conflicts.length > 0 && (
            <div className="mt-4">
              <h4 className="mb-1 text-xs font-semibold uppercase tracking-wider text-unknown">Conflicts</h4>
              <ul className="text-sm">{s.conflicts.map((c) => <li key={c.detail}>! {c.detail}</li>)}</ul>
            </div>
          )}
          {s.key_risks.length > 0 && (
            <div className="mt-4">
              <h4 className="mb-1 text-xs font-semibold uppercase tracking-wider text-muted">Key risks</h4>
              <ul className="space-y-1 text-sm">
                {s.key_risks.slice(0, 8).map((r) => (
                  <li key={r.risk}><span className="font-mono text-xs text-muted">{r.agent}</span> {r.risk}</li>
                ))}
              </ul>
            </div>
          )}
          <div className="mt-4 rounded border border-line p-3 text-sm">
            <p>{report.narrative.text}</p>
            <p className="mt-2 text-xs text-muted">Summary source: {report.narrative.source}</p>
          </div>
          <p className="mt-3 font-mono text-[11px] text-muted">
            report #{report.report_id} · hash {report.report_hash.slice(0, 16)}
            {report.hash_verified !== undefined && (report.hash_verified ? " · verified" : " · HASH MISMATCH")} · as of{" "}
            {new Date(report.as_of).toLocaleString("en-IN", { timeZone: "Asia/Kolkata" })} IST
          </p>
        </>
      )}
    </section>
  );
}
