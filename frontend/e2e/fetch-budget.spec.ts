import { test, expect } from "@playwright/test";
import fs from "node:fs";
import { mockApi, signIn } from "./fixtures/v43";
test("V4.4 uses bounded APIs without increasing the V4.3 polling cadence over 65 seconds", async ({
  browser,
}) => {
  const rows = [];
  for (const version of ["V4.3", "V4.4"]) {
    const page = await browser.newPage();
    const api = await mockApi(page);
    await page.clock.install();
    if (version === "V4.3") {
      await page.goto(
        process.env.AUTOTRADER_BEFORE_URL ?? "http://127.0.0.1:13045",
      );
      await page.getByLabel("Username", { exact: true }).fill("admin");
      await page
        .getByLabel("Password", { exact: true })
        .fill("fixture-password");
      await page.getByRole("button", { name: "Sign in", exact: true }).click();
      await expect(
        page.locator(".kpi").first().getByText("€500.00"),
      ).toBeVisible();
    } else {
      await signIn(page);
      await expect(
        page.getByText("System running.", { exact: false }),
      ).toBeVisible();
    }
    for(let second=0;second<65;second++){await page.clock.runFor(1000);await page.evaluate(()=>Promise.resolve());}
    rows.push({
      version,
      requests: api.requests.length,
      resources: Object.fromEntries(
        [...new Set(api.requests.map((r) => r.path))].map((p) => [
          p,
          api.requests.filter((r) => r.path === p).length,
        ]),
      ),
      broad_history_requests: api.requests.filter(r=>["shadow","history","research","intelligence"].includes(r.wirePath)).length,
      mutations: api.requests.filter((r) => r.method !== "GET").length,
    });
    await page.close();
  }
  expect(rows[1].requests).toBeLessThanOrEqual(rows[0].requests + 1);
  expect(rows[1].broad_history_requests).toBe(0);
  expect(rows[0].broad_history_requests).toBeGreaterThan(0);
  expect(rows.every((r) => r.mutations === 0)).toBe(true);
  fs.writeFileSync(
    `${process.env.AUTOTRADER_BROWSER_EVIDENCE ?? "../docs/evidence/v4_5"}/request-comparison.json`,
    JSON.stringify(
      {
        kind: "CONTROLLED_BROWSER_REAL_FRONTEND_CODE_MOCK_API",
        window_seconds: 65,
        before_url: "loopback V4.3 baseline",
        after_url: "loopback V4.4 build",
        rows,
        request_delta: rows[1].requests - rows[0].requests,
        interpretation: "Cadence retained; full-history polling replaced with bounded summaries/pages. Byte reduction is measured separately against real local PostgreSQL.",
      },
      null,
      2,
    ) + "\n",
  );
});
