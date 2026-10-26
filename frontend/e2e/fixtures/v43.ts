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
  const requests: { path: string; method: string; wirePath: string }[] = [];
  let failOverview = false;
  let signedIn = false;
  await page.route("**/readyz", (route) =>
    route.fulfill({ json: { ready: true, live_trading_enabled: false } }),
  );
  await page.route("**/api/**", async (route) => {
    const req = route.request(),
      wirePath = new URL(req.url()).pathname.replace("/api/", "");
    const url = new URL(req.url());
    const path =
      (
        {
          "overview/summary": "overview",
          "shadow/summary": "shadow",
          "research/summary": "research",
          "monitoring/summary": "system",
          "intelligence/summary": "intelligence",
          "history/page/equity": "history",
        } as Record<string, string>
      )[wirePath] ?? wirePath;
    if (wirePath === "session") {
      if (req.method() === "POST") signedIn = true;
      if (req.method() === "DELETE") {signedIn = false;return route.fulfill({json:{signed_out:true}});}
      return route.fulfill(signedIn ? {json:{username:"admin",csrf_token:"synthetic-csrf-session"}} : {status:401,json:{detail:"Sign in required"}});
    }
    if (wirePath === "personal-paper") return route.fulfill({json:data.personal_paper ?? {
      state:"PAPER_EXPERIMENTAL_ACTIVE",observed_at:new Date().toISOString(),runtime_matches:true,evidence_category:"SYNTHETIC_ACCEPTANCE",
      portfolio:{initial_cash:"7000",cash:"7000",equity:"7000",available_cash:"7000",reserved_cash:"0",open_exposure:"0",total_net_pnl:"0",realized_pnl:"0",unrealized_pnl:"0",current_drawdown:"0",risk_state:"HEALTHY",control:"RUNNING"},
      cash_flow:{spent_on_buys_eur:"0",sale_proceeds_eur:"0",fees_total_eur:"0"},holdings:[],markets:[],fills:[],orders:[],strategies:[],reconciliation:[],
      performance:{open_positions:0,closed_positions:0,buy_fills:0,sell_fills:0,capital_utilization:"0"},worker_health:{fresh:true},
      scan:{observed_at:new Date().toISOString(),markets:["BTC-EUR","ETH-EUR","SOL-EUR"]},position_monitor:{heartbeat:new Date().toISOString()}
    }});
    if (wirePath === "personal-paper/activity") return route.fulfill({json:{evaluations:[],events:[],evidence_category:"SYNTHETIC_ACCEPTANCE"}});
    if (/personal-paper\/markets\/.+\/chart/.test(wirePath)) {
      const symbol=wirePath.split("/")[2];
      const candles=Array.from({length:24},(_,i)=>({timestamp:new Date(Date.now()-(25-i)*300000).toISOString(),open:String(100+i),high:String(102+i),low:String(99+i),close:String(101+i),volume:"10",source:"synthetic-browser-fixture"}));
      return route.fulfill({json:{symbol,candles,timeframe:"5m",range:url.searchParams.get("range"),evidence_category:"SYNTHETIC_ACCEPTANCE",expected_bars:72,missing_intervals:0}});
    }
    requests.push({ path, method: req.method(), wirePath });
    if (wirePath === "shadow/summary")
      return route.fulfill({
        json: {
          ...data.shadow,
          experiments: data.shadow.experiments.filter(
            (e: any) =>
              Boolean(e.archived_at) ===
              (url.searchParams.get("archived") === "true"),
          ),
          occupied_slots: data.shadow.experiments.filter(
            (e: any) => !e.archived_at,
          ).length,
          archived_count: data.shadow.experiments.filter(
            (e: any) => e.archived_at,
          ).length,
        },
      });
    if (wirePath === "monitoring/summary")
      return route.fulfill({
        json: {
          ...data.system,
          service: {
            worker: data.system.worker,
            postgresql: data.system.postgresql,
          },
          market_data: { state: data.system.exchange_data, fresh: true },
          official: {
            control: data.overview.portfolio.control,
            approval: { research_only: true },
          },
          last_scan: {
            markets: ["BTC-EUR", "ETH-EUR", "SOL-EUR"],
            completed_at: new Date().toISOString(),
            operation: data.system.operation,
          },
          shadows: data.shadow.experiments
            .filter((e: any) => !e.archived_at)
            .map((e: any) => ({
              ...e,
              strategy_id: e.manifest.strategy_id,
              latest_decision: e.latest_decision ?? null,
              last_evaluation_at: e.last_evaluation_at ?? null,
            })),
          current_system_errors: [],
        },
      });
    if (wirePath.startsWith("history/page/"))
      return route.fulfill({
        json: {
          items: data.history[wirePath.split("/").pop()!] ?? [],
          next_cursor: null,
          limit: 30,
        },
      });
    if (wirePath.startsWith("shadow/") && wirePath.endsWith("/view")) {
      const e = data.shadow.experiments.find(
        (e: any) => e.experiment_id === wirePath.split("/")[1],
      );
      return route.fulfill({ json: e ?? {} });
    }
    if (wirePath.startsWith("shadow/") && wirePath.includes("/pages/")) {
      const parts = wirePath.split("/");
      const e = data.shadow.experiments.find(
        (e: any) => e.experiment_id === parts[1],
      );
      return route.fulfill({
        json: {
          items: e?.history?.[parts[3]] ?? e?.[parts[3]] ?? [],
          next_cursor: null,
          limit: 10,
        },
      });
    }
    if (wirePath.startsWith("shadow/") && req.method() === "DELETE") {
      const e = data.shadow.experiments.find(
        (e: any) => e.experiment_id === wirePath.split("/")[1],
      );
      if (
        !e ||
        !["PAUSED", "STOPPED"].includes(e.state) ||
        (e.positions ?? []).some((p: any) => Number(p.quantity) > 0)
      )
        return route.fulfill({
          status: 409,
          json: { detail: "cannot_archive_active_or_open_positions" },
        });
      e.state = "STOPPED";
      e.archived_at ??= new Date().toISOString();
      return route.fulfill({
        json: {
          experiment_id: e.experiment_id,
          archived_at: e.archived_at,
          history_preserved: true,
          slot_released: true,
        },
      });
    }
    if (wirePath === "trades") {
      const kind =
          url.searchParams.get("kind") === "orders" ? "orders" : "positions",
        view = url.searchParams.get("view"),
        account = url.searchParams.get("account");
      const accounts = [
        { id: "official", name: "Official", data: data.overview },
        ...data.shadow.experiments
          .filter((e: any) => !e.archived_at)
          .map((e: any) => ({ id: e.experiment_id, name: e.name, data: e })),
      ];
      const items = accounts
        .filter((a: any) => account === "all" || a.id === account)
        .flatMap((a: any) =>
          (a.data[kind] ?? [])
            .filter(
              (r: any) =>
                kind === "orders" ||
                (view === "open"
                  ? Number(r.quantity) > 0 && !r.closed_at
                  : Boolean(r.closed_at)),
            )
            .map((r: any) => ({
              account: a.id,
              accountName: a.name,
              symbol: r.symbol,
              kind: kind === "orders" ? "order" : "position",
              key: a.id + ":" + (r.position_id ?? r.order_id),
              record: r,
            })),
        );
      return route.fulfill({ json: { items, next_cursor: null, limit: 30 } });
    }
    if (wirePath.startsWith("trades/")) {
      const [, id, kind, identity] = wirePath.split("/");
      const account =
        id === "official"
          ? data.overview
          : data.shadow.experiments.find((e: any) => e.experiment_id === id);
      return route.fulfill({
        json: {
          ...account,
          history: id === "official" ? data.history : account?.history,
          record: account?.[kind === "position" ? "positions" : "orders"]?.find(
            (r: any) => (r.position_id ?? r.order_id) === identity,
          ),
        },
      });
    }

    if (failOverview && path === "overview")
      return route.fulfill({ status: 503, body: "Gateway unavailable" });
    if (path === "shadow" && req.method() === "POST") {
      if (
        data.shadow.experiments.filter((e: any) => !e.archived_at).length >=
        data.shadow.maximum_experiments
      )
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
  await page.getByRole("heading", { name: "Dashboard", exact: true }).waitFor();
}
