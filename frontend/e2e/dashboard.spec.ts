import { test, expect } from "@playwright/test";
import fs from "node:fs";
import path from "node:path";
const file =
  process.env.AUTOTRADER_BROWSER_ENV ?? path.resolve("../.tools/v42-test.env");
const env = Object.fromEntries(
  fs
    .readFileSync(file, "utf8")
    .trim()
    .split(/\r?\n/)
    .map((line) => {
      const i = line.indexOf("=");
      return [line.slice(0, i), line.slice(i + 1)];
    }),
);
async function advanced(page: any, name: string) {
  await page.locator(".advanced-menu > summary").click();
  await page.getByRole("button", { name, exact: true }).click();
  await expect(page.getByRole("heading", { name, level: 1 })).toBeVisible();
}
test("authenticated runtime data, retained advanced research, paper controls and pilot exports", async ({
  page,
  request,
}) => {
  test.setTimeout(240000);
  const errors: string[] = [];
  page.on("pageerror", (e) => errors.push(e.message));
  await page.goto("/");
  await page
    .getByLabel("Username", { exact: true })
    .fill(env.DASHBOARD_USERNAME);
  await page
    .getByLabel("Password", { exact: true })
    .fill(env.DASHBOARD_PASSWORD);
  await page.getByRole("button", { name: "Sign in", exact: true }).click();
  await expect(
    page.getByRole("heading", { name: "Overview", level: 1 }),
  ).toBeVisible();
  const headers = {
    Authorization: `Basic ${Buffer.from(`${env.DASHBOARD_USERNAME}:${env.DASHBOARD_PASSWORD}`).toString("base64")}`,
  };
  const before = await (await request.get("/api/overview", { headers })).json();
  await expect(page.locator(".kpi").first().locator("strong")).toHaveText(
    `€${Number(before.portfolio.equity).toFixed(2)}`,
  );
  await expect(
    page.getByText("The official portfolio is in research mode.", {
      exact: false,
    }),
  ).toBeVisible();
  for (const tab of ["Strategies", "Activity", "Research", "Overview"]) {
    await page.getByRole("button", { name: tab, exact: true }).click();
    await expect(
      page.getByRole("heading", { name: tab, level: 1 }),
    ).toBeVisible();
    await expect(page.locator("pre:visible")).toHaveCount(0);
  }
  for (const name of [
    "Market monitor",
    "Decision journal",
    "Execution diagnostics",
    "AI & budgets",
    "Risk & recovery",
    "System & data health",
    "Settings",
  ]) {
    await advanced(page, name);
  }
  await page.getByRole("button", { name: "Research", exact: true }).click();
  await page
    .getByRole("button", { name: "Advanced Research", exact: true })
    .click();
  await page.getByLabel("Research tool").selectOption("Historical lab");
  await page.getByLabel("Run history").selectOption("research-20261016T044934");
  await page.getByLabel("Dataset asset").selectOption("BTC-EUR");
  await page.getByLabel("Research timeframe").selectOption("5m");
  await page
    .getByLabel("Research strategy")
    .selectOption("B_COMPRESSION_BREAKOUT");
  await page
    .getByRole("button", {
      name: "Load position and equity evidence",
      exact: true,
    })
    .click();
  await expect(
    page.getByRole("heading", {
      name: "Out-of-sample marked equity",
      exact: true,
    }),
  ).toBeVisible();
  await page.getByLabel("Research timeframe").selectOption("1h");
  const queuedResponse = page.waitForResponse(
    (r) =>
      r.url().endsWith("/api/research/jobs") && r.request().method() === "POST",
  );
  await page
    .getByRole("button", { name: "Run selected research", exact: true })
    .click();
  const queued = await queuedResponse;
  expect(queued.status()).toBe(202);
  const job = await queued.json();
  await expect
    .poll(
      async () => {
        const body = await (
          await request.get("/api/research", { headers })
        ).json();
        return body.jobs.find((r: any) => r.job_id === job.job_id)?.status;
      },
      { timeout: 120000, intervals: [2000] },
    )
    .toBe("COMPLETED");
  await expect(page.getByLabel("Research timeframe")).toHaveValue("1h");
  await page.getByLabel("Research tool").selectOption("Historical replay");
  await page.getByLabel("Replay entry policy").selectOption("LIMIT");
  const completedResponse = page.waitForResponse(
    (r) =>
      r.url().endsWith("/api/backtests") && r.request().method() === "POST",
    { timeout: 150000 },
  );
  await page
    .getByRole("button", { name: "Run BTC-EUR historical replay", exact: true })
    .click();
  const completed = await completedResponse;
  expect(completed.ok()).toBeTruthy();
  const replay = await completed.json();
  expect(replay.status).toBe("COMPLETED");
  expect(replay.report.assumptions.entry_order_type).toBe("LIMIT");
  await expect(page.getByText(replay.run_id, { exact: true })).toBeVisible();
  await advanced(page, "Official Account Controls");
  // Acceptance runs may begin with an intentionally stopped local paper account.
  // Exercise its state-valid action before the full control sequence.
  const initialControl = (await (await request.get("/api/overview", { headers })).json()).portfolio.control;
  if (initialControl !== "RUNNING") {
    const initialLabel = initialControl === "STOPPED" ? "Start simulated activity" : "Resume simulated activity";
    await page.getByRole("button", { name: initialLabel, exact: true }).click();
    await page.getByRole("dialog").getByRole("button", { name: initialLabel, exact: true }).click();
    await expect(page.getByRole("dialog")).toHaveCount(0);
  }
  for (const [action, label, state] of [
    ["pause", "Pause new entries", "PAUSED"],
    ["resume", "Resume simulated activity", "RUNNING"],
    ["stop", "Stop simulated activity", "STOPPED"],
    ["start", "Start simulated activity", "RUNNING"],
    ["emergency", "Emergency halt", "EMERGENCY"],
    ["resume", "Resume simulated activity", "RUNNING"],
  ]) {
    await page.getByRole("button", { name: label, exact: true }).click();
    await expect(page.getByRole("dialog")).toBeVisible();
    await page
      .getByRole("dialog")
      .getByRole("button", { name: label, exact: true })
      .click();
    await expect(page.getByRole("dialog")).toHaveCount(0);
    expect(
      (await (await request.get("/api/overview", { headers })).json()).portfolio
        .control,
    ).toBe(state);
  }
  await advanced(page, "AI & budgets");
  await expect(
    page.getByText("Rolling 60 minutes", { exact: true }),
  ).toBeVisible();
  const ai = await (await request.get("/api/ai", { headers })).json();
  expect(ai.provider).toBe("mock");
  expect(ai.budget.daily_used).toBe(0);
  expect(ai.budget.rolling_hour_used).toBe(0);
  await advanced(page, "Paper pilot");
  let pilots = await (await request.get("/api/pilots", { headers })).json();
  if (!pilots.some((p: any) => p.state === "ACTIVE")) {
    await page
      .getByRole("button", { name: "Start 30-day paper pilot", exact: true })
      .click();
    await page
      .getByRole("dialog")
      .getByRole("button", { name: "Start pilot", exact: true })
      .click();
  }
  await expect(
    page.getByText(env.ENVIRONMENT === "test" ? "Test simulation · Active" : "Research mode · Active", { exact: true }),
  ).toBeVisible();
  await expect
    .poll(
      async () => {
        pilots = await (await request.get("/api/pilots", { headers })).json();
        const active = pilots.find((p: any) => p.state === "ACTIVE");
        if (!active) return 0;
        const r = await (
          await request.get(`/api/pilots/${active.pilot_id}/report`, {
            headers,
          })
        ).json();
        expect(r.mode).toBe(env.ENVIRONMENT === "test" ? "SYNTHETIC_ACCEPTANCE" : "RESEARCH_ONLY");
        expect(r.thirty_days_elapsed).toBe(false);
        return r.observations;
      },
      { timeout: 90000, intervals: [3000] },
    )
    .toBeGreaterThan(0);
  const firstExport = page
    .getByRole("button", { name: "Export CSV report", exact: true })
    .first();
  const download = page.waitForEvent("download");
  await firstExport.click();
  expect((await download).suggestedFilename()).toMatch(/\.csv$/);
  const after = await (await request.get("/api/overview", { headers })).json();
  expect(after.portfolio.equity).toBe(before.portfolio.equity);
  expect(after.orders.length).toBe(before.orders.length);
  expect(errors).toEqual([]);
  await page.getByRole("button", { name: "Sign out", exact: true }).click();
  await expect(
    page.getByRole("button", { name: "Sign in", exact: true }),
  ).toBeVisible();
});
