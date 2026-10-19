import { test, expect } from "@playwright/test";
import { mockApi, signIn } from "./fixtures/v43";

test("frozen incompatibility is critical and missing stage evidence remains unknown", async ({ page }) => {
  await mockApi(page);
  await page.route("**/api/trade-gates/**", route => route.fulfill({ json: {
    state: "SHADOW_ACTIVE", runtime_generation: "verified-v44", archived_at: null,
    counts: { evaluations: 1, eligible_signals: 0, accepted_buy_decisions: 1, allocation_attempts: 1, execution_attempts: 0 },
    lifetime_financial_counts: { orders: 1, paper_fills: 0, open_positions: 0, closed_positions: 0 },
    runtime_compatibility: { compatible: false, reason: "v44_runtime_integrity_failed" },
    safety: { status: "CONSISTENT", stale: false }, causal_first_blockers: { pending_execution: 1 }, independent_failures: {},
    window: { unannotated: 1 }, diagnostic_mismatches: 0, next_cursor: null, last_scan_observation: null,
    execution_stages: { ENTRY_PREFLIGHT: { status: "NOT_RECORDED", succeeded: null, rejected: null, outcome_unavailable: null, exceptions: null } },
    decisions: [{ decision_id: "synthetic-old-buy", symbol: "ETH-EUR", created_at: "2026-10-17T06:10:16Z",
      explanation: { reason: "Historical execution outcome not verified" }, execution_evidence_status: "Historical execution outcome not verified",
      execution_trace: null, stage_states: { ENTRY_PREFLIGHT: "NOT_RECORDED" },
      recorded_order_outcomes: [{ order_id: "synthetic-rejected-order", status: "REJECTED", reason: "execution_quality:first_target_destroyed_by_execution_costs" }] }]
  }}));
  await signIn(page);
  await page.getByRole("button", { name: "Trade Gate Diagnostics", exact: true }).click();
  await expect(page.getByRole("alert").first()).toContainText("Critical: frozen runtime identity is incompatible");
  await expect(page.getByRole("cell", { name: "NOT_RECORDED", exact: true }).first()).toBeVisible();
  await page.getByText("ETH-EUR ·", { exact: false }).first().click();
  await expect(page.getByText("Independently recorded order: REJECTED", { exact: false }).first()).toContainText("first_target_destroyed_by_execution_costs");
  await expect(page.getByText("Historical trace assessment:", { exact: false }).first()).toContainText("Historical execution outcome not verified");
  await page.screenshot({ path: `${process.env.AUTOTRADER_BROWSER_EVIDENCE ?? "../docs/evidence/v4_5_rc2"}/trade-gates-incompatible-desktop.png`, fullPage: true });
});

test("trace exceptions are distinct from refused and unreached stages", async ({ page }) => {
  await mockApi(page);
  await page.route("**/api/trade-gates/**", route => route.fulfill({ json: {
    state: "SHADOW_ACTIVE", runtime_generation: "verified-v44", counts: { evaluations: 1, eligible_signals: 1, accepted_buy_decisions: 1, allocation_attempts: 1, execution_attempts: 1 },
    lifetime_financial_counts: { orders: 0, paper_fills: 0, open_positions: 0, closed_positions: 0 },
    runtime_compatibility: { compatible: true }, safety: { status: "CONSISTENT", stale: false },
    causal_first_blockers: { "execution:system_exception": 1 }, independent_failures: {},
    window: { unannotated: 0 }, diagnostic_mismatches: 0, next_cursor: null, decisions: [],
    runtime_incidents: [{ reason: "TimeoutError" }],
    execution_stages: { ENTRY_PREFLIGHT: { status: "OBSERVED", succeeded: 0, rejected: 0, outcome_unavailable: 0, exceptions: 1 },
      ORDER_FILLED: { status: "NEVER_REACHED", succeeded: null, rejected: null, outcome_unavailable: null, exceptions: null } }
  }}));
  await page.setViewportSize({ width: 375, height: 900 });
  await signIn(page);
  await page.getByRole("button", { name: "Trade Gate Diagnostics", exact: true }).click();
  await expect(page.getByRole("alert").first()).toContainText("Runtime incident: TimeoutError");
  await expect(page.getByRole("cell", { name: "NEVER_REACHED", exact: true }).first()).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  await page.screenshot({ path: `${process.env.AUTOTRADER_BROWSER_EVIDENCE ?? "../docs/evidence/v4_5_rc2"}/trade-gates-exception-mobile.png`, fullPage: true });
});
