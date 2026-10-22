import { expect, test } from "vitest";
import { personalText, qualificationLabel } from "./presentation";
test("brand copy is explicit and financial terms are never rewritten", () => {
  expect(personalText("AutoTrader / Revolut X")).toBe("Personal Plan / Connected market provider");
  const financial = "A trade has two fills; orders, transactions and positions are different. Trade-off, trader and trading history remain source text.";
  expect(personalText(financial)).toBe(financial);
  expect(personalText("closed_trades")).toBe("Closed positions");
  expect(personalText("trade_count")).toBe("trade_count");
  expect(qualificationLabel("RESEARCH_CANDIDATE")).toContain("unvalidated");
  expect(qualificationLabel("EXECUTED_IN_SIMULATION")).toBe("Executed in simulation");
});
