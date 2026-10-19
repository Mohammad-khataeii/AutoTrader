import React, { useState } from "react";
import { type Row, useResource } from "./api";
import { conditionName, dataKind, date, humanize, strategyName } from "./model";
import { Badge, Panel, ResourceState, Technical } from "./ui";

function AccountGates({ account }: { account: Row }) {
  const [cursor, setCursor] = useState("");
  const result = useResource(`/api/trade-gates/${account.experiment_id}?limit=30${cursor ? `&cursor=${encodeURIComponent(cursor)}` : ""}`, { poll: cursor ? undefined : account.archived_at ? 60000 : 15000 });
  const data = result.data;
  return <Panel>
    <h2>{strategyName(account.manifest.strategy_id)} · {account.experiment_id.slice(0, 8)}</h2>
    <p className="muted">{dataKind(account.manifest.data_kind)}</p>
    <ResourceState resource={result} label="Decision evidence" />
    {data && <>
      <p>Account {humanize(data.state ?? account.state)} · {data.archived_at ? "Archived" : "Active registry"} · {data.runtime_generation ?? "UNKNOWN runtime"}</p>
      <p>{data.counts.evaluations} recorded evaluations in this page. {data.window.unannotated && !data.counts.eligible_signals ? "NOT_RECORDED" : data.counts.eligible_signals} observed eligible signals; {data.counts.accepted_buy_decisions} accepted BUY decisions; {data.counts.allocation_attempts} observed allocation attempts; {data.window.unannotated && !data.counts.execution_attempts ? "NOT_RECORDED" : data.counts.execution_attempts} observed execution attempts.</p>
      <p>{data.lifetime_financial_counts.paper_fills} lifetime paper fills; {data.lifetime_financial_counts.open_positions} open positions; {data.lifetime_financial_counts.closed_positions} closed positions.</p>
      <p>Technical setups: {data.qualification_counts?.technical ?? "NOT_RECORDED"}. Economically feasible: {data.qualification_counts?.economic ?? "NOT_RECORDED"}. Predictive value remains unvalidated.</p>
      <Badge tone={data.runtime_compatibility.compatible ? "positive" : "negative"}>Frozen runtime {data.runtime_compatibility.compatible ? "compatible" : "blocked"}</Badge>{" "}
      <Badge tone={data.safety.stale || data.safety.status !== "CONSISTENT" ? "warning" : "positive"}>Reconciliation {data.safety.status}{data.safety.stale ? " · stale" : ""}</Badge>
      {!data.runtime_compatibility.compatible && <p role="alert">Critical: frozen runtime identity is incompatible. Entry execution is blocked. {data.runtime_compatibility.reason}</p>}
      <h3>Execution progression</h3>
      <div className="table-wrap" tabIndex={0} role="region" aria-label="Execution progression"><table><thead><tr><th>Stage</th><th>Evidence</th><th>Succeeded</th><th>Rejected</th><th>Outcome unavailable</th><th>System exceptions</th></tr></thead><tbody>{Object.entries(data.execution_stages ?? {}).map(([stage, value]) => { const v = value as Row; return <tr key={stage}><td>{humanize(stage)}</td><td>{v.status}</td>{["succeeded", "rejected", "outcome_unavailable", "exceptions"].map(k => <td key={k}>{v[k] ?? (v.status === "NEVER_REACHED" ? "NEVER_REACHED" : "NOT_RECORDED")}</td>)}</tr>; })}</tbody></table></div>
      <p>Last evaluation: {date(data.decisions[0]?.created_at, true)}. Latest eligible setup in this page: {date(data.recent_in_window?.eligible?.created_at, true)}. Latest accepted BUY: {date(data.recent_in_window?.accepted_buy?.created_at, true)}.</p>
      <p>Latest execution refusal in this page: {data.recent_in_window?.refusal?.reason ?? "NOT_RECORDED"}.</p>
      {(data.runtime_incidents ?? []).map((r: Row, i: number) => <p role="alert" key={i}>Runtime incident: {r.reason}</p>)}
      <h3>Actual first blocking stage</h3>
      {Object.entries(data.causal_first_blockers).map(([name, count]) => <p key={name}>{name === "pending_execution" ? "Execution outcome pending or unrecorded" : name.startsWith("strategy:") ? conditionName(name.slice(9)) : humanize(name)}: {String(count)}</p>)}
      <h3>Independent failures · conditions may overlap</h3>
      {Object.entries(data.independent_failures).map(([name, value]) => { const v = value as Row; return <p key={name}>{humanize(name)}: {v.count} ({v.percent_of_evaluations}%)</p>; })}
      <p className="muted">{data.window.unannotated} unannotated decisions; {data.diagnostic_mismatches} diagnostic mismatches. Counts describe recorded events on this page. Missing telemetry remains unknown; an observed zero is not proof that an unrecorded stage was never reached. Pre-strategy skips are {data.last_scan_observation ? "recorded separately below" : "unavailable for earlier scans"}.</p>
      <Technical value={data.last_scan_observation} label="Latest scan and skipped candidates" />
      <h3>Decision evidence</h3>
      {data.decisions.map((d: Row) => <details key={d.decision_id}><summary>{d.symbol} · {date(d.created_at, true)} · {d.explanation?.reason ?? d.rejected_reason ?? "No recorded reason"}</summary>{d.execution_evidence_status ? <p>Historical trace assessment: {d.execution_evidence_status}</p> : <p>Recorded execution progression is available below.</p>}{(d.recorded_order_outcomes ?? []).map((o: Row) => <p key={o.order_id}>Independently recorded order: {o.status} · {o.reason ?? "No rejection recorded"} · {o.order_id}</p>)}<Technical value={d.explanation ?? { evidence: "Unavailable" }} label="All conditions and recorded values" /><Technical value={{ trace: d.execution_trace ?? { evidence: "NOT_RECORDED" }, stages: d.stage_states }} label="Durable execution trace" /></details>)}
      <div className="toolbar"><button disabled={!cursor} onClick={() => setCursor("")}>Latest evaluations</button><button disabled={!data.next_cursor} onClick={() => setCursor(data.next_cursor)}>Older evaluations</button></div>
    </>}
  </Panel>;
}
export function TradeGates() {
  const accounts = useResource("/api/shadow/summary", { poll: 15000 });
  const archived = useResource("/api/shadow/summary?archived=true", { poll: 60000 });
  const monitoring = useResource("/api/monitoring/summary", { poll: 15000 });
  const health = monitoring.data;
  return <div className="trade-gates">
    <Panel><h2>Scanner and portfolio safety</h2>
      <ResourceState resource={monitoring} label="Scanner health" />
      {health && <><p>Last completed scan: {date(health.last_scan?.completed_at, true)}. Market data {health.market_data?.state}; worker {health.service?.worker}; Redis {health.service?.redis}. Risk {health.risk_state}.</p><p>Live execution: {health.live_trading_enabled === false ? "disabled · verified configuration" : "configuration requires attention"}. Scanner availability, strategy eligibility and financial fills are separate measures.</p>{["BTC", "ETH", "SOL"].map(symbol => { const cache = health.market_data_quality?.caches?.find((c: Row) => c.key.startsWith(symbol + "-EUR:")); return <p key={symbol}>{symbol} completed-candle cache: {cache ? `${Math.round(cache.age_seconds)}s since refresh · ${cache.observations} observations` : "unavailable"}</p>; })}<p>Connected provider rate limits: {health.market_data_quality?.request_429 != null ? `${health.market_data_quality.request_429} recorded 429 responses in the retained counter window` : "no telemetry retained for this data source"}. See measurement windows below.</p><Technical value={health.market_data_quality} label="BTC / ETH / SOL freshness and Connected provider rate limits" /></>}
    </Panel>
    <ResourceState resource={accounts} label="Strategies" />
    {[...(accounts.data?.experiments ?? []), ...(archived.data?.experiments ?? [])].filter((a: Row, i: number, rows: Row[]) => rows.findIndex(r => r.experiment_id === a.experiment_id) === i).map((a: Row) => <AccountGates key={a.experiment_id} account={a} />)}
  </div>;
}
