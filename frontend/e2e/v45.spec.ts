import { test, expect } from "@playwright/test";
import { fixture, mockApi, signIn, ids } from "./fixtures/v43";

test("trade gate dashboard distinguishes eligibility from orders and shows decision evidence", async ({ page }) => {
  await mockApi(page);
  await page.route("**/api/trade-gates/**", route => route.fulfill({ json: {
    counts: { evaluations: 35, eligible_signals: 2, accepted_buy_decisions: 1, allocation_attempts: 1, execution_attempts: 1 },
    lifetime_financial_counts: { paper_fills: 0, open_positions: 0, closed_positions: 0 },
    runtime_compatibility: { compatible: true }, safety: { status: "CONSISTENT", stale: false },
    causal_first_blockers: { "strategy:higher_timeframe_bullish": 33, "execution:execution_quality": 1 },
    independent_failures: { higher_timeframe_bullish: { count: 33, percent_of_evaluations: 94.286 } },
    window: { unannotated: 0 }, diagnostic_mismatches: 0, next_cursor: null, last_scan_observation: null,
    decisions: [{ decision_id: "fixture-decision", symbol: "BTC-EUR", created_at: "2026-10-17T08:00:00Z", explanation: { reason: "first_target_destroyed_by_execution_costs", entry_conditions: { higher_timeframe_bullish: true }, inputs: { ema_9: "100.5" } } }]
  }}));
  await signIn(page);
  await page.getByRole("button", { name: "Decision Insights", exact: true }).click();
  await expect(page.getByRole("heading", { name: "Decision Insights", exact: true })).toBeVisible();
  await expect(page.getByText("35 recorded evaluations in this page.", { exact: false }).first()).toBeVisible();
  await expect(page.getByText("0 lifetime paper fills", { exact: false }).first()).toBeVisible();
  await page.getByText("BTC-EUR ·", { exact: false }).first().click();
  await page.getByText("All conditions and recorded values", { exact: true }).first().click();
  await expect(page.locator("pre:visible").first()).toContainText('"ema_9": "100.5"');
});

test("archiving is disabled by default while stopped history stays accessible", async ({ page }) => {
  await mockApi(page, fixture());
  await signIn(page);
  await page.getByRole("button", { name: "Strategies", exact: true }).click();
  await page.getByRole("button", { name: new RegExp(`Open .* ${ids[3].slice(0, 8)}`) }).click();
  await expect(page.getByRole("button", { name: "Delete experiment", exact: true })).toHaveCount(0);
});
