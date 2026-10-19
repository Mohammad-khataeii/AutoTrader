import { test, expect } from "@playwright/test";
import { fixture, ids, mockApi, signIn } from "./fixtures/v43";
test("five primary routes, authentic status language and no default technical payloads", async ({
  page,
}) => {
  const api = await mockApi(page);
  await signIn(page);
  expect(
    await page
      .getByRole("navigation", { name: "Primary navigation" })
      .getByRole("button")
      .allTextContents(),
  ).toEqual(["Overview", "Opportunities", "Strategies", "Activity", "Research", "Decision Insights"]);
  await expect(
    page.getByText("The official portfolio is in research mode.", {
      exact: false,
    }),
  ).toBeVisible();
  await expect(
    page.getByText("Real-money execution disabled", { exact: true }),
  ).toBeVisible();
  await expect(page.locator("pre:visible")).toHaveCount(0);
  expect(await page.locator(".kpi").count()).toBe(4);
  expect(
    api.requests.some(
      (r) =>
        [
          "research",
          "history",
          "ai",
          "execution",
          "scanner",
          "backtests",
          "intelligence",
        ].includes(r.path) && r.path !== "history",
    ),
  ).toBe(false);
  expect(api.requests.filter((r) => r.path === "overview")).toHaveLength(1);
  await page.getByRole("button", { name: "Sign out" }).click();
  await expect(
    page.getByRole("button", { name: "Sign in", exact: true }),
  ).toBeVisible();
});
test("all four retained accounts are distinct, duplicates preserved and creation unavailable", async ({
  page,
}) => {
  const api = await mockApi(page);
  await signIn(page);
  await page.getByRole("button", { name: "Strategies", exact: true }).click();
  await expect(page.locator(".experiment-card")).toHaveCount(3);
  for (const id of ids)
    await expect(
      page.getByRole("button", {
        name: new RegExp(`Open .* ${id.slice(0, 8)}`),
      }),
    ).toBeVisible();
  await expect(
    page.getByRole("button", { name: /^Open B2 Confirmed Compression/ }),
  ).toHaveCount(3);
  await expect(
    page.getByRole("button", { name: "New experiment", exact: true }),
  ).toHaveCount(0);
  await expect(
    page.getByText("4 of 4 experiment slots used.", { exact: false }),
  ).toBeVisible();
  expect(api.requests.filter((r) => r.method !== "GET")).toHaveLength(0);
});
test("state-valid actions and confirmed permanent stop preserve the retained slot", async ({
  page,
}) => {
  const api = await mockApi(page);
  await signIn(page);
  await page.getByRole("button", { name: "Strategies", exact: true }).click();
  await expect(
    page.getByRole("button", {
      name: `Resume experiment ${ids[1].slice(0, 8)}`,
      exact: true,
    }),
  ).toBeVisible();
  await expect(
    page.getByRole("button", {
      name: `Pause experiment ${ids[1].slice(0, 8)}`,
      exact: true,
    }),
  ).toHaveCount(0);
  await page
    .getByRole("button", {
      name: `Open B2 Confirmed Compression ${ids[3].slice(0, 8)}`,
      exact: true,
    })
    .click();
  await expect(
    page.getByRole("button", { name: /Resume experiment/ }),
  ).toHaveCount(0);
  await expect(
    page.getByRole("button", { name: /Pause experiment/ }),
  ).toHaveCount(0);
  await page
    .getByRole("button", { name: "All experiments", exact: true })
    .click();
  await page
    .getByRole("button", {
      name: `Open B2 Confirmed Compression ${ids[0].slice(0, 8)}`,
      exact: true,
    })
    .click();
  await page.getByText("More experiment actions", { exact: false }).count();
  await page.getByLabel("More experiment actions").click();
  await page
    .getByRole("button", { name: "Stop permanently", exact: true })
    .click();
  await expect(page.getByRole("dialog")).toBeVisible();
  await expect(
    page.getByText("Stopping does not free an experiment slot.", {
      exact: false,
    }),
  ).toBeVisible();
  expect(api.requests.filter((r) => r.method === "POST")).toHaveLength(0);
  await page.getByRole("button", { name: "Cancel", exact: true }).click();
  expect(api.requests.filter((r) => r.method === "POST")).toHaveLength(0);
  await page
    .getByRole("button", { name: "Stop permanently", exact: true })
    .click();
  await page
    .getByRole("dialog")
    .getByRole("button", { name: "Stop permanently", exact: true })
    .click();
  await expect(
    page.getByRole("button", { name: /Resume experiment/ }),
  ).toHaveCount(0);
  expect(api.data.shadow.experiments).toHaveLength(4);
});
test("one export menu retains all five authenticated complete exports", async ({
  page,
}) => {
  await mockApi(page);
  await signIn(page);
  await page.getByRole("button", { name: "Strategies", exact: true }).click();
  await page
    .getByRole("button", {
      name: `Open B2 Confirmed Compression ${ids[0].slice(0, 8)}`,
      exact: true,
    })
    .click();
  await page.getByText("Export", { exact: true }).click();
  for (const name of [
    "Financial report",
    "Orders",
    "Fills",
    "Journal",
    "Equity",
  ]) {
    const download = page.waitForEvent("download");
    await page.getByRole("button", { name, exact: true }).click();
    expect((await download).suggestedFilename()).toContain(ids[0]);
  }
  await page
    .getByText("Performance and financial integrity", { exact: true })
    .click();
  await expect(
    page.getByText("Complete exports have no row limit.", { exact: false }),
  ).toBeVisible();
});
test("stale refresh keeps the last values with a clear warning and recovers without navigation reset", async ({
  page,
}) => {
  const api = await mockApi(page);
  await signIn(page);
  await expect(page.locator(".kpi").first().getByText("€500.00")).toBeVisible();
  api.failOverview();
  await page.getByRole("button", { name: "Refresh current view" }).click();
  await expect(
    page
      .getByRole("alert")
      .filter({ hasText: "Official account could not be refreshed" }),
  ).toBeVisible();
  await expect(page.locator(".kpi").first().getByText("€500.00")).toBeVisible();
  await expect(
    page.getByRole("heading", { name: "Overview", exact: true }),
  ).toBeVisible();
  api.recoverOverview();
  await page.getByRole("button", { name: "Refresh current view" }).click();
  await expect(page.getByRole("alert")).toHaveCount(0);
});
test("research loads on demand, preserves negative results, and advanced capabilities remain reachable", async ({
  page,
}) => {
  const api = await mockApi(page);
  await signIn(page);
  expect(api.requests.filter((r) => r.path === "research")).toHaveLength(0);
  await page.getByRole("button", { name: "Research", exact: true }).click();
  await expect(page.getByText("-€3.80", { exact: true })).toBeVisible();
  await expect(
    page.getByText("Not validated", { exact: true }).first(),
  ).toBeVisible();
  await expect(page.locator("pre:visible")).toHaveCount(0);
  await page.getByRole("button", { name: "Overview", exact: true }).click();
  await page.getByRole("button", { name: "Research", exact: true }).click();
  expect(api.requests.filter((r) => r.path === "research")).toHaveLength(1);
  await page
    .getByRole("button", { name: "Advanced Research", exact: true })
    .click();
  await page
    .getByLabel("Research tool")
    .selectOption("Outcome diagnostics");
  await expect(
    page.getByRole("heading", {
      name: "Outcome diagnostics",
      exact: true,
    }),
  ).toBeVisible();
  await page.locator("summary").filter({ hasText: "Settings" }).click();
  await page
    .getByRole("button", { name: "Official Account Controls", exact: true })
    .click();
  await expect(
    page.getByRole("button", { name: "Pause new entries", exact: true }),
  ).toBeVisible();
  await page
    .getByRole("button", { name: "Emergency halt", exact: true })
    .click();
  await expect(page.getByRole("dialog")).toBeVisible();
  expect(api.requests.filter((r) => r.method === "POST")).toHaveLength(0);
  await page.keyboard.press("Escape");
});
test("open trade detail does not invent prices or P&L without a valid timestamped mark", async ({
  page,
}) => {
  const data = fixture();
  const position: any = {
    position_id: "fixture-position",
    symbol: "BTC-EUR",
    quantity: ".01",
    average_entry_price: "100",
    protective_stop: "95",
    realized_pnl: "0",
    opened_at: "2026-10-16T12:00:00Z",
    closed_at: null,
  };
  (data.overview.positions as any[]).push(position);
  data.overview.portfolio.positions = "1";
  await mockApi(page, data);
  await signIn(page);
  await page.getByRole("button", { name: "Activity", exact: true }).click();
  await expect(
    page
      .getByRole("region", { name: "Open positions", exact: true })
      .getByText("Unavailable"),
  ).toHaveCount(2);
  await page
    .getByRole("button", { name: "View BTC-EUR Official", exact: true })
    .click();
  await expect(
    page.getByText("No price is inferred from a historical signal.", {
      exact: false,
    }),
  ).toBeVisible();
  position.quantity = "0";
  position.closed_at = "2026-10-16T12:05:00Z";
  position.realized_pnl = "-5";
  await page.getByRole("button", { name: "Refresh current view" }).click();
  await expect(page.getByText("Realized P&L", { exact: true })).toBeVisible();
  await expect(page.getByText("-€5.00", { exact: true })).toBeVisible();
  await expect(
    page.getByRole("button", { name: "Back to activity", exact: true }),
  ).toBeVisible();
  await expect(page.locator("pre:visible")).toHaveCount(0);
});
test("refresh timers are sequential, hidden views stop polling and heavy data stays cached", async ({
  page,
}) => {
  const api = await mockApi(page);
  await page.clock.install();
  await signIn(page);
  await page.getByRole("button", { name: "Strategies", exact: true }).click();
  await page
    .getByRole("button", {
      name: `Pause experiment ${ids[0].slice(0, 8)}`,
      exact: true,
    })
    .click();
  await expect(
    page.getByRole("button", {
      name: `Resume experiment ${ids[0].slice(0, 8)}`,
      exact: true,
    }),
  ).toBeVisible();
  await page.getByRole("button", { name: "Research", exact: true }).click();
  await expect(page.getByText("-€3.80", { exact: true })).toBeVisible();
  const shadowBefore = api.requests.filter((r) => r.path === "shadow").length;
  await page.clock.runFor(65000);
  expect(api.requests.filter((r) => r.path === "research")).toHaveLength(1);
  expect(api.requests.filter((r) => r.path === "shadow").length).toBe(
    shadowBefore,
  );
  expect(
    api.requests.filter((r) => r.path === "system").length,
  ).toBeLessThanOrEqual(6);
});
for (const width of [1440, 1024, 768, 375])
  test(`layout and keyboard navigation at ${width}px`, async ({ page }) => {
    await page.setViewportSize({ width, height: 1000 });
    await mockApi(page);
    await signIn(page);
    await expect(
      page.getByRole("heading", { name: "Overview", exact: true }),
    ).toBeVisible();
    expect(
      await page.evaluate(
        () => document.documentElement.scrollWidth <= innerWidth,
      ),
    ).toBe(true);
    await page.screenshot({
      path: `${process.env.AUTOTRADER_BROWSER_EVIDENCE ?? "../docs/evidence/v4_5"}/acceptance-overview-${width}.png`,
      fullPage: true,
    });
    await page
      .getByRole("button", { name: "Strategies", exact: true })
      .click();
    await expect(page.locator(".experiment-card")).toHaveCount(3);
    expect(
      await page.evaluate(
        () => document.documentElement.scrollWidth <= innerWidth,
      ),
    ).toBe(true);
    await expect(page.locator("pre:visible")).toHaveCount(0);
    await page.screenshot({
      path: `${process.env.AUTOTRADER_BROWSER_EVIDENCE ?? "../docs/evidence/v4_5"}/acceptance-experiments-${width}.png`,
      fullPage: true,
    });
    await page.getByRole("button", { name: "Research", exact: true }).focus();
    await page.keyboard.press("Enter");
    await expect(
      page.getByRole("heading", { name: "Research", exact: true }),
    ).toBeVisible();
  });

