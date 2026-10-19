import { test, expect } from "@playwright/test";
import { mockApi, signIn } from "./fixtures/v43";

for (const width of [375, 1440]) {
  test(`Personal Plan qualification, comparison and visible language at ${width}px`, async ({ page }) => {
    const api = await mockApi(page);
    await page.setViewportSize({ width, height: 1000 });
    const row = { symbol: "ETH-EUR", strategy_id: "A3_COST_AWARE_CONTINUATION", score: "0.78", as_of: "2026-10-19T10:00:00Z",
      technical_eligible: true, economic_eligible: false,
      explanation: "A bullish pullback qualified technically, but the modeled first target cannot cover execution costs.",
      regime_assessment: { trend: "MODERATE_BULLISH", structure: ["COMPRESSION"], volatility: "LOW" },
      economics: { measurements: { gross_target_return: "0.0016", estimated_total_round_trip_cost_eur: "0.27", net_reward_risk: "-0.2", conditional_target_net_eur: ["-0.15"], expected_net_stop_loss_eur: ".4", breakeven_bid: "100.36" } },
      pipeline: [{ stage: "TECHNICAL_SETUP", reached: true, passed: true, reason: "technical_setup_qualified" }, { stage: "COST_FEASIBILITY", reached: true, passed: false, reason: "first_target_destroyed_by_execution_costs" }, { stage: "PORTFOLIO_RISK", reached: false, passed: null }] };
    await page.route("**/api/opportunities?**", route => route.fulfill({ json: { status: "OBSERVED", rows: [row], technical_candidates: 1, economically_viable_candidates: 0, stale: false,
      updated_at: "2026-10-19T10:00:00Z", next_cursor: null, discovery: { counts: { supported_eur: 40, screened: 10 }, extra_detail_budget: 3 }, data_failures: [] } }));
    await page.route("**/api/strategies/comparison", route => route.fulfill({ json: { status: "NOT_RECORDED", successors: [], research: null } }));
    await signIn(page);
    await page.getByRole("button", { name: "Opportunities", exact: true }).click();
    await expect(page.getByRole("cell", { name: "Cost constrained", exact: true })).toBeVisible();
    await page.getByRole("button", { name: "ETH-EUR A3 Cost-Aware Continuation", exact: true }).click();
    await expect(page.getByRole("paragraph").filter({ hasText: "A bullish pullback qualified technically" })).toBeVisible();
    await expect(page.getByText("Not reached ·", { exact: false }).first()).toBeVisible();
    await page.getByText("Conditions and cost measurements", { exact: true }).click();
    expect(await page.locator("body").innerText()).not.toMatch(/\b(?:revolut(?: x)?|trade|trades|trading|trader|autotrader)\b/i);
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
    await page.screenshot({ path: `${process.env.AUTOTRADER_BROWSER_EVIDENCE ?? "../docs/evidence/v4_6"}/personal-plan-opportunities-${width}.png`, fullPage: true });
    await page.getByRole("button", { name: "Strategies", exact: true }).click();
    await page.getByRole("tab", { name: "Research comparison", exact: true }).click();
    await expect(page.getByText("No completed V4.6 comparison", { exact: false })).toBeVisible();
    await expect(page.getByRole("region", { name: "Strategy research comparison", exact: true }).locator("tbody tr")).toHaveCount(6);
    for (const name of ["Overview", "Activity", "Research", "Decision Insights"]) {
      await page.getByRole("button", { name, exact: true }).click();
      expect(await page.locator("body").innerText()).not.toMatch(/\b(?:revolut(?: x)?|trade|trades|trading|trader|autotrader)\b/i);
      expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
    }
    expect(api.requests.filter(r => r.method !== "GET")).toHaveLength(0);
  });
}
