import { test, expect } from "@playwright/test";
import fs from "node:fs";
import path from "node:path";

const file = process.env.AUTOTRADER_BROWSER_ENV ?? path.resolve("../.tools/v41-test.env");
const env = Object.fromEntries(fs.readFileSync(file, "utf8").trim().split(/\r?\n/).map(line => { const i = line.indexOf("="); return [line.slice(0, i), line.slice(i + 1)]; }));

test("authenticated runtime data, all pages, and persistent paper controls", async ({ page, request }) => {
  test.setTimeout(180000);
  const errors: string[] = [];
  page.on("pageerror", error => errors.push(error.message));
  await page.goto("/");
  await expect(page.getByRole("heading", { name: "Revolut X AutoTrader" })).toBeVisible();
  await page.getByLabel("Username").fill(env.DASHBOARD_USERNAME);
  await page.getByLabel("Password").fill(env.DASHBOARD_PASSWORD);
  await page.getByRole("button", { name: "Sign in", exact: true }).click();
  await expect(page.getByRole("heading", { name: "Command Center", exact: true })).toBeVisible();
  await expect(page.getByText("Starting virtual capital", { exact: true })).toBeVisible();
  await expect(page.getByText("NO VALIDATED STRATEGY", { exact: true })).toBeVisible();
  const headers = { Authorization: `Basic ${Buffer.from(`${env.DASHBOARD_USERNAME}:${env.DASHBOARD_PASSWORD}`).toString("base64")}` };
  const api = await request.get("/api/overview", { headers });
  expect(api.ok()).toBeTruthy();
  const overview = await api.json();
  const expected = `EUR ${Number(overview.portfolio.available_cash).toFixed(2)}`;
  await expect(page.locator(".metric").filter({ hasText: "Available cash" }).locator("strong")).toHaveText(expected);
  for (const tab of ["Market Scanner", "Opportunities", "Autonomous Decisions", "Portfolio", "Position Management", "Order History", "Backtesting Lab", "Execution Quality", "Strategy Lab", "Opportunity Intelligence", "AI Intelligence", "Risk Center", "System Health", "Paper Pilot", "Settings"]) {
    await page.getByRole("button", { name: tab, exact: true }).click();
    await expect(page.getByRole("heading", { name: tab, exact: true })).toBeVisible();
  }
  await page.getByRole("button", { name: "Strategy Lab", exact: true }).click();
  await page.getByLabel("Dataset asset").selectOption("BTC-EUR");
  await page.getByLabel("Research timeframe").selectOption("5m");
  await page.getByLabel("Research strategy").selectOption("B_COMPRESSION_BREAKOUT");
  await page.getByRole("button", { name: "Load trade and equity evidence", exact: true }).click();
  await expect(page.getByRole("heading", { name: "Out-of-sample marked equity", exact: true })).toBeVisible();
  await page.getByLabel("Research timeframe").selectOption("1h");
  const queuedResponse = page.waitForResponse(response => response.url().endsWith("/api/research/jobs") && response.request().method() === "POST");
  await page.getByRole("button", { name: "Run selected research", exact: true }).click();
  const queued = await queuedResponse;
  expect(queued.status()).toBe(202);
  const job = await queued.json();
  await expect.poll(async () => {
    const body = await (await request.get("/api/research", { headers })).json();
    return body.jobs.find((row: any) => row.job_id === job.job_id)?.status;
  }, { timeout: 120000, intervals: [2000] }).toBe("COMPLETED");
  await expect(page.getByText("COMPLETED", { exact: true }).first()).toBeVisible({ timeout: 15000 });
  await page.screenshot({ path: "../docs/evidence/strategy-lab-v4_1.png", fullPage: true });
  await page.getByRole("button", { name: "Backtesting Lab", exact: true }).click();
  await page.getByLabel("Replay entry policy").selectOption("LIMIT");
  const replayResponse = page.waitForResponse(response => response.url().endsWith("/api/backtests") && response.request().method() === "POST", { timeout: 150000 });
  await page.getByRole("button", { name: "Run BTC-EUR historical replay", exact: true }).click();
  const completed = await replayResponse;
  expect(completed.ok()).toBeTruthy();
  const replay = await completed.json();
  expect(replay.status).toBe("COMPLETED");
  expect(replay.report.assumptions.entry_order_type).toBe("LIMIT");
  await expect(page.getByText(replay.run_id, { exact: true })).toBeVisible();
  await page.getByRole("button", { name: "PAUSE NEW ENTRIES", exact: true }).click();
  await expect(page.getByText(/Controls: PAUSED/)).toBeVisible();
  expect((await (await request.get("/api/overview", { headers })).json()).portfolio.control).toBe("PAUSED");
  await page.getByRole("button", { name: "RESUME PAPER TRADING", exact: true }).click();
  await expect(page.getByText(/Controls: RUNNING/)).toBeVisible();
  await page.getByRole("button", { name: "STOP PAPER TRADING", exact: true }).click();
  await expect(page.getByText(/Controls: STOPPED/)).toBeVisible();
  await page.getByRole("button", { name: "START PAPER TRADING", exact: true }).click();
  await expect(page.getByText(/Controls: RUNNING/)).toBeVisible();
  await page.getByRole("button", { name: "EMERGENCY PAPER HALT", exact: true }).click();
  await expect(page.getByText(/Controls: EMERGENCY/)).toBeVisible();
  await page.getByRole("button", { name: "RESUME PAPER TRADING", exact: true }).click();
  await expect(page.getByText(/Controls: RUNNING/)).toBeVisible();
  await page.getByRole("button", { name: "Command Center", exact: true }).click();
  if ((await (await request.get("/api/history", { headers })).json()).equity.length > 1) {
    // A flat equity curve has zero geometric height despite its visible stroke.
    await expect(page.locator(".recharts-area-area")).toBeVisible();
    await expect(page.locator(".recharts-area-curve")).toHaveAttribute("d", /[ML]/);
  }
  await page.screenshot({ path: "../docs/evidence/dashboard-v4_1.png", fullPage: true });
  await page.getByRole("button", { name: "AI Intelligence", exact: true }).click();
  await expect(page.getByText("Rolling 60 minutes", { exact: true })).toBeVisible();
  const ai = await (await request.get("/api/ai", { headers })).json();
  expect(ai.provider).toBe("mock");
  expect(ai.budget.daily_used).toBe(0);
  expect(ai.budget.rolling_hour_used).toBe(0);
  await page.getByRole("button", { name: "Paper Pilot", exact: true }).click();
  const pilotList = await (await request.get("/api/pilots", { headers })).json();
  if (!pilotList.length) await page.getByRole("button", { name: "Start 30-day paper pilot", exact: true }).click();
  await expect(page.getByRole("heading", { name: "RESEARCH_ONLY · ACTIVE" })).toBeVisible();
  await expect.poll(async () => {
    const pilots = await (await request.get("/api/pilots", { headers })).json();
    if (!pilots.length) return 0;
    const report = await (await request.get(`/api/pilots/${pilots[0].pilot_id}/report`, { headers })).json();
    expect(report.thirty_days_elapsed).toBe(false);
    expect(report.mode).toBe("RESEARCH_ONLY");
    return report.observations;
  }, { timeout: 90000, intervals: [3000] }).toBeGreaterThan(0);
  const pilots = await (await request.get("/api/pilots", { headers })).json();
  const csv = await request.get(`/api/pilots/${pilots[0].pilot_id}/report?format=csv`, { headers });
  expect(csv.ok()).toBeTruthy();
  expect(csv.headers()["content-type"]).toContain("text/csv");
  expect(errors).toEqual([]);
  await page.getByRole("button", { name: "Sign out", exact: true }).click();
  await expect(page.getByRole("button", { name: "Sign in", exact: true })).toBeVisible();
});
