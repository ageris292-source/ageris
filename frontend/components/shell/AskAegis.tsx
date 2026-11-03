"use client";

import { ArrowRight, MessageCircle, Send, Sparkles, X } from "lucide-react";
import Link from "next/link";
import { useEffect, useMemo, useRef, useState } from "react";
import { useSession } from "@/components/providers/SessionProvider";
import { NAV } from "@/components/shell/nav";
import { cx } from "@/components/ui/core";
import { api, type RankingRun, type RiskStatus } from "@/lib/api";
import { plainCheck } from "@/lib/plain";

/**
 * "Ask Aegis": a plain-English helper (after GridNova's "Ask GridNova").
 *
 * Honest by construction: answers come from Aegis's own guide plus live
 * system state (latest ranking, risk status). It is not a chatbot, never
 * invents an answer, and never gives investment advice; anything it can't
 * match points to the Help page and the matching screens.
 */

type Link_ = { href: string; label: string };
type Answer = { title: string; body: React.ReactNode; links?: Link_[] };
type Live = { ranking: RankingRun | null | undefined; risk: RiskStatus | null | undefined };

type Topic = {
  id: string;
  question: string;
  keywords: string[];
  answer: (live: Live) => Answer;
};

function blockerSummary(r: RankingRun): string[] {
  const counts = new Map<string, number>();
  for (const row of r.rows ?? []) {
    if (row.qualified || !row.first_failure) continue;
    counts.set(row.first_failure, (counts.get(row.first_failure) ?? 0) + 1);
  }
  return [...counts.entries()]
    .sort((a, b) => b[1] - a[1])
    .slice(0, 3)
    .map(([gate, n]) => `${plainCheck(gate)} (${n} stock${n === 1 ? "" : "s"})`);
}

const TOPICS: Topic[] = [
  {
    id: "start",
    question: "What should I do first?",
    keywords: ["start", "begin", "first", "new", "how", "use", "setup", "guide"],
    answer: () => ({
      title: "Three steps to get going",
      body: (
        <ol className="list-decimal space-y-1.5 pl-5">
          <li><b>Pick stocks.</b> Open Stocks and star the companies you follow.</li>
          <li><b>Run research.</b> On a stock&apos;s page press <i>Run analysis</i>. Seven agents check price, fundamentals, value, risk, news and the market, then explain the bull and bear case.</li>
          <li><b>Practise with paper money.</b> Create a paper portfolio and try trades. Every trade must pass all 24 safety checks and you approve each one.</li>
        </ol>
      ),
      links: [
        { href: "/stocks", label: "Open Stocks" },
        { href: "/paper", label: "Paper trading" },
      ],
    }),
  },
  {
    id: "no-ideas",
    question: "Why are there no trade ideas today?",
    keywords: ["no", "ideas", "opportunities", "qualified", "nothing", "empty", "why", "blocked", "ranking"],
    answer: ({ ranking }) => {
      if (ranking === undefined) return { title: "Checking the latest ranking…", body: "One moment." };
      if (ranking === null)
        return {
          title: "No ranking has run yet",
          body: "Aegis ranks stocks once a day after the market closes. Until the first run, there's nothing to show.",
          links: [{ href: "/ranking", label: "Opportunities" }],
        };
      const top = blockerSummary(ranking);
      return {
        title: ranking.qualified > 0 ? `${ranking.qualified} idea(s) qualified today` : "Nothing qualified today, and that's normal",
        body: (
          <>
            <p>
              Aegis only shows a trade idea when <b>every one of 24 safety checks passes</b>. Unknown counts as fail, so “no trade”
              is a common, honest answer.
            </p>
            {top.length > 0 && (
              <p className="mt-2">
                Most common blockers in the last run: <b>{top.join(", ")}</b>.
              </p>
            )}
            <p className="mt-2 text-muted">
              A frequent cause: prices from a free, unlicensed source can be used for research but never for trading.
            </p>
          </>
        ),
        links: [{ href: "/ranking", label: "See every check" }],
      };
    },
  },
  {
    id: "paper",
    question: "How do I paper trade?",
    keywords: ["paper", "trade", "buy", "sell", "order", "practice", "portfolio"],
    answer: ({ risk }) => ({
      title: "Paper trading in four steps",
      body: (
        <>
          <ol className="list-decimal space-y-1.5 pl-5">
            <li>Create a paper portfolio with pretend cash.</li>
            <li>Open <i>New trade</i>, pick a stock, a price and a stop-loss.</li>
            <li>Aegis runs the 24 checks and shows each result in plain words.</li>
            <li>If everything passes, <b>you</b> approve the order; it fills at a realistic simulated price.</li>
          </ol>
          {risk && !risk.paper_orders_permitted && (
            <p className="mt-2 text-warn">Right now paper orders are switched off (see System). An admin can enable paper mode.</p>
          )}
        </>
      ),
      links: [
        { href: "/trade", label: "New trade" },
        { href: "/paper", label: "Paper portfolio" },
      ],
    }),
  },
  {
    id: "safe",
    question: "Can Aegis lose real money?",
    keywords: ["real", "money", "live", "risk", "safe", "lose", "broker", "account"],
    answer: () => ({
      title: "No. Live trading is switched off",
      body: (
        <p>
          Aegis has no connection to a real broker. It does research and <b>paper</b> (pretend) trading only, and even paper orders
          need your approval after all 24 checks pass. Nothing here is investment advice.
        </p>
      ),
      links: [{ href: "/legal#disclaimer", label: "Risk disclaimer" }],
    }),
  },
  {
    id: "model",
    question: "How does the AI model work?",
    keywords: ["ai", "model", "ml", "machine", "learning", "predict", "probability", "accuracy", "backtest"],
    answer: () => ({
      title: "A tested model, never the final say",
      body: (
        <>
          <p>
            The model estimates the chance a stock rises over the next 20 trading days. It is trained only on the past and tested on
            later periods it never saw (walk-forward).
          </p>
          <p className="mt-2">
            It can be switched on only if it <b>beats simple baselines</b> (for example “always guess the average”), stays calibrated and
            works across most test periods. Even then, the 24 safety checks decide, not the model.
          </p>
        </>
      ),
      links: [{ href: "/backtests", label: "Backtests & model" }],
    }),
  },
  {
    id: "agents",
    question: "What do the research agents do?",
    keywords: ["agent", "agents", "research", "analysis", "stance", "bull", "bear", "report", "news"],
    answer: () => ({
      title: "Seven specialists, one honest summary",
      body: (
        <>
          <p>
            Technical, fundamental, valuation, risk, news, macro and portfolio agents each score one angle and show their evidence. Aegis
            combines them into a bull case, a bear case and a stance.
          </p>
          <p className="mt-2">
            <b>Risk is a veto</b>: high risk rules out a positive view, however good the rest looks. An agent that is switched off (like
            news sentiment on small servers) is marked “not active” and doesn&apos;t count.
          </p>
        </>
      ),
      links: [{ href: "/stocks", label: "Research a stock" }],
    }),
  },
];

