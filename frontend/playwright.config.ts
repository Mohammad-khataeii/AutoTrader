import { defineConfig } from "@playwright/test";

export default defineConfig({
  testDir: "./e2e",
  workers: 1,
  use: {
    baseURL: process.env.AUTOTRADER_BROWSER_URL ?? "http://127.0.0.1:13043",
    headless: true,
    trace: "off",
    screenshot: "only-on-failure",
  },
  reporter: [
    ["list"],
    [
      "json",
      {
        outputFile:
          process.env.AUTOTRADER_BROWSER_REPORT ??
          "../docs/evidence/v4_3/playwright.json",
      },
    ],
  ],
});
