import { expect, test } from "vitest";
import { personalText } from "./presentation";
test("backend terminology is adapted only at the presentation boundary", () => {
  const raw = "AutoTrader / Revolut X / Paper trading / Trade history";
  expect(personalText(raw)).not.toMatch(/autotrader|revolut|trading|trade/i);
  expect(raw).toContain("AutoTrader");
});
