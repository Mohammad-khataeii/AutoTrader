import React, { useState } from "react";
import { Row, useResource } from "./api";
import { date, humanize, money, number, percent, price, strategyName } from "./model";
import { Badge, CompactTable, Empty, Panel, ResourceState, Technical } from "./ui";

const label = (value: unknown) => humanize(String(value ?? "Unknown").toLowerCase());

export function OpportunityIntelligence() {
  const result = useResource("/api/intelligence", { poll: 15000 });
  const [selected, setSelected] = useState<Row>();
  const data = result.data;
  const rows = data?.rows ?? [];
  const summary = data?.unscanned_or_excluded ?? [];
  return <div className="page-stack raoe-intelligence">
    <Panel><p className="eyebrow">V4.9 · Adaptive Opportunity Intelligence</p><h2>Opportunity Radar</h2>
      <p>Recovery, controlled pullback and confirmed breakout retest in the primary portfolio; bounded continuation is separate shadow research. Each setup must offer a defensible plan after costs. Estimated edge remains unknown.</p>
      <ResourceState resource={result} label="Opportunity intelligence" />
      <p className="small muted">{label(data?.status)} · observed {date(data?.observed_at, true)} · {data?.discovery?.supported_eur ?? "Unknown"} supported EUR markets. Public Revolut X EEA observations; mid-price candles are not executable trades.</p>
      <CompactTable label="RAOE opportunity radar" rows={rows} empty={<Empty title="Waiting for completed observations">No setup is inferred from missing data.</Empty>} columns={[
        { label: "Market / playbook", render: r => <button className="table-link" onClick={() => setSelected(r)}>{r.symbol}<span className="small muted">{strategyName(r.strategy_id)}</span></button> },
        { label: "Price / recent movement", render: r => <>{price(r.market_price)}<div className="small muted">30m completed {percent(r.completed_return_30m)}</div></> },
        { label: "Liquidity / spread", render: r => <>{money(r.quote_volume_24h)}<div className="small muted">24h turnover · {number(r.spread_bps)?.toFixed(2) ?? "Unknown"} bps</div></> },
        { label: "Relative strength", render: r => <>{percent(r.relative_return_30m)}<div className="small muted">30m versus BTC/ETH</div></> },
        { label: "Regime", render: r => <>{(r.raoe_regime?.labels ?? []).map(label).join(" · ")}<div className="small muted">BTC/ETH {label(r.raoe_regime?.benchmark)}</div></> },
        { label: "Setup", render: r => <Badge tone={r.status === "READY" ? "positive" : r.status === "STALE" ? "warning" : "neutral"}>{label(r.status)}</Badge> },
        { label: "Entry / stop", render: r => <>{price(r.entry_plan?.entry)}<div className="small muted">Stop {price(r.entry_plan?.stop)}</div></> },
        { label: "Net risk / cost", render: r => <>{money(r.economics?.measurements?.expected_net_stop_loss_eur)}<div className="small muted">Cost {money(r.economics?.measurements?.estimated_total_round_trip_cost_eur)}</div></> },
        { label: "Net reward / risk", render: r => number(r.economics?.measurements?.net_reward_risk)?.toFixed(2) ?? "Not reached" },
      ]} />
    </Panel>
    <Panel><h2>Runtime diagnostics</h2><p>Benchmark labels require aligned completed bars. Four-hour context requires at least 21 genuine completed bars; unavailable history remains unknown.</p>
      <Technical value={{ benchmark: data?.benchmark_sync, acquisitionAndHeartbeats: data?.runtime_diagnostics }} label="Synchronization, scanner, protection and rate-limit observations" />
    </Panel>
    {selected && <Panel><div className="section-heading"><h2>{selected.symbol} · Trade Plan Inspector</h2><button onClick={() => setSelected(undefined)}>Close evidence</button></div>
      <p>{(selected.reasons ?? []).map(label).join(" · ") || "Qualified paper hypothesis; long-term expectancy remains unknown."}</p>
      <p>Entry alternatives use the same structural invalidation. A patient price requires a later executable quote; touching a candle low does not prove a fill.</p>
      <div className="plan-inspector" aria-label="Causal trade plan">
        <div><strong>Observed ask</strong><p>{price(selected.entry_plan?.entry)}</p></div>
        <div><strong>Structural stop</strong><p>{price(selected.entry_plan?.stop)}</p></div>
        <div><strong>First bid scenario</strong><p>{price(selected.entry_plan?.targets?.[0])}</p></div>
        <div><strong>Next meaningful structure</strong><p>{price(selected.entry_plan?.next_overhead)}</p></div>
        <div><strong>Modeled break-even bid</strong><p>{price(selected.economics?.measurements?.breakeven_bid)}</p></div>
      </div>
      {number(selected.entry_plan?.targets?.[0]) != null && number(selected.economics?.measurements?.breakeven_bid) != null && Number(selected.entry_plan.targets[0]) < Number(selected.economics.measurements.breakeven_bid) && <p role="status">First target is below modeled executable break-even. This plan does not cover costs.</p>}
      <p className="small muted">Targets are bounded structural scenarios, not forecasts. Five-minute noise is shown separately from meaningful unbroken resistance. No alternate plan edits the original decision.</p>
      <Technical value={selected.entry_plan} label="Entry alternatives and target structure" />
      <ol className="qualification-path">{(selected.pipeline ?? []).map((s: Row) => <li key={s.stage}><div><strong>{label(s.stage)}</strong><p>{label(s.state ?? (!s.reached ? "NOT_REACHED" : s.passed === true ? "PASSED" : s.passed === false ? "FAILED" : "UNKNOWN"))}</p></div></li>)}</ol>
      <Technical value={selected.raoe_regime} label="Independent timeframe and benchmark evidence" />
    </Panel>}
    <Panel><h2>Universe coverage</h2><p>Unscanned markets have summary evidence only. Stablecoins are excluded from directional playbooks. One rotating detail slot gives new markets a chance to replace weaker candidates.</p>
      <CompactTable label="Discovery coverage" rows={summary} columns={[
        { label: "Market", render: r => r.symbol }, { label: "Mid price", render: r => price(r.price) },
        { label: "Short-window evidence", render: r => <>{percent(r.completed_return_30m ?? r.summary_return_30m)}<div className="small muted">{label(r.short_window_source)}</div></> },
        { label: "Spread", render: r => `${number(r.spread_bps)?.toFixed(2) ?? "Unknown"} bps` },
        { label: "24h turnover", render: r => money(r.quote_volume_24h) },
        { label: "Status", render: r => <><Badge>{label(r.status)}</Badge><div className="small muted">{label(r.reason ?? r.selection_reason)}</div></> },
      ]} />
    </Panel>
    <MissedOpportunities />
  </div>;
}

