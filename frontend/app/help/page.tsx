"use client";

import { BookOpen, ChevronDown, Compass, LifeBuoy, ScrollText, Search } from "lucide-react";
import Link from "next/link";
import { useMemo, useState } from "react";
import { usePageTitle } from "@/components/usePageTitle";
import { Button, Card, Input, PageHeader } from "@/components/ui/core";

const START = [
  { href: "/stocks", title: "Find a stock", body: "Search the universe, open a company, fetch prices and run a research report." },
  { href: "/ranking", title: "See today's ideas", body: "The daily ranking runs every stock through the risk engine and lists those that qualify." },
  { href: "/trade", title: "Evaluate a trade", body: "Enter entry, stop and target. See all 24 gates, costs and the decision." },
  { href: "/paper", title: "Practise with paper money", body: "An admin approves each order. Track positions, theses and performance." },
];

const FAQ: { q: string; a: React.ReactNode; tags: string }[] = [
  {
    q: "Does Aegis trade real money?",
    a: "No. Live trading is disabled in code and configuration. Aegis does research and paper (simulated) trading only, and every paper order needs a human admin's approval.",
    tags: "live broker real money",
  },
  {
    q: "Who decides whether a trade is allowed?",
    a: "Only the Trade Risk Engine: 24 deterministic gates covering data freshness, liquidity, position and sector limits, loss limits, the kill switch and more. The AI agents provide research. They are never the authority on a trade.",
    tags: "gates engine approve ai llm",
  },
  {
    q: "Why does a value show “—” or “unknown”?",
    a: "Aegis never invents data. If a figure is missing, stale or can't be computed, it is shown as unknown, and anything that depends on it fails closed (an UNKNOWN gate never passes).",
    tags: "missing unknown stale data dash",
  },
  {
    q: "How fresh are prices?",
    a: "Prices are end-of-day. They refresh each weekday evening after the NSE/BSE close. The Data tab on each stock shows the source, when it became known, and quality checks.",
    tags: "price freshness end of day eod intraday",
  },
  {
    q: "How do price alerts work?",
    a: (
      <>
        Set a rule on a stock&apos;s <em>Notes &amp; alerts</em> tab or on <Link href="/alerts#price-alerts" className="-my-2 inline-block py-2 text-accent hover:underline">Alerts → My price alerts</Link>: close above or below a price, a daily move of at least X%, or RSI(14) above or below a level. Rules are checked against each new daily close. If the stock&apos;s data is stale, the rule waits rather than guessing. A one-shot rule switches off after it fires; a repeating rule fires again only after the condition has cleared. High-importance rules are also pushed to Telegram or email when your admin has set those channels up.
      </>
    ),
    tags: "price alert notification rsi telegram email",
  },
  {
    q: "What are watchlists for?",
    a: "They're personal lists of stocks you follow, shown on your dashboard with the last close, the day's change and a 30-day trend. You can create several lists (for example “Banks” or “Swing ideas”). The star on a stock adds it to your first list; the stock's Notes & alerts tab lets you pick any list.",
    tags: "watchlist star list",
  },
  {
    q: "Who can see my journal and notes?",
    a: "Only you. Admins can see that an entry was created in the activity log, but never its text.",
    tags: "journal notes private privacy",
  },
  {
    q: "What does the Performance tab measure?",
    a: "Win rate, profit factor and average win or loss use closed (sold) paper trades. Drawdown and total return use the daily equity marks. The NIFTY 50 comparison uses the stored index series over the same dates, and it is hidden if that series isn't stored.",
    tags: "performance win rate drawdown nifty benchmark",
  },
  {
    q: "How do I export my data?",
    a: "CSV downloads are on Account (watchlist, journal, price alerts, activity), on Paper trading → Performance (orders, fills, positions, equity), on Journal, and on the Activity log.",
    tags: "export csv excel download",
  },
  {
    q: "I think someone else used my account. What should I do?",
    a: (
      <>
        Go to <Link href="/account" className="-my-2 inline-block py-2 text-accent hover:underline">Account</Link>, check <em>Sign-in activity</em>, change your password and press <em>Sign out everywhere</em>. Every other session ends immediately.
      </>
    ),
    tags: "security password hacked sign out sessions",
  },
  {
    q: "How do I install Aegis on my phone?",
    a: "On iPhone, open Aegis in Safari, tap Share, then Add to Home Screen. On Android, open it in Chrome, open the ⋮ menu, then Install app. It opens full screen like a normal app.",
    tags: "install phone app pwa home screen mobile",
  },
  {
    q: "How do I get an account for someone else?",
    a: "Aegis is invite-only. An admin invites people on the Users page. They get a one-time password and must choose their own at first sign-in.",
    tags: "invite user account team admin",
  },
];

