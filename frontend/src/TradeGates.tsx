import React, { useState } from "react";
import { type Row, useResource } from "./api";
import { conditionName, dataKind, date, humanize, strategyName } from "./model";
import { Badge, Panel, ResourceState, Technical } from "./ui";

function AccountGates({ account }: { account: Row }) {
  const [cursor, setCursor] = useState("");
  const result = useResource(`/api/trade-gates/${account.experiment_id}?limit=100${cursor ? `&cursor=${encodeURIComponent(cursor)}` : ""}`, { poll: cursor ? undefined : 15000 });
  const data = result.data;
  return <Panel>
    <h2>{strategyName(account.manifest.strategy_id)} · {account.experiment_id.slice(0, 8)}</h2>
    <p className="muted">{dataKind(account.manifest.data_kind)}</p>
    <ResourceState resource={result} label="Trade gate evidence" />
    {data && <>
      <p>{data.counts.evaluations} recorded evaluations in this page. {data.counts.eligible_signals} observed eligible signals; {data.counts.accepted_buy_decisions} accepted BUY decisions; {data.counts.allocation_attempts} observed allocation attempts; {data.counts.execution_attempts} observed execution attempts.</p>
      <p>{data.lifetime_financial_counts.paper_fills} lifetime paper fills; {data.lifetime_financial_counts.open_positions} open positions; {data.lifetime_financial_counts.closed_positions} closed positions.</p>
      <Badge tone={data.runtime_compatibility.compatible ? "positive" : "warning"}>Frozen runtime {data.runtime_compatibility.compatible ? "compatible" : "blocked"}</Badge>{" "}
      <Badge tone={data.safety.stale || data.safety.status !== "CONSISTENT" ? "warning" : "positive"}>Reconciliation {data.safety.status}{data.safety.stale ? " · stale" : ""}</Badge>
      <h3>Actual first blocking stage</h3>
      {Object.entries(data.causal_first_blockers).map(([name, count]) => <p key={name}>{name === "pending_execution" ? "Execution outcome pending or unrecorded" : name.startsWith("strategy:") ? conditionName(name.slice(9)) : humanize(name)}: {String(count)}</p>)}
      <h3>Independent failures · conditions may overlap</h3>
      {Object.entries(data.independent_failures).map(([name, value]) => { const v = value as Row; return <p key={name}>{humanize(name)}: {v.count} ({v.percent_of_evaluations}%)</p>; })}
      <p className="muted">{data.window.unannotated} unannotated decisions; {data.diagnostic_mismatches} diagnostic mismatches. Counts describe recorded events on this page. Missing telemetry remains unknown; an observed zero is not proof that an unrecorded stage was never reached. Pre-strategy skips are {data.last_scan_observation ? "recorded separately below" : "unavailable for earlier scans"}.</p>
      <Technical value={data.last_scan_observation} label="Latest scan and skipped candidates" />
      <h3>Decision evidence</h3>
      {data.decisions.map((d: Row) => <details key={d.decision_id}><summary>{d.symbol} · {date(d.created_at, true)} · {d.explanation?.reason ?? d.rejected_reason ?? "No recorded reason"}</summary><Technical value={d.explanation ?? { evidence: "Unavailable" }} label="All conditions and recorded values" /></details>)}
      <div className="toolbar"><button disabled={!cursor} onClick={() => setCursor("")}>Latest evaluations</button><button disabled={!data.next_cursor} onClick={() => setCursor(data.next_cursor)}>Older evaluations</button></div>
    </>}
  </Panel>;
}
export function TradeGates() {
  const accounts = useResource("/api/shadow/summary", { poll: 15000 });
  const monitoring = useResource("/api/monitoring/summary", { poll: 15000 });
  const health = monitoring.data;
  return <div className="trade-gates">
    <Panel><h2>Scanner and portfolio safety</h2>
      <ResourceState resource={monitoring} label="Scanner health" />
      {health && <><p>Last completed scan: {date(health.last_scan?.completed_at, true)}. Market data {health.market_data?.state}; worker {health.service?.worker}; Redis {health.service?.redis}. Risk {health.risk_state}.</p><p>Live trading: {health.live_trading_enabled === false ? "disabled · verified configuration" : "configuration requires attention"}. Scanner availability, strategy eligibility and financial fills are separate measures.</p>{["BTC", "ETH", "SOL"].map(symbol => { const cache = health.market_data_quality?.caches?.find((c: Row) => c.key.startsWith(symbol + "-EUR:")); return <p key={symbol}>{symbol} completed-candle cache: {cache ? `${Math.round(cache.age_seconds)}s since refresh · ${cache.observations} observations` : "unavailable"}</p>; })}<p>Revolut X rate limits: {health.market_data_quality?.request_429 != null ? `${health.market_data_quality.request_429} recorded 429 responses in the retained counter window` : "no telemetry retained for this data source"}. See measurement windows below.</p><Technical value={health.market_data_quality} label="BTC / ETH / SOL freshness and Revolut X rate limits" /></>}
    </Panel>
    <ResourceState resource={accounts} label="Experiments" />
    {(accounts.data?.experiments ?? []).filter((a: Row) => a.state === "SHADOW_ACTIVE").map((a: Row) => <AccountGates key={a.experiment_id} account={a} />)}
  </div>;
}
