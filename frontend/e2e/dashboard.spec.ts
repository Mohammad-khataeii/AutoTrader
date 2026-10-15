import { test, expect } from "@playwright/test";
import fs from "node:fs";
import path from "node:path";

const file = process.env.AUTOTRADER_BROWSER_ENV ?? path.resolve("../.tools/v34-test.env");
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
  const headers = { Authorization: `Basic ${Buffer.from(`${env.DASHBOARD_USERNAME}:${env.DASHBOARD_PASSWORD}`).toString("base64")}` };
  const api = await request.get("/api/overview", { headers });
  expect(api.ok()).toBeTruthy();
  const overview = await api.json();
  const expected = `EUR ${Number(overview.portfolio.available_cash).toFixed(2)}`;
  await expect(page.locator(".metric").filter({ hasText: "Available cash" }).locator("strong")).toHaveText(expected);
  for (const tab of ["Market Scanner", "Opportunities", "Autonomous Decisions", "Portfolio", "Position Management", "Order History", "Backtesting Lab", "AI Intelligence", "Risk Center", "System Health", "Settings"]) {
    await page.getByRole("button", { name: tab, exact: true }).click();
    await expect(page.getByRole("heading", { name: tab, exact: true })).toBeVisible();
  }
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
  await page.screenshot({ path: "../docs/evidence/dashboard-v34.png", fullPage: true });
  expect(errors).toEqual([]);
  await page.getByRole("button", { name: "Sign out", exact: true }).click();
  await expect(page.getByRole("button", { name: "Sign in", exact: true })).toBeVisible();
});