test("creating an experiment requires explicit slot-use review and cancellation has no side effect", async ({
  page,
}) => {
  const data = fixture();
  data.shadow.experiments.pop();
  const api = await mockApi(page, data);
  await signIn(page);
  await page.getByRole("button", { name: "Strategies", exact: true }).click();
  await page
    .getByRole("button", { name: "New experiment", exact: true })
    .click();
  await page
    .getByLabel("Experiment name", { exact: true })
    .fill("Acceptance creation");
  await page
    .getByRole("button", { name: "Review experiment", exact: true })
    .click();
  await expect(page.getByRole("dialog")).toContainText(
    "using one of 4 workspace slots",
  );
  await page
    .getByRole("dialog")
    .getByRole("button", { name: "Cancel", exact: true })
    .click();
  expect(api.requests.filter((r) => r.method === "POST")).toHaveLength(0);
  await page
    .getByRole("button", { name: "Review experiment", exact: true })
    .click();
  await page
    .getByRole("dialog")
    .getByRole("button", { name: "Create experiment", exact: true })
    .click();
  await expect(page.getByRole("dialog")).toHaveCount(0);
  expect(
    api.requests.filter((r) => r.path === "shadow" && r.method === "POST"),
  ).toHaveLength(1);
  await page
    .getByRole("button", { name: "All experiments", exact: true })
    .click();
  await expect(
    page.getByRole("button", { name: "New experiment", exact: true }),
  ).toHaveCount(0);
});
