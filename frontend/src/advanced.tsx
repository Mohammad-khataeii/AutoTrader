import React, { useState } from "react";
import { type Row, errorMessage, useApi, useResource } from "./api";
import {
  date,
  humanize,
  money,
  officialActions,
  parse,
  rejection,
  stateName,
} from "./model";
import {
  Badge,
  CompactTable,
  Confirm,
  Panel,
  ResourceState,
  Technical,
} from "./ui";
import {
  ExecutionQuality,
  OpportunityIntelligence,
  StrategyLab,
} from "./ResearchPanels";
import { MarketDataHealth, TradeFailureExplorer } from "./ShadowPanels";
import { PilotPanel } from "./PilotPanel";
export const advancedItems = [
  "Official Account Controls",
  "Market monitor",
  "Decision journal",
  "Execution diagnostics",
  "AI & budgets",
  "Risk & recovery",
  "System & data health",
  "Paper pilot",
  "Settings",
];
function Replay() {
  const api = useApi();
  const data = useResource("/api/backtests", { ttl: 60000 });
  const [policy, setPolicy] = useState("MARKET"),
    [busy, setBusy] = useState(false),
    [error, setError] = useState("");
  return (
    <Panel>
      <h2>Historical replay</h2>
      <p className="muted">
        Persisted completed candles, simulated execution and recorded costs. No
        orders are sent to an exchange.
      </p>
      <label>
        Replay entry policy
        <select value={policy} onChange={(e) => setPolicy(e.target.value)}>
          <option value="MARKET">Market IOC</option>
          <option value="LIMIT">Limit IOC at observed ask</option>
        </select>
      </label>
      <button
        className="primary"
        disabled={busy}
        onClick={async () => {
          setBusy(true);
          setError("");
          try {
            await api.request("/api/backtests", "POST", {
              symbol: "BTC-EUR",
              max_bars: 300,
              entry_order_type: policy,
            });
            await api.refresh("/api/backtests");
          } catch (e) {
            setError(errorMessage(e));
          } finally {
            setBusy(false);
          }
        }}
      >
        {busy ? "Running replay…" : "Run BTC-EUR historical replay"}
      </button>
      {error && (
        <p role="alert" className="notice warning">
          {error}
        </p>
      )}
      <ResourceState resource={data} label="Backtests" />
      <CompactTable
        label="Historical replays"
        rows={data.data?.runs ?? []}
        columns={[
          { label: "Run", render: (r) => r.run_id },
          { label: "Coin", render: (r) => r.symbol },
          { label: "Completed", render: (r) => date(r.completed_at, true) },
          {
            label: "Evidence",
            render: (r) => <Technical value={parse(r.payload_json)} />,
          },
        ]}
      />
    </Panel>
  );
}
export function AdvancedResearch({ auth }: { auth: string }) {
  const [tool, setTool] = useState("Historical lab");
  const api = useApi();
  const research = useResource("/api/research", {
    enabled: tool === "Historical lab",
    ttl: 300000,
  });
  const running =
    tool === "Historical lab" &&
    (research.data?.jobs ?? []).some((j: Row) =>
      ["QUEUED", "RUNNING"].includes(j.status),
    );
  useResource("/api/research", { enabled: running, poll: 5000, ttl: 300000 });
  const outcomes = useResource("/api/intelligence", {
    enabled: tool === "Opportunity outcomes",
    ttl: 60000,
  });
  return (
    <div className="advanced-research page-stack">
      <div className="section-heading">
        <h2>Advanced Research</h2>
        <label className="inline-label">
          Tool
          <select
            aria-label="Research tool"
            value={tool}
            onChange={(e) => setTool(e.target.value)}
          >
            {[
              "Historical lab",
              "Historical replay",
              "Trade failure diagnostics",
              "Opportunity outcomes",
              "Paper pilot",
            ].map((s) => (
              <option key={s}>{s}</option>
            ))}
          </select>
        </label>
      </div>
      {tool === "Historical lab" && (
        <>
          <ResourceState resource={research} label="Historical research" />
          {research.data && (
            <StrategyLab
              auth={auth}
              data={research.data}
              refresh={() => api.refresh("/api/research")}
            />
          )}
        </>
      )}
      {tool === "Historical replay" && <Replay />}
      {tool === "Trade failure diagnostics" && (
        <TradeFailureExplorer auth={auth} />
      )}{" "}
      {tool === "Opportunity outcomes" && (
        <>
          <ResourceState resource={outcomes} label="Opportunity outcomes" />
          {outcomes.data && <OpportunityIntelligence data={outcomes.data} />}
        </>
      )}
      {tool === "Paper pilot" && <PilotPanel auth={auth} />}
    </div>
  );
}
export function AdvancedScreen({ page, auth }: { page: string; auth: string }) {
  const api = useApi();
  const overview = useResource("/api/overview", {
    enabled: page === "Official Account Controls" || page === "Risk & recovery",
  });
  const system = useResource("/api/system");
  const scanner = useResource("/api/scanner", {
    enabled: page === "Market monitor" || page === "AI & budgets",
    poll: page === "Market monitor" ? 30000 : 0,
  });
  const history = useResource("/api/history", {
    enabled: page === "Decision journal" || page === "Risk & recovery",
    ttl: 60000,
  });
  const execution = useResource("/api/execution", {
    enabled: page === "Execution diagnostics",
    ttl: 30000,
  });
  const settings = useResource("/api/settings", {
    enabled: page === "Settings" || page === "Risk & recovery",
    ttl: 300000,
  });
  const ai = useResource("/api/ai", {
    enabled: page === "AI & budgets",
    ttl: 60000,
  });
  const [action, setAction] = useState("");
  const [recover, setRecover] = useState(false);
  const control = overview.data?.portfolio?.control;
  const labels: Record<string, string> = {
    start: "Start paper trading",
    pause: "Pause new entries",
    resume: "Resume paper trading",
    stop: "Stop paper trading",
    emergency: "Emergency halt",
  };
  if (page === "Paper pilot") return <PilotPanel auth={auth} />;
  return (
    <div className="page-stack">
      <div>
        <p className="eyebrow">Advanced</p>
        <h2 className="page-title">{page}</h2>
      </div>
      {page === "Official Account Controls" && (
        <>
          <ResourceState resource={overview} label="Official account" />
          <Panel>
            <Badge>{stateName(control ?? "Unavailable")}</Badge>
            <h3>Official paper account only</h3>
            <p>
              These controls never approve a strategy or enable real-money
              trading. Shadow experiments have separate controls.
            </p>
            <div className="toolbar">
              {officialActions(control)
                .filter((a) => a !== "emergency")
                .map((a) => (
                  <button
                    className={a === "stop" ? "" : "primary"}
                    key={a}
                    onClick={() => setAction(a)}
                  >
                    {labels[a]}
                  </button>
                ))}
            </div>
            {officialActions(control).includes("emergency") && (
              <div className="emergency-control">
                <div>
                  <strong>Emergency halt</strong>
                  <p className="muted small">
                    For a situation that needs immediate operator attention.
                  </p>
                </div>
                <button
                  className="danger-outline"
                  onClick={() => setAction("emergency")}
                >
                  Emergency halt
                </button>
              </div>
            )}
            <p className="small muted">
              Research mode and server risk checks still apply. Protective
              position monitoring remains controlled by the existing backend.
            </p>
          </Panel>
          {action && (
            <Confirm
              title={`${labels[action]}?`}
              action={labels[action]}
              danger={["stop", "emergency"].includes(action)}
              onCancel={() => setAction("")}
              onConfirm={async () => {
                await api.request(`/api/controls/${action}`, "POST");
                await api.refresh("/api/overview", "/api/system");
              }}
            >
              <p>
                This changes the official virtual account to{" "}
                {labels[action].toLowerCase()}. It does not affect
                shadow-account controls or grant research approval.
              </p>
              <p>Review the current account state before confirming.</p>
            </Confirm>
          )}
        </>
      )}
      {page === "Market monitor" && (
        <>
          <ResourceState resource={scanner} label="Market monitor" />
          <Panel>
            <h3>
              {scanner.data?.scanned ?? "Unavailable"} markets in the latest
              scan
            </h3>
            <p>
              {scanner.data?.status
                ? humanize(scanner.data.status)
                : "Scan status unavailable"}
            </p>
            <CompactTable
              label="Market observations"
              rows={scanner.data?.candidates ?? []}
              columns={[
                { label: "Coin", render: (r) => r.symbol },
                { label: "Bid", render: (r) => money(r.market?.best_bid) },
                { label: "Ask", render: (r) => money(r.market?.best_ask) },
                { label: "Quality", render: (r) => humanize(r.quality) },
                {
                  label: "Decision",
                  render: (r) =>
                    rejection(
                      r.decision?.rejected_reason ?? r.decision?.explanation,
                    ),
                },
              ]}
            />
            {scanner.data?.provider_errors?.length > 0 && (
              <p role="alert" className="notice warning">
                {scanner.data.provider_errors.join("; ")}
              </p>
            )}
            <Technical
              value={scanner.data}
              label="Signals, features and rejected observations"
            />
          </Panel>
        </>
      )}
      {page === "Decision journal" && (
        <>
          <ResourceState resource={history} label="Decision journal" />
          <Panel>
            <CompactTable
              label="Official decision history"
              rows={history.data?.decisions ?? []}
              columns={[
                { label: "Time", render: (r) => date(r.created_at, true) },
                { label: "Coin", render: (r) => r.symbol },
                {
                  label: "Action",
                  render: (r) =>
                    humanize(r.action ?? parse(r.payload_json).action),
                },
                {
                  label: "Reason",
                  render: (r) =>
                    rejection(
                      r.rejected_reason ?? parse(r.payload_json).explanation,
                    ),
                },
              ]}
            />
            <Technical
              value={history.data}
              label="Decision payloads, transitions and exit intentions"
            />
          </Panel>
        </>
      )}
      {page === "Execution diagnostics" && (
        <>
          <ResourceState resource={execution} label="Execution diagnostics" />
          {execution.data && <ExecutionQuality data={execution.data} />}
        </>
      )}
      {page === "AI & budgets" && (
        <>
          <ResourceState resource={ai} label="AI budgets" />
          <Panel>
            <h3>Provider: {ai.data?.provider ?? "Unavailable"}</h3>
            <p className="muted">
              {ai.data?.paid_enabled
                ? "Paid AI configured. Existing server quotas apply."
                : "Paid AI is not enabled."}
            </p>
            <dl className="facts">
              {[
                [
                  "Today",
                  `${ai.data?.budget?.daily_used ?? "Unavailable"} / ${ai.data?.budget?.daily_limit ?? "Unavailable"}`,
                ],
                [
                  "Rolling 60 minutes",
                  `${ai.data?.budget?.rolling_hour_used ?? "Unavailable"} / ${ai.data?.budget?.hourly_limit ?? "Unavailable"}`,
                ],
                [
                  "Monthly estimated spend",
                  ai.data?.budget?.estimated_spend_usd == null
                    ? "Unavailable"
                    : `USD ${ai.data.budget.estimated_spend_usd}`,
                ],
                [
                  "Confirmed provider spend",
                  ai.data?.budget?.confirmed_spend_usd == null
                    ? "Unavailable"
                    : `USD ${ai.data.budget.confirmed_spend_usd}`,
                ],
                ["Daily reset", date(ai.data?.budget?.daily_reset_at, true)],
              ].map(([label, value]) => (
                <div key={label}>
                  <dt>{label}</dt>
                  <dd>{value}</dd>
                </div>
              ))}
            </dl>
            <Technical
              value={{
                provider: ai.data,
                latest_scanner_assessment: scanner.data?.ai,
              }}
              label="Quota reservations, pricing and latest assessment"
            />
          </Panel>
        </>
      )}
      {page === "Risk & recovery" && (
        <>
          <ResourceState resource={overview} label="Account risk" />
          <Panel>
            <h3>{stateName(overview.data?.portfolio?.risk_state)}</h3>
            <dl className="facts">
              <div>
                <dt>Daily equity change</dt>
                <dd>{money(overview.data?.portfolio?.daily_equity_change)}</dd>
              </div>
              <div>
                <dt>Weekly equity change</dt>
                <dd>{money(overview.data?.portfolio?.weekly_equity_change)}</dd>
              </div>
              <div>
                <dt>Financial records</dt>
                <dd>
                  {system.data?.reconciliation?.problems?.length
                    ? "Review required"
                    : system.data?.reconciliation
                      ? "Financial records consistent"
                      : "Not checked"}
                </dd>
              </div>
            </dl>
            <button onClick={() => setRecover(true)}>
              Request risk recovery
            </button>
            <Technical
              value={{
                risk_limits: settings.data?.risk_limits,
                incidents: history.data?.incidents,
                reconciliation: system.data?.reconciliation,
              }}
              label="Risk limits, incidents and reconciliation evidence"
            />
          </Panel>
          {recover && (
            <Confirm
              title="Request reconciliation-based risk recovery?"
              action="Request recovery"
              onCancel={() => setRecover(false)}
              onConfirm={async () => {
                await api.request("/api/risk/recover", "POST");
                await api.refresh("/api/overview", "/api/system");
              }}
            >
              <p>
                The server will verify its existing financial invariants. A
                failed check prevents recovery; research approval is never
                bypassed.
              </p>
            </Confirm>
          )}
        </>
      )}
      {page === "System & data health" && (
        <>
          <ResourceState resource={system} label="System health" />
          <Panel>
            <dl className="facts">
              {["worker", "postgresql", "redis", "exchange_data"].map((k) => (
                <div key={k}>
                  <dt>{humanize(k)}</dt>
                  <dd>{system.data?.[k] ?? "Unavailable"}</dd>
                </div>
              ))}
            </dl>
            <Technical
              value={system.data}
              label="Heartbeats, coordinator leases and incidents"
            />
          </Panel>
          <MarketDataHealth auth={auth} />
        </>
      )}
      {page === "Settings" && (
        <>
          <ResourceState resource={settings} label="Settings" />
          <Panel>
            <h3>Read-only server configuration</h3>
            <p>
              The dashboard does not change trading limits, credentials,
              schedules or market-data safeguards.
            </p>
            <Technical value={settings.data} label="View server settings" />
          </Panel>
        </>
      )}
    </div>
  );
}