function MissedOpportunities() {
  const [cursor, setCursor] = useState(0);
  const result = useResource(`/api/intelligence?limit=12&cursor=${cursor}`, { poll: cursor ? undefined : 30000 });
  const [selected, setSelected] = useState<Row>();
  return <Panel><h2>Missed Opportunities</h2><p>Original signals and separate fixed-horizon price-path reviews. The episode table groups overlapping proposals on the same asset across strategies; a page of repeated signals is not a sample of independent wins. A later rise alone does not establish a missed executable profit.</p>
    <CompactTable label="Prospective rejected candidate review" rows={result.data?.missed ?? []} columns={[
      { label: "Observation", render: r => <button className="table-link" onClick={() => setSelected(r)}>{r.symbol}<span className="small muted">{date(r.observed_at,true)}</span></button> },
      { label: "Playbook", render: r => strategyName(r.strategy_id) },
      { label: "Decision", render: r => label(r.rejection ?? (r.accepted ? "Qualified paper decision" : "Not admitted")) },
      { label: "Price-path review", render: r => label(r.outcome?.classification) },
    ]} />
    <CompactTable label="Overlapping market episodes" rows={result.data?.episodes ?? []} columns={[
      { label: "Market / first observation", render: r => <>{r.symbol}<div className="small muted">{date(r.first_observed_at,true)}</div></> },
      { label: "Repeated signals", render: r => r.signal_count },
      { label: "First actionable", render: r => date(r.first_actionable_observation,true) },
      { label: "Position conflicts", render: r => r.position_conflicts },
      { label: "Evidence", render: () => "Execution unproven; no independent win implied" },
    ]} />
    <p className="small muted">Episode window: latest {result.data?.episode_scope?.hours ?? 48} hours; {result.data?.episode_scope?.signals ?? 0} signals. {result.data?.episode_scope?.possibly_truncated ? "Window truncated; counts are incomplete." : "Boundary episodes may overlap older history."}</p>
    <div className="toolbar"><button disabled={!cursor} onClick={() => setCursor(0)}>Latest reviews</button><button disabled={result.data?.next_cursor == null} onClick={() => setCursor(result.data.next_cursor)}>Earlier reviews</button></div>
    {selected && <><button onClick={() => setSelected(undefined)}>Close review</button><Technical value={selected} label="Immutable candidate and separate future assessment" /></>}
  </Panel>;
}

