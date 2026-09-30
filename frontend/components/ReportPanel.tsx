"use client";

import { CircleHelp, Download, FileText, ShieldAlert, Sparkles, TrendingDown, TrendingUp, TriangleAlert } from "lucide-react";
import type { AnalysisReport, ReportHistoryRow } from "@/lib/api";
import { Badge, Button, Card, EmptyState, SectionLabel, cx } from "@/components/ui/core";
import { ScoreBar, ScoreRing, StanceBadge } from "@/components/ui/Status";
import { ago, humanize, istDateTime, num } from "@/lib/format";

const AGENT_LABEL: Record<string, string> = {
  technical: "Technical",
  fundamental: "Fundamental",
  news: "News",
  valuation: "Valuation",
  macro: "Macro",
  risk: "Risk",
  portfolio: "Portfolio fit",
};
const agentLabel = (a: string) => AGENT_LABEL[a] ?? humanize(a).replace(/^\w/, (c) => c.toUpperCase());

/** The hero research card: composite score, stance, decision and each agent's score. */
export function ResearchSummary({
  report,
  busy,
  onRun,
  onDownload,
}: {
  report: AnalysisReport | null | undefined;
  busy: boolean;
  onRun: () => void;
  onDownload: () => void;
}) {
  const s = report?.synthesis;
  return (
    <Card
      title={
        <span className="flex items-center gap-2">
          <Sparkles size={15} className="text-accent" aria-hidden /> Research summary
        </span>
      }
      description={report ? `Report #${report.report_id} · ${ago(report.created_at ?? report.as_of)}` : "All agents at one point in time"}
      actions={
        <>
          {report && (
            <Button size="sm" variant="ghost" onClick={onDownload} icon={<Download size={14} />} aria-label="Download report as Markdown">
              .md
            </Button>
          )}
          <Button size="sm" variant={report ? "secondary" : "primary"} onClick={onRun} loading={busy}>
            {busy ? "Running agents…" : report ? "Re-run" : "Run analysis"}
          </Button>
        </>
      }
    >
      {report === undefined && <div className="skeleton h-40 rounded-lg" />}
      {report === null && (
        <EmptyState
          compact
          icon={<FileText size={20} />}
          title="No research report yet"
          body="Run every agent at the same point in time. The report is stored immutably with a hash."
        />
      )}
      {s && report && (
        <div className="space-y-5">
          <div className="flex items-center gap-5">
            <ScoreRing score={s.composite_score} label="composite" size={96} />
            <div className="min-w-0 space-y-1.5">
              <StanceBadge stance={s.stance} />
              <p className="text-sm font-medium">{s.stance_text}</p>
              <p className="text-xs text-muted">
                Confidence <span className="font-mono text-ink">{num(s.confidence)}</span> · coverage{" "}
                <span className="font-mono text-ink">{Math.round(s.coverage * 100)}%</span>
              </p>
            </div>
          </div>

          <div className="rounded-lg bg-sunken px-3 py-2.5">
            <div className="flex items-center gap-2 text-sm">
              <ShieldAlert size={15} className="text-muted" aria-hidden />
              <span className="text-muted">Decision</span>
              <span className="font-semibold">{s.decision.trade}</span>
            </div>
            <p className="mt-1 text-xs text-muted">{s.decision.reason}</p>
          </div>

          <div>
            <SectionLabel>Agent scores</SectionLabel>
            <ul className="space-y-2.5">
              {s.agents.map((a) => (
                <li key={a.agent} className="grid grid-cols-[92px_1fr] items-center gap-3 text-sm">
                  <span className="truncate text-muted">{agentLabel(a.agent)}</span>
                  {a.status === "ok" ? (
                    <ScoreBar score={a.score} />
                  ) : (
                    <span className="inline-flex items-center gap-1 text-xs text-warn">
                      <CircleHelp size={12} aria-hidden /> {humanize(a.status)}
                    </span>
                  )}
                </li>
              ))}
            </ul>
            <p className="mt-2 text-[11px] text-subtle">50 is neutral. Scores are heuristics, not probabilities.</p>
          </div>

          {s.insufficient_reasons.length > 0 && (
            <ul className="space-y-1 text-xs text-warn">
              {s.insufficient_reasons.map((r) => (
                <li key={r} className="flex gap-1.5">
                  <CircleHelp size={13} className="mt-0.5 shrink-0" aria-hidden />
                  {r}
                </li>
              ))}
            </ul>
          )}
        </div>
      )}
    </Card>
  );
}

