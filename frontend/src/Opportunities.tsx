import React, { useState } from "react";
import { ArrowUpRight, Compass, ShieldCheck } from "lucide-react";
import { type Row, useResource } from "./api";
import { date, humanize, money, number, percent, strategyName } from "./model";
import { Badge, CompactTable, Empty, Panel, Pnl, ResourceState, Technical } from "./ui";
import { Experiments } from "./Experiments";

function qualification(row: Row, stale: boolean) {
  return stale ? "Watch only · refresh needed" : row.economic_eligible ? "Feasible · unvalidated" : row.technical_eligible ? "Cost constrained" : "Watching for a setup";
}
export function OpportunityPreview() {
  const result = useResource("/api/opportunities?limit=1", { ttl: 60000 });
  const row = result.data?.rows?.[0];
  return <Panel className="opportunity-preview"><div className="section-heading"><h2>Latest opportunity insight</h2><Compass size={18} /></div>
    <ResourceState resource={result} label="Opportunity observations" />
    {row ? <><p><strong>{row.symbol}</strong> · {strategyName(row.strategy_id)}</p><p>{row.explanation}</p><Badge tone={row.economic_eligible && !result.data.stale ? "positive" : "neutral"}>{qualification(row, result.data.stale)}</Badge><p className="small muted">Observed {date(row.as_of, true)}. A feasible setup is not evidence of predictive value.</p></> : <p className="muted">No successor observation has been recorded yet. Missing evidence is shown as unknown.</p>}
  </Panel>;
}

export function Opportunities() {
  const [cursor, setCursor] = useState(0);
  const [selected, setSelected] = useState<Row>();
  const result = useResource(`/api/opportunities?limit=12&cursor=${cursor}`, { poll: cursor ? undefined : 15000 });
  const data = result.data;
  const rows: Row[] = data?.rows ?? [];
  return <div className="page-stack opportunities-view">
    <Panel><div className="section-heading"><div><p className="eyebrow">Observe · qualify · understand</p><h2>A clearer view of opportunity</h2></div><Compass size={22} /></div>
      <p>Technical conditions, realistic costs and portfolio safeguards are evaluated separately. These successor models remain experimental; no orders or allocations are created from this view.</p>
      <ResourceState resource={result} label="Opportunity observations" />
      {data?.runtime_incident && <p className="notice warning" role="alert">Observation incident: {data.runtime_incident}</p>}
      <div className="insight-metrics"><div><span>Technical setups</span><strong>{data?.technical_candidates ?? "Unknown"}</strong></div><div><span>Economic feasibility</span><strong>{data?.economically_viable_candidates ?? "Unknown"}</strong></div><div><span>Validated predictive edge</span><strong>Not established</strong></div></div>
      <p className="small muted">Last observation {date(data?.updated_at, true)} · {data?.stale ? "Price evidence is stale; watching only." : "Observed quotes are indicative. The gateway always checks a fresh book."}</p>
    </Panel>
    <Panel><div className="section-heading"><h2>Markets and qualification</h2><Badge>Simulated Mode</Badge></div>
      <CompactTable label="Opportunity qualification" rows={rows} empty={<Empty title="Waiting for observations"><p>The next completed-data cycle will populate this view. No qualifying setup is inferred from missing data.</p></Empty>} columns={[
        { label: "Market", render: r => <button className="table-link" onClick={() => setSelected(r)}><strong>{r.symbol}</strong><span className="small muted">{strategyName(r.strategy_id)}</span></button> },
        { label: "Market conditions", render: r => <><span>{humanize(r.regime_assessment?.trend)}</span><div className="small muted">{(r.regime_assessment?.structure ?? []).map(humanize).join(" · ")}</div></> },
        { label: "Gross target", render: r => percent(r.economics?.measurements?.gross_target_return) },
        { label: "Modeled costs", render: r => money(r.economics?.measurements?.estimated_total_round_trip_cost_eur) },
        { label: "Net reward / risk", render: r => number(r.economics?.measurements?.net_reward_risk)?.toFixed(2) ?? "Not assessed" },
        { label: "Qualification", render: r => <Badge tone={r.economic_eligible && !data?.stale ? "positive" : r.technical_eligible ? "warning" : "neutral"}>{qualification(r, data?.stale)}</Badge> },
      ]} />
      <div className="toolbar"><button disabled={!cursor} onClick={() => setCursor(0)}>Latest observations</button><button disabled={data?.next_cursor == null} onClick={() => setCursor(data.next_cursor)}>More markets</button></div>
    </Panel>
    {selected && <Panel><div className="section-heading"><h2>{selected.symbol} · {strategyName(selected.strategy_id)}</h2><button onClick={() => setSelected(undefined)}>Close evidence</button></div>
      <p>{selected.explanation}</p><p className="small muted">Score {number(selected.score)?.toFixed(2) ?? "Unknown"} ranks observations. It is not a probability of profit.</p>
      <div className="opportunity-economics"><div><span>Conditional first-target result</span><strong>{money(selected.economics?.measurements?.conditional_target_net_eur?.[0])}</strong></div><div><span>Modeled loss at stop</span><strong>{money(selected.economics?.measurements?.expected_net_stop_loss_eur)}</strong></div><div><span>Break-even bid</span><strong>{money(selected.economics?.measurements?.breakeven_bid)}</strong></div></div>
      <p className="small muted">The spread is counted once through bid/ask prices. Future liquidity, gaps and target-hit probabilities remain uncertain.</p>
      <ol className="qualification-path">{(selected.pipeline ?? []).map((stage: Row) => <li key={stage.stage}><ShieldCheck size={16} /><div><strong>{humanize(stage.stage)}</strong><p>{!stage.reached ? "Not reached" : stage.passed === true ? "Passed" : stage.passed === false ? "Not selected" : "Unverified"} · {humanize(stage.reason)}</p></div></li>)}</ol>
      <Technical value={selected} label="Conditions and cost measurements" />
    </Panel>}
    <Panel><h2>Discovery and data quality</h2><p>A lightweight public summary screen precedes a bounded number of detailed history and depth checks. Protective monitoring retains priority.</p>
      <p>{data?.discovery?.counts?.supported_eur ?? "Unknown"} supported EUR markets · {data?.discovery?.counts?.screened ?? "Unknown"} passed the summary screen · {data?.discovery?.extra_detail_budget ?? "Unknown"} extra detail checks per completed-candle cycle.</p>
      {(data?.data_failures ?? []).map((r: Row, i: number) => <p className="small" key={i}>{r.symbol ?? "Discovery"}: {humanize(r.reason ?? r.reasons?.join(", "))}</p>)}
      <Technical value={data?.discovery ?? { status: "NOT_RECORDED" }} label="Discovery measurements" />
    </Panel>
  </div>;
}