export function RAOECompetition() {
  const result = useResource("/api/intelligence/competition", { poll: 30000 });
  return <Panel className="raoe-intelligence"><p className="eyebrow">Separate evidence · shared primary risk</p><h2>Strategy Competition</h2>
    <ResourceState resource={result} label="Strategy competition" />
    <p>{result.data?.allocation ?? "One primary portfolio and independent paper experiments."} No automatic promotion or recent-winner allocation. Zero trades provide no evidence of profitability.</p>
    <CompactTable label="Prospective strategy competition" rows={result.data?.experiments ?? []} columns={[
      { label: "Strategy / version", render: r => <>{strategyName(r.strategy_id)}<div className="small muted">{r.version}</div></> },
      { label: "Equity / orders / fills", render: r => <>{money(r.portfolio?.equity)}<div className="small muted">{r.orders} orders · {r.fills} recent fills</div></> },
      { label: "Exit / forward age", render: r => <>{r.exit_policy?.version ?? "Legacy unbound"}<div className="small muted">{r.exit_policy?.holding_seconds ? `${r.exit_policy.holding_seconds / 3600}h policy` : "See original orders"} · {Math.floor((r.forward_evidence_seconds ?? 0) / 3600)}h elapsed since creation{r.archived_at ? " · Archived" : ""}</div></> },
      { label: "Rejections", render: r => Object.entries(r.rejection_reasons ?? {}).map(([key, value]) => `${label(key)}: ${value}`).join(" · ") || "None recorded" },
      { label: "Realized / unrealized", render: r => <>{money(r.portfolio?.realized_pnl)}<div className="small muted">{money(r.portfolio?.unrealized_pnl)}</div></> },
      { label: "Closed / win rate", render: r => <>{r.performance?.closed_trades}<div className="small muted">{percent(r.performance?.win_rate)}</div></> },
      { label: "Expectancy / profit factor", render: r => <>{money(r.performance?.expectancy)}<div className="small muted">{r.performance?.profit_factor ?? "Unknown"}</div></> },
      { label: "Drawdown / fees", render: r => <>{percent(r.performance?.max_drawdown)}<div className="small muted">{money(r.performance?.fees)}</div></> },
      { label: "Wins / losses", render: r => `${r.performance?.win_count ?? "Unknown"} / ${r.performance?.loss_count ?? "Unknown"}` },
      { label: "Modeled slippage / exposure", render: r => <>{money(r.performance?.modeled_slippage_and_impact_eur)}<div className="small muted">Exposure {money(r.performance?.exposure_eur)}</div></> },
      { label: "Median holding", render: r => r.performance?.median_holding_seconds == null ? "Unknown" : `${Math.round(r.performance.median_holding_seconds / 60)} min` },
      { label: "Evidence", render: r => <><Badge tone="warning">{label(r.evidence_category)}</Badge><div className="small muted">{label(r.confidence)}</div></> },
    ]} />
    <Technical value={result.data?.primary_strategies ?? []} label="Primary shared-account attribution" />
    <Technical value={result.data?.historical ?? { status: "NOT_PUBLISHED" }} label="Historical proxy comparison, costs and limitations" />
  </Panel>;
}
