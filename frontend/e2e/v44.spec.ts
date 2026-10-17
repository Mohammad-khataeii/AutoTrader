import { test, expect } from "@playwright/test";
import { fixture, ids, mockApi as baseMockApi, signIn } from "./fixtures/v43";
// Explicit archival opt-in exercises the separately gated legacy UI.
async function mockApi(page: any, data = fixture()) {
  for (const experiment of data.shadow.experiments) (experiment as any).archive_enabled = true;
  return baseMockApi(page, data);
}
async function open(page: any, id: string) {
  await page.getByRole("button", { name: "Experiments", exact: true }).click();
  await page
    .getByRole("button", { name: new RegExp(`Open .* ${id.slice(0, 8)}`) })
    .click();
}
test("deleting a paused experiment archives immutable history and frees a workspace slot", async ({
  page,
}) => {
  const api = await mockApi(page);
  const original = structuredClone(api.data.shadow.experiments[1].manifest);
  await signIn(page);
  await open(page, ids[1]);
  await page.getByText("Manage experiment", { exact: true }).click();
  await page
    .getByRole("button", { name: "Delete experiment", exact: true })
    .click();
  await expect(page.getByRole("dialog")).toContainText(
    "complete financial history",
  );
  expect(api.requests.filter((r) => r.method === "DELETE")).toHaveLength(0);
  await page
    .getByRole("dialog")
    .getByRole("button", { name: "Cancel", exact: true })
    .click();
  expect(api.requests.filter((r) => r.method === "DELETE")).toHaveLength(0);
  await page
    .getByRole("button", { name: "Delete experiment", exact: true })
    .click();
  await page
    .getByRole("dialog")
    .getByRole("button", { name: "Archive and free slot", exact: true })
    .click();
  await expect(page.getByRole("dialog")).toHaveCount(0);
  await expect(
    page.getByRole("button", { name: "New experiment", exact: true }),
  ).toBeVisible();
  expect(api.data.shadow.experiments).toHaveLength(4);
  expect(api.data.shadow.experiments[1].manifest).toEqual(original);
  await page.getByText("Archived experiments (1)", { exact: true }).click();
  await page
    .getByRole("button", { name: "View archived history", exact: true })
    .click();
  await expect(
    page.getByText("this account cannot resume", { exact: false }),
  ).toBeVisible();
  await expect(
    page.getByRole("button", { name: /Resume experiment/ }),
  ).toHaveCount(0);
  await page.getByText("Export", { exact: true }).click();
  const download = page.waitForEvent("download");
  await page.getByRole("button", { name: "Journal", exact: true }).click();
  expect((await download).suggestedFilename()).toContain(ids[1]);
});
test("stopped accounts can be deleted but active accounts cannot", async ({
  page,
}) => {
  const api = await mockApi(page);
  await signIn(page);
  await open(page, ids[0]);
  await expect(
    page.getByRole("button", { name: "Delete experiment", exact: true }),
  ).toHaveCount(0);
  await page
    .getByRole("button", { name: "All experiments", exact: true })
    .click();
  await page
    .getByRole("button", { name: new RegExp(`Open .* ${ids[3].slice(0, 8)}`) })
    .click();
  await page.getByText("Manage experiment", { exact: true }).click();
  await page
    .getByRole("button", { name: "Delete experiment", exact: true })
    .click();
  await page
    .getByRole("dialog")
    .getByRole("button", { name: "Archive and free slot", exact: true })
    .click();
  await expect(
    page.getByRole("button", { name: "New experiment", exact: true }),
  ).toBeVisible();
  expect(api.data.shadow.experiments[3].archived_at).toBeTruthy();
});
test("open-position archival failure retains the account and confirmation error", async ({
  page,
}) => {
  const data = fixture();
  (data.shadow.experiments[1].positions as any[]).push({
    position_id: "open-test",
    quantity: "1",
    symbol: "BTC-EUR",
  });
  const api = await mockApi(page, data);
  await signIn(page);
  await open(page, ids[1]);
  await page.getByText("Manage experiment", { exact: true }).click();
  await page
    .getByRole("button", { name: "Delete experiment", exact: true })
    .click();
  await page
    .getByRole("dialog")
    .getByRole("button", { name: "Archive and free slot", exact: true })
    .click();
  await expect(page.getByRole("dialog").getByRole("alert")).toBeVisible();
  expect(api.data.shadow.experiments[1].archived_at).toBeUndefined();
});
test("HTML readiness fails safely and official STOPPED remains independent of system health", async ({
  page,
}) => {
  const data = fixture();
  data.overview.portfolio.control = "STOPPED";
  await mockApi(page, data);
  await page.route("**/readyz", (route) =>
    route.fulfill({
      contentType: "text/html",
      body: "<html>React fallback</html>",
    }),
  );
  await signIn(page);
  await expect(
    page.getByText("System running.", { exact: true }),
  ).toBeVisible();
  await expect(
    page.getByText("Official account entries stopped.", { exact: false }),
  ).toBeVisible();
  await expect(
    page.getByRole("alert").filter({ hasText: "JSON was expected" }),
  ).toBeVisible();
  await expect(
    page.getByText("Real-money trading disabled", { exact: true }),
  ).toHaveCount(0);
});
test("routine views use compact APIs and structured decision evidence stays contextual", async ({
  page,
}) => {
  const data = fixture();
  const decision: any = {
    decision_id: "new-observed",
    symbol: "BTC-EUR",
    accepted: false,
    created_at: new Date().toISOString(),
    rejected_reason: "Entry conditions not met.",
    explanation: {
      final_state: "REJECTED",
      reason: "Entry conditions not met.",
      regime: "COMPRESSION",
      risk: { reached: false },
      execution: { reached: false },
      independently_failed: ["higher_timeframe_bullish", "range_held"],
      unknown_conditions: [],
      momentum_veto: true,
    },
  };
  (data.shadow.experiments[0].history.decisions as any[]).push(decision);
  const api = await mockApi(page, data);
  await signIn(page);
  expect(
    api.requests.some((r) =>
      ["shadow", "history", "research", "intelligence"].includes(r.wirePath),
    ),
  ).toBe(false);
  await open(page, ids[0]);
  await expect(
    page.getByRole("heading", { name: "Recent decisions", exact: true }),
  ).toBeVisible();
  await expect(
    page.getByText("Risk not reached", { exact: false }),
  ).toBeVisible();
  await expect(page.locator("pre:visible")).toHaveCount(0);
  await page.getByText("Why this decision?", { exact: true }).click();
  await expect(
    page.getByText(
      "A concurrent veto is not evidence that it was the only blocker.",
      { exact: false },
    ),
  ).toBeVisible();
  expect(api.requests.some((r) => r.wirePath.endsWith("/view"))).toBe(true);
});
