import fs from "node:fs";
import type { Page } from "@playwright/test";
// Synthetic acceptance only. IDs are user-supplied; balances/states are test cases, not production observations.
export const ids = [
  "9b18cabcc94c45fe84a59917226ebb58",
  "39cddc6d7e584a369ce223945f06e629",
  "52746de1116e4852b61cb16988917545",
  "2f12b0257a3b453a8e2a61ab695d8146",
];
export function fixture() {
  const timestamp = new Date().toISOString();
  const portfolio = {
    equity: "500",
    cash: "500",
    available_cash: "500",
    initial_cash: "500",
    positions: "0",
    orders: "0",
    control: "RUNNING",
    risk_state: "HEALTHY",
    total_net_pnl: "0",
    reserved_cash: "0",
    open_exposure: "0",
  };
  const history = {
    equity: [],
    decisions: [],
    signals: [],
    exit_intents: [],
    incidents: [],
    transitions: [],
  };
  const experiments = ids.map((id, i) => ({
    experiment_id: id,
    name: `Acceptance ${i + 1}`,
    created_at: `2026-10-16T12:0${i}:00Z`,
    state: ["SHADOW_ACTIVE", "PAUSED", "SHADOW_ACTIVE", "STOPPED"][i],
    manifest: {
      strategy_id:
        i === 2 ? "A2_CONFIRMED_PULLBACK" : "B2_CONFIRMED_COMPRESSION",
      strategy_version: "4.2.0-experimental.1",
      data_kind: "SYNTHETIC_ACCEPTANCE",
      frozen_at: timestamp,
      parameters: {},
    },
    portfolio: { ...portfolio },
    performance: {
      net_pnl: "0",
      closed_trades: 0,
      fees: "0",
      max_drawdown: "0",
      win_rate: null,
    },
    history: { ...history },
    positions: [],
    orders: [],
    fills: [],
    targets: [],
    reconciliation: [],
    source_matches: true,
    history_window_limit: 500,
  }));
  const report = JSON.parse(
    fs.readFileSync(
      new URL("../../../docs/evidence/v4_2-summary.json", import.meta.url),
      "utf8",
    ),
  );
  return {
    overview: {
      application_version: "4.2.0",
      portfolio: { ...portfolio },
      positions: [],
      orders: [],
      fills: [],
      targets: [],
    },
    system: {
      worker: "ok",
      postgresql: "ok",
      redis: "ok",
      exchange_data: "OK",
      operational_state: "RESEARCH_ONLY",
      risk_state: "HEALTHY",
      operation: {
        markets_scanned: 3,
        successful_observations: 3,
        paper_entries_filled: 0,
        execution_outcomes: [
          {
            symbol: "BTC-EUR",
            accepted: false,
            reason: "decision_not_accepted",
          },
        ],
      },
      reconciliation: { problems: [] },
      incidents: [],
    },
    shadow: {
      enabled: true,
      maximum_experiments: 4,
      official: { ...portfolio },
      experiments,
      presets: [
        {
          strategy_id: "B2_CONFIRMED_COMPRESSION",
          hypothesis:
            "Confirmed compression after causal higher-timeframe checks.",
        },
        {
          strategy_id: "A2_CONFIRMED_PULLBACK",
          hypothesis: "Confirmed pullback with higher-timeframe alignment.",
        },
      ],
    },
    history,
    research: {
      latest: null,
      experimental_latest: report,
      experimental_registry: [],
      registry: [],
      runs: [],
      datasets: [],
      jobs: [],
    },
    execution: { positions: [] },
    ai: {
      provider: "mock",
      paid_enabled: false,
      budget: { daily_used: 0, daily_limit: 30 },
    },
    settings: {},
    scanner: { status: "COMPLETED", scanned: 3, candidates: [] },
    pilots: [],
    backtests: { runs: [] },
    intelligence: { feedback: [] },
    "market-data/health": { requests: 10, request_429: 1, caches: [] },
  };
}
export async function mockApi(page: Page, data: any = fixture()) {
  const requests: { path: string; method: string }[] = [];
  let failOverview = false;
  await page.route("**/readyz", (route) =>
    route.fulfill({ json: { ready: true, live_trading_enabled: false } }),
  );
  await page.route("**/api/**", async (route) => {
    const req = route.request(),
      path = new URL(req.url()).pathname.replace("/api/", "");
    requests.push({ path, method: req.method() });
    if (failOverview && path === "overview")
      return route.fulfill({ status: 503, body: "Gateway unavailable" });
    if (path === "shadow" && req.method() === "POST") {
      if (data.shadow.experiments.length >= data.shadow.maximum_experiments)
        return route.fulfill({
          status: 409,
          json: { detail: "bounded shadow limit reached" },
        });
      const input = req.postDataJSON();
      const created = {
        ...structuredClone(data.shadow.experiments[0]),
        experiment_id: "acceptance-created-instance",
        name: input.name,
        state: "SHADOW_ACTIVE",
        created_at: new Date().toISOString(),
        manifest: {
          ...data.shadow.experiments[0].manifest,
          strategy_id: input.strategy_id,
        },
      };
      data.shadow.experiments.push(created);
      return route.fulfill({ status: 201, json: created });
    }
    if (path.startsWith("shadow/") && req.method() === "POST") {
      const [, id, action] = path.split("/");
      const e = data.shadow.experiments.find(
        (r: any) => r.experiment_id === id,
      );
      if (!e || e.state === "STOPPED")
        return route.fulfill({
          status: 409,
          json: { detail: "shadow state cannot transition" },
        });
      e.state =
        action === "pause"
          ? "PAUSED"
          : action === "resume"
            ? "SHADOW_ACTIVE"
            : "STOPPED";
      return route.fulfill({ json: e });
    }
    if (
      path.startsWith("shadow/") &&
      (path.includes("history/") || path.endsWith("export"))
    )
      return route.fulfill({
        body: path.endsWith("export")
          ? JSON.stringify({ kind: "SYNTHETIC_ACCEPTANCE" })
          : '{"account_id":"shadow:fixture","fixture":true}\n',
        contentType: path.endsWith("export")
          ? "application/json"
          : "application/x-ndjson",
      });
    if (path.startsWith("research/trade-failures"))
      return route.fulfill({
        json: { total: 833, matched: 0, positions: [], limitations: [] },
      });
    return route.fulfill({ json: data[path] ?? {} });
  });
  return {
    requests,
    data,
    failOverview: () => {
      failOverview = true;
    },
    recoverOverview: () => {
      failOverview = false;
    },
  };
}
export async function signIn(page: Page) {
  await page.goto("/");
  await page.getByLabel("Username", { exact: true }).fill("admin");
  await page.getByLabel("Password", { exact: true }).fill("fixture-password");
  await page.getByRole("button", { name: "Sign in", exact: true }).click();
  await page.getByRole("heading", { name: "Overview", exact: true }).waitFor();
}
