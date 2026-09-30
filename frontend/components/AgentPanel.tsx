"use client";

import { CircleHelp, Minus, RefreshCw, TrendingDown, TrendingUp, TriangleAlert } from "lucide-react";
import type { AgentOutput } from "@/lib/api";
import { Button, Callout, Card, LoadingRows, SectionLabel, cx } from "@/components/ui/core";
import { ScoreRing, tiltOf } from "@/components/ui/Status";
import { humanize, istDateTime } from "@/lib/format";

const DIR = {
  bullish: { icon: <TrendingUp size={14} aria-hidden />, cls: "text-pass", word: "Bullish" },
  bearish: { icon: <TrendingDown size={14} aria-hidden />, cls: "text-fail", word: "Bearish" },
  neutral: { icon: <Minus size={14} aria-hidden />, cls: "text-muted", word: "Neutral" },
} as const;

const STATUS_TEXT: Record<AgentOutput["status"], string> = {
  ok: "",
  insufficient_data: "Not enough history",
  data_unusable: "Data failed validation",
  failed: "Analysis error",
};

/** One agent's output: score, the signals behind it, what would invalidate it. */
export function AgentPanel({
  out,
  busy,
  onRun,
  title,
  scoreLabel = "Score",
  runLabel = "Re-run",
  description,
  children,
}: {
  out: AgentOutput | null;
  busy: boolean;
  onRun?: () => void;
  title: string;
  scoreLabel?: string;
  runLabel?: string;
  description?: React.ReactNode;
  children?: React.ReactNode;
}) {
  const t = tiltOf(out?.score);
  return (
    <Card
      title={title}
      description={description}
      actions={
        onRun && (
          <Button size="sm" onClick={onRun} loading={busy} icon={<RefreshCw size={13} />}>
            {busy ? "Working…" : runLabel}
          </Button>
        )
      }
    >
      {!out && (busy ? <LoadingRows rows={4} /> : <p className="text-sm text-muted">Not run yet.</p>)}

      {out && out.status !== "ok" && (
        <Callout tone="warn" icon={<CircleHelp size={16} />} title={`${STATUS_TEXT[out.status]} — no score produced`}>
          {out.warnings.map((w) => (
            <p key={w}>{w}</p>
          ))}
        </Callout>
      )}

      {out && out.status === "ok" && out.score !== null && (
        <div className="space-y-6">
          <div className="flex flex-wrap items-center gap-6">
            <ScoreRing score={out.score} label="/ 100" />
            <div className="min-w-0 flex-1">
              <div className="text-xs text-muted">{scoreLabel}</div>
              <div className={cx("text-lg font-semibold", t.cls)}>{t.word}</div>
              <div className="mt-1 text-xs text-muted">
                Signal agreement <span className="font-mono text-ink">{Math.round(out.confidence * 100)}%</span>
                <span className="text-subtle"> · heuristic, not calibrated</span>
              </div>
              <p className="mt-2 text-xs text-subtle">{out.score_basis}</p>
            </div>
          </div>

          {children}

          {out.signals.length > 0 && (
            <div>
              <SectionLabel>Signals</SectionLabel>
              <ul className="divide-y divide-line rounded-lg border border-line">
                {out.signals.map((s) => {
                  const d = DIR[s.direction];
                  return (
                    <li key={s.name} className="flex flex-wrap items-center gap-x-3 gap-y-1 px-3 py-2.5 text-sm">
                      <span className={cx("inline-flex w-24 shrink-0 items-center gap-1 text-xs font-medium", d.cls)}>
                        {d.icon}
                        {d.word}
                      </span>
                      <span className="min-w-0 flex-1">{s.detail}</span>
                      <span className="text-xs text-subtle">{humanize(s.category)}</span>
                      <span className="w-16 shrink-0" title={`Strength ${Math.round(s.strength * 100)}`}>
                        <span className="block h-1.5 rounded-full bg-sunken">
                          <span className="block h-1.5 rounded-full bg-line-strong" style={{ width: `${Math.round(s.strength * 100)}%` }} />
                        </span>
                      </span>
                    </li>
                  );
                })}
              </ul>
            </div>
          )}

          <div className="grid gap-6 md:grid-cols-2">
            <div>
              <SectionLabel>What would invalidate this</SectionLabel>
              {out.invalidation_conditions.length ? (
                <ul className="list-disc space-y-1 pl-4 text-sm text-muted marker:text-subtle">
                  {out.invalidation_conditions.map((c) => (
                    <li key={c}>{c}</li>
                  ))}
                </ul>
              ) : (
                <p className="text-sm text-subtle">None stated.</p>
              )}
            </div>
            <div>
              <SectionLabel>Risks</SectionLabel>
              {out.risks.length ? (
                <ul className="list-disc space-y-1 pl-4 text-sm text-muted marker:text-subtle">
                  {out.risks.map((r) => (
                    <li key={r}>{r}</li>
                  ))}
                </ul>
              ) : (
                <p className="text-sm text-subtle">None flagged by this agent.</p>
              )}
            </div>
          </div>

          {out.warnings.length > 0 && (
            <ul className="space-y-1 text-xs text-warn">
              {out.warnings.map((w) => (
                <li key={w} className="flex gap-1.5">
                  <TriangleAlert size={13} className="mt-0.5 shrink-0" aria-hidden />
                  {w}
                </li>
              ))}
            </ul>
          )}
        </div>
      )}

      {out && out.status !== "ok" && children && <div className="mt-4">{children}</div>}

      {out && (
        <p className="mt-5 border-t border-line pt-3 font-mono text-[11px] text-subtle">
          as of {istDateTime(out.as_of)} IST · {out.agent_version} · snapshot {out.data_snapshot_id?.slice(0, 12) ?? "—"}
        </p>
      )}
    </Card>
  );
}