const GLOSSARY: [string, string][] = [
  ["Stance", "The research report's overall view (e.g. bullish or bearish), based on every agent's score and confidence."],
  ["Composite score", "A weighted blend of the agents' scores on a 0–100 scale, where 50 is neutral. It is shown only when enough agents have usable data."],
  ["Gate", "One rule in the Trade Risk Engine. Every gate must PASS for a trade to be approved."],
  ["Kill switch", "Halts all trading at once. Anyone can halt; only an admin can resume."],
  ["Thesis", "The plan recorded with a paper position: entry, stop-loss, target, time horizon and invalidation conditions."],
  ["RSI(14)", "Relative Strength Index over 14 sessions (Wilder). Above 70 is often called overbought, below 30 oversold."],
  ["Drawdown", "The fall from a previous peak, in percent."],
  ["Profit factor", "Gross profit from winning trades divided by gross loss from losing trades. Above 1 means winners outweighed losers."],
  ["Point-in-time", "Research only uses data that was actually available at the time (as_of), so backtests can't peek into the future."],
];

export default function HelpPage() {
  usePageTitle("Help");
  const [q, setQ] = useState("");
  const faq = useMemo(() => {
    const t = q.trim().toLowerCase();
    if (!t) return FAQ;
    return FAQ.filter((f) => (f.q + " " + f.tags + " " + (typeof f.a === "string" ? f.a : "")).toLowerCase().includes(t));
  }, [q]);

  return (
    <div className="space-y-6">
      <PageHeader
        title="Help"
        description="How Aegis works, answers to common questions, and a glossary."
        actions={
          <Button icon={<Compass size={15} />} onClick={() => window.dispatchEvent(new Event("aegis:welcome"))}>
            Show welcome guide
          </Button>
        }
      />

      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 xl:grid-cols-4">
        {START.map((s, i) => (
          <Link key={s.href} href={s.href} className="rounded-xl border border-line bg-panel p-4 shadow-[var(--shadow-card)] transition-colors hover:border-line-strong">
            <span className="text-xs font-semibold text-accent">Step {i + 1}</span>
            <p className="mt-1 text-sm font-semibold">{s.title}</p>
            <p className="mt-1 text-xs text-muted">{s.body}</p>
          </Link>
        ))}
      </div>

      <div className="grid gap-6 xl:grid-cols-3">
        <Card className="xl:col-span-2" title={<span className="flex items-center gap-2"><LifeBuoy size={15} aria-hidden /> Questions</span>}>
          <div className="relative mb-4">
            <Search size={15} className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-subtle" aria-hidden />
            <Input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Search help…" aria-label="Search help" className="pl-9" />
          </div>
          {faq.length === 0 && <p className="py-6 text-center text-sm text-muted">No answers match. Try other words.</p>}
          <div className="divide-y divide-line rounded-lg border border-line">
            {faq.map((f) => (
              <details key={f.q} className="group">
                <summary className="flex cursor-pointer list-none items-center gap-3 px-4 py-3.5 text-sm font-medium hover:bg-hover [&::-webkit-details-marker]:hidden">
                  <span className="flex-1">{f.q}</span>
                  <ChevronDown size={16} className="shrink-0 text-subtle transition-transform group-open:rotate-180" aria-hidden />
                </summary>
                <div className="px-4 pb-4 text-sm leading-relaxed text-muted">{f.a}</div>
              </details>
            ))}
          </div>
        </Card>

        <div className="min-w-0 space-y-6">
          <Card title={<span className="flex items-center gap-2"><BookOpen size={15} aria-hidden /> Glossary</span>}>
            <dl className="space-y-3 text-sm">
              {GLOSSARY.map(([t, d]) => (
                <div key={t}>
                  <dt className="font-medium">{t}</dt>
                  <dd className="text-xs leading-relaxed text-muted">{d}</dd>
                </div>
              ))}
            </dl>
          </Card>
          <Card title={<span className="flex items-center gap-2"><ScrollText size={15} aria-hidden /> Policies</span>}>
            <ul className="space-y-1 text-sm">
              <li><Link href="/legal#disclaimer" className="inline-block py-2 text-accent hover:underline">Risk disclaimer</Link></li>
              <li><Link href="/legal#terms" className="inline-block py-2 text-accent hover:underline">Terms of use</Link></li>
              <li><Link href="/legal#privacy" className="inline-block py-2 text-accent hover:underline">Privacy: what Aegis stores</Link></li>
              <li><Link href="/system" className="inline-block py-2 text-accent hover:underline">How Aegis decides (System)</Link></li>
            </ul>
          </Card>
        </div>
      </div>
    </div>
  );
}
