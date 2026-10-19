import React, { useState } from "react";
import { ArrowUpRight, Radar } from "lucide-react";
import { type Row, type Snapshot, useResource } from "./api";
import {
  date,
  money,
  number,
  rejection,
  decisionSummary,
  shortId,
  stateName,
  strategyName,
  systemStatus,
} from "./model";
import { Badge, EquityChart, Panel, Pnl, ResourceState } from "./ui";
import { OpportunityPreview } from "./Opportunities";
export function Overview({
  system,
  onExperiments,
}: {
  system: Snapshot;
  onExperiments: () => void;
}) {
  const overview = useResource("/api/overview/summary", { poll: 30000 });
  const shadows = useResource("/api/shadow/summary", { ttl: 60000 });
  const [account, setAccount] = useState("official");
  const history = useResource("/api/history/page/equity?limit=60", {
    enabled: account === "official",
    ttl: 60000,
  });
  const p = overview.data?.portfolio;
  const experiments: Row[] = shadows.data?.experiments ?? [];
  const active = experiments.filter((e) => e.state === "SHADOW_ACTIVE");

  const shadowEquity = useResource(
    `/api/shadow/${account}/pages/equity?limit=60`,
    { enabled: account !== "official", ttl: 60000 },
  );
  const op = system.data?.last_scan?.operation ?? system.data?.operation;
  const status = systemStatus(
    system.data,
    p?.control,
    Boolean(system.error || overview.error),
  );
  const open =
    p &&
    shadows.data &&
    experiments.every((e) => e.portfolio?.positions != null)
      ? Number(p.positions) +
        experiments.reduce((sum, e) => sum + Number(e.portfolio.positions), 0)
      : undefined;
  const problem =
    system.data?.reconciliation?.problems?.length ||
    (p?.risk_state && p.risk_state !== "HEALTHY");
  const outcomes: Row[] = op?.execution_outcomes ?? [];
  const rejected = outcomes.find((r) => r.accepted === false);
  const errors = (
    system.data?.current_system_errors ??
    system.data?.incidents ??
    []
  ).filter((r: Row) => r.severity === "ERROR" && r.status !== "RESOLVED");
  const nowText = system.data?.service
    ? status === "Running"
      ? "System running."
      : status === "Offline"
        ? "Worker heartbeat is unavailable."
        : "Monitoring needs attention."
    : status === "Degraded"
      ? "Monitoring needs attention."
      : p?.control && p.control !== "RUNNING"
        ? `Official entries are ${stateName(p.control).toLowerCase()}.`
        : op?.markets_scanned != null
          ? `Monitoring ${op.markets_scanned} markets. ${Number(op.paper_entries_filled) > 0 ? "A simulated entry was filled in the latest scan." : "Waiting for a qualifying entry."}`
          : "Waiting for the first completed market scan.";
  return (
    <div className="page-stack">
      <ResourceState resource={overview} label="Official account" />
      {system.error && (
        <ResourceState resource={system} label="System status" />
      )}
      <div className="kpi-grid">
        <div className="kpi">
          <span>Official equity</span>
          <strong>{money(p?.equity)}</strong>
          <small>
            Paper account ·{" "}
            {system.data?.official?.approval?.research_only === true ||
            system.data?.operational_state === "RESEARCH_ONLY"
              ? "Research mode"
              : "Simulation"}
          </small>
        </div>
        <div className="kpi">
          <span>Shadow experiments</span>
          <strong>
            {shadows.data ? `${active.length} active` : "Unavailable"}
          </strong>
          <small>
            {shadows.data
              ? `${experiments.length} retained accounts · separate balances`
              : "Loading virtual accounts"}
          </small>
        </div>
        <div className="kpi">
          <span>Open positions</span>
          <strong>{open ?? "Unavailable"}</strong>
          <small>Across identified virtual accounts</small>
        </div>
        <div className="kpi">
          <span>System status</span>
          <strong className="status-value">
            <span
              className={`status-dot ${status === "Running" ? "positive-dot" : "warning-dot"}`}
            />
            {status}
          </strong>
          <small>
            {(system.data?.service?.worker ?? system.data?.worker) === "ok"
              ? "Worker connected"
              : "Worker status unavailable"}
          </small>
        </div>
      </div>
      <div className="balance-summary" aria-label="Official simulated balance and results">
        <div><span>Available balance</span><strong>{money(p?.available_cash)}</strong></div>
        <div><span>Reserved balance</span><strong>{money(p?.reserved_cash)}</strong></div>
        <div><span>Allocated balance</span><strong>{money(number(p?.open_exposure) != null && number(p?.reserved_cash) != null ? Number(p.open_exposure) + Number(p.reserved_cash) : undefined)}</strong></div>
        <div><span>Realized result</span><strong><Pnl value={p?.realized_pnl} /></strong></div>
        <div><span>Unrealized result</span><strong><Pnl value={p?.unrealized_pnl} /></strong></div>
      </div>
      <OpportunityPreview />
      <Panel className="happening">
        <div className="section-heading">
          <h2>What’s happening now?</h2>
          <Radar size={18} className="muted" />
        </div>
        <h3>{nowText}</h3>
        <p>
          {system.data?.official?.approval?.research_only === true ||
          system.data?.operational_state === "RESEARCH_ONLY"
            ? "The official portfolio is in research mode. No strategy is approved to place orders in this account."
            : "Official-account entries remain subject to the existing research and risk checks."}
        </p>
        {system.data?.service && (
          <>
            <p>
              {active.length} experimental strategies active. Official account
              entries {String(p?.control ?? "unavailable").toLowerCase()}.
            </p>
            <p>
              {system.data.last_scan?.markets?.length
                ? `Latest completed scan: ${system.data.last_scan.markets.join(", ")}.`
                : "Waiting for a confirmed completed scan."}
            </p>
            {system.data.last_scan?.completed_at && (
              <p className="small muted">
                Scan completed {date(system.data.last_scan.completed_at, true)}.
              </p>
            )}
            {(system.data.shadows ?? [])
              .filter((e: Row) => e.state === "SHADOW_ACTIVE")
              .map((e: Row) => (
                <p key={e.experiment_id} className="activity-reason">
                  Latest {e.strategy_id?.split("_")[0]} ·{" "}
                  {shortId(e.experiment_id)}:{" "}
                  {e.latest_decision
                    ? decisionSummary(e.latest_decision)
                    : "No recorded evaluation yet"}
                  {e.last_evaluation_at
                    ? ` · ${date(e.last_evaluation_at, true)}`
                    : ""}
                </p>
              ))}
          </>
        )}
        {rejected && (
          <p className="activity-reason">
            <span className="subtle-dot" />
            {rejected.symbol}: {rejection(rejected.reason)}
          </p>
        )}
        {problem && (
          <p role="alert" className="notice warning">
            {system.data?.reconciliation?.problems?.length
              ? "Financial records need review."
              : `Account risk state: ${stateName(p?.risk_state)}.`}{" "}
            Open Advanced → Risk & recovery for the recorded evidence.
          </p>
        )}
        {errors.length > 0 && (
          <p role="alert" className="notice warning">
            Latest recorded error:{" "}
            {rejection(errors[0].message ?? errors[0].status)}
          </p>
        )}
        <div className="section-footer">
          <span className="muted small">
            Last updated {date(system.updatedAt, true)}
          </span>
          <Badge>Simulated Mode</Badge>
        </div>
      </Panel>
      <div className="section-heading">
        <h2>Active experiments</h2>
        <button className="text-button" onClick={onExperiments}>
          View all <ArrowUpRight size={15} />
        </button>
      </div>
      <ResourceState resource={shadows} label="Experiment snapshot" />
      <div className="overview-experiments">
        {active.slice(0, 4).map((e) => (
          <button
            className="mini-experiment"
            key={e.experiment_id}
            onClick={onExperiments}
          >
            <span className="strategy-letter">
              {e.manifest?.strategy_id?.split("_")[0] ?? "?"}
            </span>
            <div>
              <strong>{strategyName(e.manifest?.strategy_id)}</strong>
              <span className="muted small">
                Instance {shortId(e.experiment_id)} ·{" "}
                {e.performance?.closed_trades ?? "Unavailable"} closed positions ·{" "}
                {e.source_matches === false ? "New entries blocked" : "Active"}
              </span>
            </div>
            <div className="mini-pnl">
              <Pnl value={e.performance?.net_pnl} />
              <span className="muted small">Virtual P&L</span>
            </div>
          </button>
        ))}
        {shadows.data && !active.length && (
          <p className="muted">
            No active experiments. Existing histories remain available in
            Experiments.
          </p>
        )}
      </div>
      {shadows.updatedAt && (
        <p className="small muted snapshot-note">
          Experiment snapshot {date(shadows.updatedAt, true)}. Refresh to
          update.
        </p>
      )}
      <div className="section-heading">
        <h2>Account performance</h2>
        <label className="inline-label">
          Account
          <select
            aria-label="Equity chart account"
            value={account}
            onChange={(e) => setAccount(e.target.value)}
          >
            <option value="official">Official paper account</option>
            {experiments.map((e) => (
              <option value={e.experiment_id} key={e.experiment_id}>
                {strategyName(e.manifest?.strategy_id)} ·{" "}
                {shortId(e.experiment_id)}
              </option>
            ))}
          </select>
        </label>
      </div>
      {account === "official" && (
        <ResourceState resource={history} label="Equity history" />
      )}
      <EquityChart
        rows={
          account === "official"
            ? (history.data?.items ?? [])
            : (shadowEquity.data?.items ?? [])
        }
        title={account === "official" ? "Official equity" : "Experiment equity"}
        caption="Accounts are never combined"
      />
    </div>
  );
}
