// Brand copy only. Financial objects and technical records retain their meaning.
const labels: Record<string, string> = {
  closed_trades: "Closed positions",
  average_trade: "Average closed-position result",
  trade_gate: "Decision stage",
  paper_trading: "Simulated Mode",
  live_trading_enabled: "Real-money execution enabled",
};
export function personalText(value: unknown): string {
  const text = String(value ?? "");
  return labels[text] ?? text
    .replace(/\bAutoTrader\b/gi, "Personal Plan")
    .replace(/\bRevolut(?:[ -]X)?\b/gi, "Connected market provider");
}
export const qualificationLabel = (state: unknown) => ({
  WATCH: "Watching for a setup", DATA_UNAVAILABLE: "Data unavailable",
  TECHNICAL_CANDIDATE: "Technical candidate", COST_CONSTRAINED: "Cost constrained",
  RESEARCH_CANDIDATE: "Research candidate · unvalidated", PAPER_ELIGIBLE: "Paper eligible",
  REJECTED: "Rejected", EXECUTED_IN_SIMULATION: "Executed in simulation",
} as Record<string,string>)[String(state)] ?? "Qualification unavailable";
