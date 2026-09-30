"use client";

import { CheckCircle2, CircleDashed, CircleHelp, MinusCircle, TrendingDown, TrendingUp, XCircle, Minus } from "lucide-react";
import type { Freshness, GateStatus, Stance, TradeGateStatus } from "@/lib/api";
import { Badge, cx, type Tone } from "@/components/ui/core";

// Status is never colour alone: every badge carries an icon and a word.

export function GateBadge({ s, label }: { s: TradeGateStatus | "WARN" | null | undefined; label?: string }) {
  if (!s) return <Badge icon={<CircleDashed size={12} aria-hidden />}>{label ?? "Not checked"}</Badge>;
  const map: Record<string, [Tone, React.ReactNode, string]> = {
    PASS: ["pass", <CheckCircle2 key="i" size={12} aria-hidden />, "Pass"],
    FAIL: ["fail", <XCircle key="i" size={12} aria-hidden />, "Fail"],
    UNKNOWN: ["warn", <CircleHelp key="i" size={12} aria-hidden />, "Unknown"],
    WARN: ["warn", <CircleHelp key="i" size={12} aria-hidden />, "Warning"],
    NOT_APPLICABLE: ["neutral", <MinusCircle key="i" size={12} aria-hidden />, "N/A"],
  };
  const [tone, icon, word] = map[s];
  return (
    <Badge tone={tone} icon={icon}>
      {label ?? word}
    </Badge>
  );
}

export function FreshnessBadge({ f }: { f: Freshness | GateStatus }) {
  const status = typeof f === "string" ? f : f.status;
  const noData = typeof f !== "string" && f.status === "FAIL" && f.latest_session === null;
  const word = noData ? "No data" : status === "PASS" ? "Fresh" : status === "FAIL" ? "Stale" : "Unknown";
  const tone: Tone = status === "PASS" ? "pass" : status === "FAIL" ? "fail" : "warn";
  const icon =
    status === "PASS" ? <CheckCircle2 size={12} aria-hidden /> : status === "FAIL" ? <XCircle size={12} aria-hidden /> : <CircleHelp size={12} aria-hidden />;
  return (
    <Badge tone={noData ? "neutral" : tone} icon={icon} title={typeof f === "string" ? undefined : f.reason}>
      {word}
    </Badge>
  );
}

export function QualityBadge({ usable, score, threshold }: { usable: boolean; score: number; threshold: number }) {
  // Usable-but-low-score (e.g. short history) is amber, never a green tick.
  const [tone, word]: [Tone, string] = !usable ? ["fail", "Unusable"] : score >= threshold ? ["pass", "Quality"] : ["warn", "Limited"];
  return (
    <Badge tone={tone} icon={tone === "pass" ? <CheckCircle2 size={12} aria-hidden /> : tone === "fail" ? <XCircle size={12} aria-hidden /> : <CircleHelp size={12} aria-hidden />}>
      {word} · {(score * 100).toFixed(1)}%
    </Badge>
  );
}

export const STANCE: Record<Stance, { tone: Tone; word: string; icon: React.ReactNode }> = {
  POSITIVE_TILT: { tone: "pass", word: "Positive tilt", icon: <TrendingUp size={12} aria-hidden /> },
  NEGATIVE_TILT: { tone: "fail", word: "Negative tilt", icon: <TrendingDown size={12} aria-hidden /> },
  NO_CLEAR_TILT: { tone: "neutral", word: "No clear tilt", icon: <Minus size={12} aria-hidden /> },
  INSUFFICIENT_DATA: { tone: "warn", word: "Insufficient data", icon: <CircleHelp size={12} aria-hidden /> },
};

export function StanceBadge({ stance }: { stance: Stance | null | undefined }) {
  if (!stance) return <Badge icon={<CircleDashed size={12} aria-hidden />}>No report</Badge>;
  const s = STANCE[stance];
  return (
    <Badge tone={s.tone} icon={s.icon}>
      {s.word}
    </Badge>
  );
}

export function tiltOf(score: number | null | undefined): { word: string; tone: Tone; cls: string } {
  if (score === null || score === undefined) return { word: "No score", tone: "neutral", cls: "text-muted" };
  if (score >= 60) return { word: "Bullish tilt", tone: "pass", cls: "text-pass" };
  if (score <= 40) return { word: "Bearish tilt", tone: "fail", cls: "text-fail" };
  return { word: "No clear tilt", tone: "neutral", cls: "text-muted" };
}

/** 0–100 score on a track with the neutral 50 marked. Diverging around 50:
 *  the fill runs from the midpoint toward the score. */
export function ScoreBar({ score, className, showValue = true }: { score: number | null | undefined; className?: string; showValue?: boolean }) {
  if (score === null || score === undefined) {
    return <div className={cx("flex items-center gap-2 text-xs text-subtle", className)}>—</div>;
  }
  const s = Math.max(0, Math.min(100, score));
  const left = Math.min(s, 50);
  const width = Math.abs(s - 50);
  const color = s >= 60 ? "var(--pass)" : s <= 40 ? "var(--fail)" : "var(--subtle)";
  return (
    <div className={cx("flex items-center gap-2", className)}>
      <div className="relative h-1.5 flex-1 rounded-full bg-sunken" role="meter" aria-valuemin={0} aria-valuemax={100} aria-valuenow={Math.round(s)} aria-label="Score">
        <div className="absolute inset-y-0 rounded-full" style={{ left: `${left}%`, width: `${Math.max(width, 1)}%`, background: color }} />
        <div className="absolute -top-0.5 h-2.5 w-px bg-line-strong" style={{ left: "50%" }} aria-hidden />
      </div>
      {showValue && <span className="w-8 text-right font-mono text-xs tabular-nums">{s.toFixed(0)}</span>}
    </div>
  );
}

/** Large circular score for hero spots. */
export function ScoreRing({ score, size = 88, label }: { score: number | null | undefined; size?: number; label?: string }) {
  const r = size / 2 - 7;
  const c = 2 * Math.PI * r;
  const s = score === null || score === undefined ? null : Math.max(0, Math.min(100, score));
  const color = s === null ? "var(--subtle)" : s >= 60 ? "var(--pass)" : s <= 40 ? "var(--fail)" : "var(--accent)";
  return (
    <div className="relative shrink-0" style={{ width: size, height: size }}>
      <svg width={size} height={size} viewBox={`0 0 ${size} ${size}`} aria-hidden>
        <circle cx={size / 2} cy={size / 2} r={r} fill="none" stroke="var(--sunken)" strokeWidth={7} />
        {s !== null && (
          <circle
            cx={size / 2}
            cy={size / 2}
            r={r}
            fill="none"
            stroke={color}
            strokeWidth={7}
            strokeLinecap="round"
            strokeDasharray={`${(s / 100) * c} ${c}`}
            transform={`rotate(-90 ${size / 2} ${size / 2})`}
          />
        )}
      </svg>
      <div className="absolute inset-0 flex flex-col items-center justify-center">
        <span className="text-xl font-semibold tabular-nums">{s === null ? "—" : s.toFixed(0)}</span>
        {label && <span className="text-[10px] text-muted">{label}</span>}
      </div>
    </div>
  );
}
