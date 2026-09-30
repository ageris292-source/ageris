"use client";

import { BellRing, LineChart, NotebookPen, ShieldCheck, Sparkles } from "lucide-react";
import { useEffect, useState } from "react";
import { useSession } from "@/components/providers/SessionProvider";
import { Dialog } from "@/components/ui/Dialog";
import { Button, cx } from "@/components/ui/core";

const STEPS = [
  {
    icon: <Sparkles size={22} />,
    title: "Welcome to Aegis",
    body: "Aegis researches Indian stocks (NSE and BSE) with several specialist agents, and lets you practise with simulated money. It never trades real money: live trading is off.",
  },
  {
    icon: <LineChart size={22} />,
    title: "Research a stock",
    body: "Open Stocks, pick a company and run a research report. Each agent (technical, fundamentals, news, valuation, macro, risk) shows its evidence. When data is missing or stale, Aegis says so instead of guessing.",
  },
  {
    icon: <ShieldCheck size={22} />,
    title: "Every trade passes 24 gates",
    body: "Propose a trade on New trade. The Trade Risk Engine checks 24 rules: data freshness, position size, liquidity, losses and more. The AI never decides a trade, and an admin approves every paper order.",
  },
  {
    icon: <BellRing size={22} />,
    title: "Track what matters to you",
    body: "Star stocks into watchlists, set price alerts (price, daily move or RSI), and compare stocks side by side. Alerts only inform you.",
  },
  {
    icon: <NotebookPen size={22} />,
    title: "Keep a journal",
    body: "Write why you enter and exit, then review. The Performance tab on Paper trading shows your win rate, drawdown and returns against the NIFTY 50. Help is always in the menu.",
  },
];

const key = (email: string) => `aegis:welcomed:${email}`;

export function WelcomeGuide() {
  const { me } = useSession();
  const [open, setOpen] = useState(false);
  const [step, setStep] = useState(0);

  useEffect(() => {
    if (!me?.email) return;
    try {
      if (!localStorage.getItem(key(me.email))) setOpen(true);
    } catch {
      /* storage blocked: don't nag */
    }
    const show = () => {
      setStep(0);
      setOpen(true);
    };
    window.addEventListener("aegis:welcome", show);
    return () => window.removeEventListener("aegis:welcome", show);
  }, [me?.email]);

  const close = () => {
    setOpen(false);
    try {
      if (me?.email) localStorage.setItem(key(me.email), new Date().toISOString());
    } catch {
      /* not persisted */
    }
  };

  const s = STEPS[step];
  const last = step === STEPS.length - 1;
  return (
    <Dialog
      open={open}
      onClose={close}
      size="sm"
      title={
        <span className="flex items-center gap-3">
          <span className="flex h-10 w-10 items-center justify-center rounded-xl bg-accent-soft text-accent">{s.icon}</span>
          {s.title}
        </span>
      }
      footer={
        <>
          {step > 0 ? <Button onClick={() => setStep(step - 1)}>Back</Button> : <Button variant="ghost" onClick={close}>Skip</Button>}
          <Button variant="primary" onClick={() => (last ? close() : setStep(step + 1))}>
            {last ? "Get started" : "Next"}
          </Button>
        </>
      }
    >
      <p className="text-sm leading-relaxed text-muted">{s.body}</p>
      <div className="mt-5 flex justify-center gap-1.5" aria-label={`Step ${step + 1} of ${STEPS.length}`}>
        {STEPS.map((_, i) => (
          <span key={i} className={cx("h-1.5 rounded-full transition-all", i === step ? "w-6 bg-accent" : "w-1.5 bg-line-strong")} aria-hidden />
        ))}
      </div>
    </Dialog>
  );
}
