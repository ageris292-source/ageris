import type { AgentOutput } from "@/lib/api";

const DIR = {
  bullish: { icon: "▲", cls: "text-pass", word: "Bullish" },
  bearish: { icon: "▼", cls: "text-fail", word: "Bearish" },
  neutral: { icon: "●", cls: "text-muted", word: "Neutral" },
} as const;

const STATUS_TEXT: Record<AgentOutput["status"], string> = {
  ok: "",
  insufficient_data: "Not enough history",
  data_unusable: "Data failed validation",
  failed: "Analysis error",
};

function tilt(score: number) {
  if (score >= 60) return { word: "Bullish tilt", cls: "text-pass" };
  if (score <= 40) return { word: "Bearish tilt", cls: "text-fail" };
  return { word: "No clear tilt", cls: "text-muted" };
}

export function TechnicalPanel({
  out,
  busy,
  onRun,
}: {
  out: AgentOutput | null;
  busy: boolean;
  onRun: () => void;
}) {
  return (
    <section className="mb-4 rounded-lg border border-line bg-panel p-5">
      <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
        <h3 className="text-xs font-semibold uppercase tracking-wider text-muted">
          Technical analysis
        </h3>
        <button
          className="rounded border border-line px-2.5 py-1 text-xs disabled:opacity-40"
          onClick={onRun}
          disabled={busy}
        >
          {busy ? "Analysing…" : "Re-run"}
        </button>
      </div>

      {!out && <p className="text-sm text-muted">{busy ? "Running…" : "Not run yet."}</p>}

      {out && out.status !== "ok" && (
        <div className="rounded border border-unknown/40 bg-unknown/10 px-4 py-3 text-sm text-unknown">
          <p className="font-medium">
            <span aria-hidden>! </span>
            {STATUS_TEXT[out.status]} — no score produced
          </p>
          {out.warnings.map((w) => (
            <p key={w} className="mt-1 text-xs">{w}</p>
          ))}
        </div>
      )}

      {out && out.status === "ok" && out.score !== null && (
        <>
          <div className="mb-4 grid gap-4 sm:grid-cols-3">
            <div>
              <div className="text-xs text-muted">Technical score</div>
              <div className="font-mono text-3xl">{out.score.toFixed(0)}<span className="text-base text-muted">/100</span></div>
              <div className={`text-sm ${tilt(out.score).cls}`}>{tilt(out.score).word}</div>
            </div>
            <div>
              <div className="text-xs text-muted">Signal agreement</div>
              <div className="font-mono text-3xl">{Math.round(out.confidence * 100)}%</div>
              <div className="text-xs text-muted">Heuristic, not calibrated</div>
            </div>
            <div className="text-xs text-muted sm:text-right">
              <p>{out.score_basis}</p>
            </div>
          </div>

          <ul className="mb-4 divide-y divide-line text-sm">
            {out.signals.map((s) => {
              const d = DIR[s.direction];
              return (
                <li key={s.name} className="flex gap-3 py-2">
                  <span className={`w-20 shrink-0 text-xs ${d.cls}`}>
                    <span aria-hidden>{d.icon} </span>
                    {d.word}
                  </span>
                  <span className="w-28 shrink-0 text-xs text-muted">{s.category.replace("_", " ")}</span>
                  <span className="flex-1">{s.detail}</span>
                  <span className="w-10 shrink-0 text-right font-mono text-xs text-muted" title="Signal strength">
                    {Math.round(s.strength * 100)}
                  </span>
                </li>
              );
            })}
          </ul>

          <div className="grid gap-4 md:grid-cols-2">
            <div>
              <h4 className="mb-1 text-xs font-semibold uppercase tracking-wider text-muted">
                Invalidation
              </h4>
              <ul className="list-disc space-y-1 pl-4 text-sm">
                {out.invalidation_conditions.map((c) => <li key={c}>{c}</li>)}
              </ul>
            </div>
            <div>
              <h4 className="mb-1 text-xs font-semibold uppercase tracking-wider text-muted">Risks</h4>
              {out.risks.length ? (
                <ul className="list-disc space-y-1 pl-4 text-sm">
                  {out.risks.map((r) => <li key={r}>{r}</li>)}
                </ul>
              ) : (
                <p className="text-sm text-muted">None flagged by technical rules.</p>
              )}
            </div>
          </div>

          {out.warnings.length > 0 && (
            <ul className="mt-4 space-y-1 text-xs text-unknown">
              {out.warnings.map((w) => (
                <li key={w}><span aria-hidden>! </span>{w}</li>
              ))}
            </ul>
          )}
        </>
      )}

      {out && (
        <p className="mt-4 font-mono text-[11px] text-muted">
          as of {new Date(out.as_of).toLocaleString("en-IN", { timeZone: "Asia/Kolkata" })} IST ·{" "}
          {out.agent_version} · snapshot {out.data_snapshot_id?.slice(0, 12) ?? "—"}
        </p>
      )}
    </section>
  );
}
