import { describe, expect, it } from "vitest";
import { eventTitle, explainReason } from "./TraderLive";

describe("live trader evidence", () => {
  it("only describes a purchase or sale when a fill exists", () => {
    expect(eventTitle({ kind: "DECISION", symbol: "BTC-EUR", accepted: true })).toContain("qualified");
    expect(eventTitle({ kind: "DECISION", symbol: "BTC-EUR", accepted: true, broker_status: "REJECTED" })).toContain("broker rejected");
    expect(eventTitle({ kind: "ORDER", side: "BUY", status: "FILLED" })).not.toContain("Bought");
    expect(eventTitle({ kind: "FILL", side: "BUY", symbol: "BTC-EUR" })).toBe("Bought BTC-EUR · paper fill");
    expect(eventTitle({ kind: "FILL", side: "SELL", symbol: "BTC-EUR" })).toBe("Sold BTC-EUR · paper fill");
  });
  it("explains failed predicates without claiming forecast profits", () => {
    expect(explainReason("higher_15m_bullish")).toContain("has not turned bullish");
    expect(explainReason("net_reward_risk_below_research_minimum")).toContain("after fees and slippage");
    expect(explainReason("risk_rejected:planned_loss")).toContain("The planned loss is above the per-trade limit.");
    expect(explainReason("unknown_check")).toContain("Required check not met: unknown check");
  });
});