/** Bull / bear case, narrative, conflicts and key risks. */
export function ReportDetails({ report }: { report: AnalysisReport }) {
  const s = report.synthesis;
  return (
    <div className="space-y-6">
      <div className="grid gap-6 md:grid-cols-2">
        {(
          [
            ["Bull case", s.bull_case, "text-pass", <TrendingUp key="u" size={15} aria-hidden />],
            ["Bear case", s.bear_case, "text-fail", <TrendingDown key="d" size={15} aria-hidden />],
          ] as const
        ).map(([title, pts, tone, icon]) => (
          <Card key={title} title={<span className={cx("flex items-center gap-2", tone)}>{icon}{title}</span>}>
            {pts.length === 0 ? (
              <p className="text-sm text-muted">None identified.</p>
            ) : (
              <ul className="space-y-3">
                {pts.map((p, i) => (
                  <li key={i} className="text-sm">
                    <Badge className="mr-2">{agentLabel(p.agent)}</Badge>
                    {p.detail}
                  </li>
                ))}
              </ul>
            )}
          </Card>
        ))}
      </div>

      <Card title="In plain words" description={`Summary written by: ${report.narrative.source}. It may not add any fact or number that isn't in the report.`}>
        <p className="text-[15px] leading-relaxed">{report.narrative.text}</p>
        {report.narrative.warnings.length > 0 && (
          <ul className="mt-3 space-y-1 text-xs text-warn">
            {report.narrative.warnings.map((w) => (
              <li key={w}>{w}</li>
            ))}
          </ul>
        )}
      </Card>

      {(s.conflicts.length > 0 || s.key_risks.length > 0 || s.data_warnings.length > 0) && (
        <div className="grid gap-6 md:grid-cols-2">
          {s.key_risks.length > 0 && (
            <Card title="Key risks">
              <ul className="space-y-2 text-sm">
                {s.key_risks.slice(0, 8).map((r) => (
                  <li key={r.agent + r.risk} className="flex gap-2">
                    <Badge className="shrink-0">{agentLabel(r.agent)}</Badge>
                    <span className="text-muted">{r.risk}</span>
                  </li>
                ))}
              </ul>
            </Card>
          )}
          {(s.conflicts.length > 0 || s.data_warnings.length > 0) && (
            <Card title="Conflicts & data warnings">
              <ul className="space-y-2 text-sm">
                {s.conflicts.map((c) => (
                  <li key={c.detail} className="flex gap-2 text-warn">
                    <TriangleAlert size={15} className="mt-0.5 shrink-0" aria-hidden />
                    {c.detail}
                  </li>
                ))}
                {s.data_warnings.map((w) => (
                  <li key={w.agent + w.warning} className="flex gap-2 text-muted">
                    <CircleHelp size={15} className="mt-0.5 shrink-0" aria-hidden />
                    <span>
                      <span className="font-medium text-ink">{agentLabel(w.agent)}:</span> {w.warning}
                    </span>
                  </li>
                ))}
              </ul>
            </Card>
          )}
        </div>
      )}

      <p className="font-mono text-[11px] text-subtle">
        report #{report.report_id} · hash {report.report_hash.slice(0, 16)}
        {report.hash_verified !== undefined && (report.hash_verified ? " · hash verified" : " · HASH MISMATCH")} · as of {istDateTime(report.as_of)} IST
      </p>
    </div>
  );
}

export function ReportHistory({ rows }: { rows: ReportHistoryRow[] | null }) {
  return (
    <Card title="Report history" description="Every stored report for this stock, newest first.">
      {rows === null && <div className="skeleton h-24 rounded-lg" />}
      {rows?.length === 0 && <p className="text-sm text-muted">No reports yet.</p>}
      {rows && rows.length > 0 && (
        <ul className="-mx-2 max-h-72 space-y-0.5 overflow-y-auto">
          {rows.map((r) => (
            <li key={r.report_id} className="flex flex-wrap items-center justify-between gap-2 rounded-lg px-2 py-2 text-sm hover:bg-hover">
              <span className="text-muted">
                <span className="font-mono text-xs text-subtle">#{r.report_id}</span> {istDateTime(r.created_at)}
              </span>
              <span className="flex items-center gap-3">
                {r.composite_score !== null && <span className="font-mono text-xs">{r.composite_score.toFixed(1)}</span>}
                <StanceBadge stance={r.stance} />
              </span>
            </li>
          ))}
        </ul>
      )}
    </Card>
  );
}
