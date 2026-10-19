import { test, expect } from "@playwright/test";
import fs from "node:fs";
import path from "node:path";
const env = Object.fromEntries(
  fs
    .readFileSync(
      process.env.AUTOTRADER_BROWSER_ENV ??
        path.resolve("../.tools/v42-test.env"),
      "utf8",
    )
    .trim()
    .split(/\r?\n/)
    .map((l) => {
      const i = l.indexOf("=");
      return [l.slice(0, i), l.slice(i + 1)];
    }),
);
test("retained V4.2 shadow controls, five complete exports, official isolation and diagnostics", async ({
  page,
  request,
}) => {
  test.setTimeout(90000);
  const headers = {
    Authorization: `Basic ${Buffer.from(`${env.DASHBOARD_USERNAME}:${env.DASHBOARD_PASSWORD}`).toString("base64")}`,
  };
  expect((await request.get("/api/shadow")).status()).toBe(401);
  const before = await (await request.get("/api/overview", { headers })).json();
  const list = await (await request.get("/api/shadow", { headers })).json();
  const existing = list.experiments.find(
    (e: any) => e.state === "SHADOW_ACTIVE",
  );
  expect(existing).toBeTruthy();
  await page.goto("/");
  await page
    .getByLabel("Username", { exact: true })
    .fill(env.DASHBOARD_USERNAME);
  await page
    .getByLabel("Password", { exact: true })
    .fill(env.DASHBOARD_PASSWORD);
  await page.getByRole("button", { name: "Sign in", exact: true }).click();
  await page.getByRole("button", { name: "Strategies", exact: true }).click();
  const id = existing.experiment_id.slice(0, 8);
  await page
    .getByRole("button", { name: new RegExp(`^Open .* ${id}$`) })
    .click();
  await page
    .getByRole("button", { name: `Pause experiment ${id}`, exact: true })
    .click();
  await expect(
    page.getByRole("button", { name: `Resume experiment ${id}`, exact: true }),
  ).toBeVisible();
  await page
    .getByRole("button", { name: `Resume experiment ${id}`, exact: true })
    .click();
  await page.getByText("Export", { exact: true }).click();
  for (const label of [
    "Financial report",
    "Orders",
    "Fills",
    "Journal",
    "Equity",
  ]) {
    const d = page.waitForEvent("download");
    await page.getByRole("button", { name: label, exact: true }).click();
    expect((await d).suggestedFilename()).toContain(existing.experiment_id);
  }
  await page
    .getByText("Performance and financial integrity", { exact: true })
    .click();
  await expect(
    page.getByText("Financial records consistent", { exact: true }),
  ).toBeVisible();
  const after = await (await request.get("/api/overview", { headers })).json();
  expect(after.portfolio.available_cash).toBe(before.portfolio.available_cash);
  expect(after.orders.length).toBe(before.orders.length);
  expect(after.fills.length).toBe(before.fills.length);
  await page.getByRole("button", { name: "Research", exact: true }).click();
  await page
    .getByRole("button", { name: "Advanced Research", exact: true })
    .click();
  await page
    .getByLabel("Research tool")
    .selectOption("Outcome diagnostics");
  await page.getByLabel("Failure outcome").selectOption("LOSS");
  await page
    .getByLabel("Failure strategy", { exact: true })
    .fill("A_TREND_PULLBACK");
  await expect(page.getByText("833 positions", { exact: false })).toBeVisible();
  await expect(
    page.getByLabel("Inspect failure position").locator("option"),
  ).not.toHaveCount(1);
  await page.getByLabel("Inspect failure position").selectOption({ index: 1 });
  await page
    .getByText("View causal features, signal evidence and counterfactuals", {
      exact: true,
    })
    .click();
  await expect(
    page.locator("pre").filter({ hasText: "signal_evidence" }),
  ).toBeVisible();
  await page.locator(".advanced-menu > summary").click();
  await page
    .getByRole("button", { name: "System & data health", exact: true })
    .click();
  await expect(
    page.getByRole("heading", {
      name: "Public market-data health",
      exact: true,
    }),
  ).toBeVisible();
});