export function StrategyComparison() {
  const result = useResource("/api/strategies/comparison", { ttl: 60000 });
  const report = result.data?.research;
  const successors = ["A3_COST_AWARE_CONTINUATION", "B3_STATEFUL_BREAKOUT", "E3_ADAPTIVE_RELATIVE_STRENGTH"];
  const old = ["A2_CONFIRMED_PULLBACK", "B2_CONFIRMED_COMPRESSION", "E2_ABSOLUTE_RELATIVE_STRENGTH"];
  const rows = successors.flatMap((id, i) => [
    { strategy_id: old[i], generation: "Original baseline", result: report?.baseline?.[old[i]], status: "Historical proxy" },
    { strategy_id: id, generation: "Successor hypothesis", result: report?.successors?.[id]?.test, status: report?.successors?.[id]?.status ?? "Experimental", detail: report?.successors?.[id] },
  ]);
  return <div className="page-stack"><Panel><div className="section-heading"><h2>Compare hypotheses, not promises</h2><ArrowUpRight size={20} /></div><p>A2/A3, B2/B3 and E2/E3 use matched chronological observations and explicit costs. Wider targets or more entries are useful only if realized results improve reliably.</p><ResourceState resource={result} label="Strategy comparison" />
    {!report && <p className="notice warning">No completed V4.6 comparison is available in this environment. Performance and opportunity counts remain unverified.</p>}
    <CompactTable label="Strategy research comparison" rows={rows} columns={[
      { label: "Strategy", render: r => <><strong>{strategyName(r.strategy_id)}</strong><div className="small muted">{r.generation}</div></> },
      { label: "Technical / feasible", render: r => `${r.result?.opportunity_counts?.technical ?? "Unknown"} / ${r.result?.opportunity_counts?.economically_viable ?? "Unknown"}` },
      { label: "Closed positions", render: r => r.result?.trades ?? "Unknown" },
      { label: "Net result", render: r => <Pnl value={r.result?.net_profit} /> },
      { label: "Drawdown", render: r => percent(r.result?.max_drawdown) },
      { label: "Higher-cost result", render: r => money(r.detail?.cost_stress?.net_profit) },
      { label: "Evidence", render: r => <Badge tone="warning">{humanize(r.status)}</Badge> },
    ]} />
    <p className="small muted">Simulation uses historical proxy candles and assumed spread/depth. Reused samples, missing regimes and unavailable untouched holdout prevent a validated investment conclusion.</p></Panel>
    {successors.map(id => <Panel key={id}><h2>{strategyName(id)}</h2><p>{result.data?.successors?.find((s: Row) => s.strategy_id === id)?.hypothesis}</p><Technical value={report?.successors?.[id] ?? { status: "NOT_RECORDED" }} label="Validation, timing and universe comparisons" /></Panel>)}
  </div>;
}

export function StrategiesWorkspace() {
  const [view, setView] = useState("Accounts");
  return <div className="page-stack"><div className="segmented" role="tablist" aria-label="Strategy workspace">{["Accounts", "Research comparison"].map(name => <button key={name} role="tab" aria-selected={view === name} onClick={() => setView(name)}>{name}</button>)}</div>{view === "Accounts" ? <Experiments /> : <StrategyComparison />}</div>;
}
