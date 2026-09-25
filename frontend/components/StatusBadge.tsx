import type { Freshness, GateStatus } from "@/lib/api";

// Status is never color alone: every badge carries an icon glyph and a word.
const STYLE: Record<GateStatus, { cls: string; icon: string; word: string }> = {
  PASS: { cls: "border-pass/40 text-pass", icon: "✓", word: "Fresh" },
  FAIL: { cls: "border-fail/40 text-fail", icon: "✕", word: "Stale" },
  UNKNOWN: { cls: "border-unknown/40 text-unknown", icon: "?", word: "Unknown" },
};

export function FreshnessBadge({ f }: { f: Freshness }) {
  const s = STYLE[f.status];
  const word = f.status === "FAIL" && f.latest_session === null ? "No data" : s.word;
  return (
    <span
      className={`inline-flex items-center gap-1 rounded border px-1.5 py-0.5 text-xs ${s.cls}`}
      title={f.reason}
    >
      <span aria-hidden>{s.icon}</span>
      {word}
    </span>
  );
}

export function QualityBadge({
  usable,
  score,
  threshold,
}: {
  usable: boolean;
  score: number;
  threshold: number;
}) {
  // Usable-but-low-score (e.g. short history) is amber, never a green tick.
  const [cls, icon, word] = !usable
    ? ["border-fail/40 text-fail", "✕", "Unusable"]
    : score >= threshold
      ? ["border-pass/40 text-pass", "✓", "Quality"]
      : ["border-unknown/40 text-unknown", "!", "Limited"];
  return (
    <span className={`inline-flex items-center gap-1 rounded border px-1.5 py-0.5 text-xs ${cls}`}>
      <span aria-hidden>{icon}</span>
      {word} · {(score * 100).toFixed(1)}%
    </span>
  );
}
