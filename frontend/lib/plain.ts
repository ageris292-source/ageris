/** Plain-English names for the 24 safety checks (and the ranking's
 *  "data" pre-check), for people who don't speak risk-engine. */
export const PLAIN_CHECK: Record<string, string> = {
  data: "not enough price history",
  kill_switch: "trading is paused",
  execution_mode: "paper trading is switched off",
  portfolio_match: "no matching portfolio",
  instrument: "not a tradable Indian stock",
  data_licensed: "prices come from a free, unlicensed source",
  data_freshness: "prices are out of date",
  data_quality: "price data failed quality checks",
  entry_deviation: "price too far from the last close",
  research_report: "research report is missing or old",
  research_stance: "research view isn't positive",
  agent_conflicts: "research agents disagree",
  model_calibration: "no validated AI model estimate",
  out_of_sample: "model not tested on enough unseen data",
  probability_of_profit: "chance of profit too low",
  expected_net_return: "expected return too small after costs",
  edge_vs_benchmark: "doesn't beat the NIFTY 50",
  trade_plan: "trade plan incomplete",
  reward_risk: "reward too small for the risk",
  liquidity: "stock trades too thinly",
  participation: "order too big for daily volume",
  spread: "no live price quote",
  position_sizing: "position too large",
  portfolio_limits: "portfolio limits would be broken",
  loss_limits: "loss limits already reached",
};

export function plainCheck(name: string | null | undefined): string {
  if (!name) return "—";
  return PLAIN_CHECK[name] ?? name.replace(/_/g, " ");
}

export function sentenceCase(s: string): string {
  return s ? s.charAt(0).toUpperCase() + s.slice(1).toLowerCase() : s;
}