function score(q: string, t: Topic): number {
  const words = q.toLowerCase().split(/[^a-z0-9]+/).filter((w) => w.length > 1);
  return words.reduce((n, w) => n + (t.keywords.includes(w) ? 1 : 0), 0);
}

function pageMatches(q: string, isAdmin: boolean) {
  const needle = q.toLowerCase();
  return NAV.flatMap((g) => g.items)
    .filter((i) => !i.adminOnly || isAdmin)
    .filter((i) => needle.split(/\s+/).some((w) => w.length > 2 && `${i.label} ${i.keywords ?? ""}`.toLowerCase().includes(w)))
    .slice(0, 3);
}

export function AskAegis() {
  const { guard, isAdmin } = useSession();
  const [open, setOpen] = useState(false);
  const [q, setQ] = useState("");
  const [active, setActive] = useState<{ topic?: Topic; asked?: string } | null>(null);
  const [live, setLive] = useState<Live>({ ranking: undefined, risk: undefined });
  const input = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (!open) return;
    guard((t) => api.latestRanking(t))
      .then((r) => setLive((l) => ({ ...l, ranking: r ?? null })))
      .catch(() => setLive((l) => ({ ...l, ranking: null })));
    guard((t) => api.riskStatus(t))
      .then((r) => setLive((l) => ({ ...l, risk: r ?? null })))
      .catch(() => setLive((l) => ({ ...l, risk: null })));
    const esc = (e: KeyboardEvent) => e.key === "Escape" && setOpen(false);
    document.addEventListener("keydown", esc);
    setTimeout(() => input.current?.focus(), 50);
    return () => document.removeEventListener("keydown", esc);
  }, [open, guard]);

  const answer = useMemo(() => (active?.topic ? active.topic.answer(live) : null), [active, live]);
  const pages = active?.asked ? pageMatches(active.asked, isAdmin) : [];

  function ask(e: React.FormEvent) {
    e.preventDefault();
    const text = q.trim();
    if (!text) return;
    const best = [...TOPICS].sort((a, b) => score(text, b) - score(text, a))[0];
    setActive({ topic: score(text, best) > 0 ? best : undefined, asked: text });
    setQ("");
  }

  return (
    <>
      <button
        onClick={() => setOpen((v) => !v)}
        aria-expanded={open}
        aria-haspopup="dialog"
        className="glass fixed bottom-[calc(5.75rem+env(safe-area-inset-bottom))] right-4 z-40 inline-flex h-12 min-w-12 items-center justify-center gap-2 rounded-full border border-[var(--glass-border)] bg-accent px-3.5 text-sm sm:px-4 font-semibold text-on-accent shadow-[var(--shadow-glass)] transition-transform hover:-translate-y-0.5 active:scale-95 lg:bottom-6 lg:right-6"
      >
        {open ? <X size={18} aria-hidden /> : <MessageCircle size={18} aria-hidden />}
        <span className="sr-only sm:not-sr-only">{open ? "Close" : "Ask Aegis"}</span>
      </button>

      {open && (
        <div
          role="dialog"
          aria-label="Ask Aegis"
          className="animate-sheet fixed inset-x-3 bottom-[calc(9.75rem+env(safe-area-inset-bottom))] z-40 flex max-h-[min(70dvh,560px)] flex-col overflow-hidden rounded-3xl border border-line bg-elevated shadow-[var(--shadow-pop)] sm:left-auto sm:w-[400px] lg:bottom-24 lg:right-6"
        >
          <div className="hero-card shrink-0 rounded-none border-0 px-5 py-4">
            <div className="relative z-10 flex items-center gap-2">
              <Sparkles size={16} aria-hidden />
              <p className="font-semibold">Ask Aegis</p>
            </div>
            <p className="relative z-10 mt-1 text-[13px] text-[var(--hero-text-muted)]">
              Plain answers from Aegis&apos;s guide and live status. Not investment advice.
            </p>
          </div>

          <div className="min-h-0 flex-1 space-y-4 overflow-y-auto px-5 py-4 text-sm leading-relaxed">
            {active?.asked && <p className="ml-auto w-fit max-w-[85%] rounded-2xl rounded-br-md bg-accent-soft px-3 py-2 text-ink">{active.asked}</p>}
            {answer && (
              <div className="rounded-2xl rounded-bl-md bg-sunken px-4 py-3">
                <p className="mb-1.5 font-semibold">{answer.title}</p>
                <div className="text-[13.5px] text-ink">{answer.body}</div>
                {answer.links && (
                  <div className="mt-3 flex flex-wrap gap-2">
                    {answer.links.map((l) => (
                      <Link key={l.href} href={l.href} onClick={() => setOpen(false)} className="inline-flex items-center gap-1 rounded-full bg-accent px-3 py-1.5 text-xs font-semibold text-on-accent">
                        {l.label} <ArrowRight size={12} aria-hidden />
                      </Link>
                    ))}
                  </div>
                )}
              </div>
            )}
            {active?.asked && !active.topic && (
              <div className="rounded-2xl rounded-bl-md bg-sunken px-4 py-3">
                <p className="font-semibold">I don&apos;t have a guide answer for that</p>
                <p className="mt-1 text-[13px] text-muted">I only answer from Aegis&apos;s own guide, so I won&apos;t guess. Try one of these:</p>
                <div className="mt-3 flex flex-wrap gap-2">
                  {[...pages, { href: "/help", label: "Help & FAQ" }].map((p) => (
                    <Link key={p.href + p.label} href={p.href} onClick={() => setOpen(false)} className="inline-flex items-center gap-1 rounded-full border border-line px-3 py-1.5 text-xs font-semibold">
                      {p.label} <ArrowRight size={12} aria-hidden />
                    </Link>
                  ))}
                </div>
              </div>
            )}
            <div>
              <p className="micro-label mb-2 text-subtle">{active ? "More questions" : "Popular questions"}</p>
              <div className="flex flex-wrap gap-2">
                {TOPICS.filter((t) => t.id !== active?.topic?.id).map((t) => (
                  <button
                    key={t.id}
                    onClick={() => setActive({ topic: t, asked: t.question })}
                    className="rounded-full border border-line px-3 py-1.5 text-left text-xs font-medium text-ink hover:border-accent hover:text-accent"
                  >
                    {t.question}
                  </button>
                ))}
              </div>
            </div>
          </div>

          <form onSubmit={ask} className="flex shrink-0 gap-2 border-t border-line p-3">
            <input
              ref={input}
              value={q}
              onChange={(e) => setQ(e.target.value)}
              placeholder="Ask a question…"
              aria-label="Your question"
              className="h-11 min-w-0 flex-1 rounded-xl border border-line bg-sunken px-3 text-base text-ink placeholder:text-subtle focus:border-accent focus:outline-none sm:text-sm"
            />
            <button type="submit" aria-label="Ask" disabled={!q.trim()} className={cx("flex h-11 w-11 items-center justify-center rounded-xl bg-accent text-on-accent", !q.trim() && "opacity-40")}>
              <Send size={16} aria-hidden />
            </button>
          </form>
        </div>
      )}
    </>
  );
}
