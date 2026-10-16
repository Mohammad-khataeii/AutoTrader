import { test, expect } from "@playwright/test";
import fs from "node:fs";
import { mockApi, signIn } from "./fixtures/v43";
test("same-fixture V4.2 versus V4.3 overview request budget over 65 seconds", async ({
  browser,
}) => {
  const rows = [];
  for (const version of ["V4.2", "V4.3"]) {
    const page = await browser.newPage();
    const api = await mockApi(page);
    await page.clock.install();
    if (version === "V4.2") {
      await page.goto(
        process.env.AUTOTRADER_BEFORE_URL ?? "http://127.0.0.1:13042",
      );
      await page.getByLabel("Username", { exact: true }).fill("admin");
      await page
        .getByLabel("Password", { exact: true })
        .fill("fixture-password");
      await page.getByRole("button", { name: "Sign in", exact: true }).click();
      await expect(
        page
          .locator(".metric")
          .filter({ hasText: "Available cash" })
          .locator("strong"),
      ).toHaveText("EUR 500.00");
    } else {
      await signIn(page);
      await expect(
        page.getByText("Monitoring 3 markets.", { exact: false }),
      ).toBeVisible();
    }
    await page.clock.runFor(65000);
    rows.push({
      version,
      requests: api.requests.length,
      resources: Object.fromEntries(
        [...new Set(api.requests.map((r) => r.path))].map((p) => [
          p,
          api.requests.filter((r) => r.path === p).length,
        ]),
      ),
      mutations: api.requests.filter((r) => r.method !== "GET").length,
    });
    await page.close();
  }
  expect(rows[1].requests).toBeLessThan(rows[0].requests / 2);
  expect(rows.every((r) => r.mutations === 0)).toBe(true);
  fs.writeFileSync(
    "../docs/evidence/v4_3/request-comparison.json",
    JSON.stringify(
      {
        kind: "CONTROLLED_BROWSER_REAL_FRONTEND_CODE_MOCK_API",
        window_seconds: 65,
        before_url: "loopback old V4.2 build",
        after_url: "loopback V4.3 dev build",
        rows,
        reduction: 1 - rows[1].requests / rows[0].requests,
      },
      null,
      2,
    ) + "\n",
  );
});
