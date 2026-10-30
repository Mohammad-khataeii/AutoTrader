import React from "react";
import { useResource, type Row } from "./api";
import { date, money, percent } from "./model";
import { Badge, CompactTable, Panel, ResourceState } from "./ui";

export function LearningPerformance({ primary }: { primary?: Row }) {
  const resource = useResource("/api/personal-paper/learning", { poll: 30000 });
  const d = resource.data;
  const dataset = d?.dataset;
  const training = d?.latest_training;
  const funnel = d?.funnel;
  const market = d?.market_task;
  const latest = funnel?.latest?.find((r: Row) => r.market_state) ?? funnel?.latest?.[0];
  const state = latest?.market_state;
  const blockers = Object.entries(latest?.primary_admission?.gates ?? {}).filter(([, passed]) => passed === false).map(([gate]) => gate);
  const windows = Object.entries(d?.provider_measurements ?? {}).filter(([key]) => key.startsWith("market_window:")).map(([, value]) => value as Row);
  return <div className="page-stack" aria-label="Learning and Performance">
    <Panel><div className="section-heading"><div><p className="eyebrow">Learning &amp; Performance</p><h2>Evidence before model promotion</h2></div><Badge>Shadow research only</Badge></div>
      <ResourceState resource={resource} label="Learning pipeline" />
      <p>Backend {d?.backend_version ?? "unavailable"} · Execution profile {d?.approved_execution_profile ?? "unavailable"}</p>
      <p>Approved model: {d?.approved_model?.replaceAll("_", " ") ?? "Unavailable"}. Primary execution changes require a separately approved frozen release.</p>
      <div className="kpi-grid">
        <div className="kpi"><span>Training status</span><strong>{d?.status?.replaceAll("_", " ") ?? "Loading"}</strong><small>Latest run {date(training?.trained_at, true)}</small></div>
        <div className="kpi"><span>Independent episodes</span><strong>{dataset?.independent_episodes ?? 0}</strong><small>{dataset?.required_episodes ?? "—"} required across {dataset?.required_days ?? "—"} days</small></div>
        <div className="kpi"><span>Dataset</span><strong>{dataset?.counts?.LABELED ?? 0} labeled</strong><small>{dataset?.counts?.PENDING ?? 0} pending complete priced plans · {dataset?.scope ?? "Legacy collector coverage"}</small></div>
        <div className="kpi"><span>Shadow challenger</span><strong>{d?.active_challenger ? d.active_challenger.slice(0, 12) : "No qualified model"}</strong><small>Drift {percent(d?.feature_drift)}</small></div>
      </div>
      <p className="small muted">Coverage {date(dataset?.from, true)} to {date(dataset?.until, true)} · Collector {date(d?.observed_at, true)}. Overlapping signals across crypto assets share an episode. Candle paths use explicit cost assumptions and cannot prove future fills.</p>
      {(d?.warnings ?? []).map((w: string) => <p key={w} className="notice warning" role="status">{w}</p>)}
      {d?.collector_stale && <p className="notice warning">Collection is stale. Research estimates must not be treated as current.</p>}
      {d?.quarantined_challenger && <p className="notice warning" role="status">Shadow model quarantined: {d.quarantined_challenger.reason.replaceAll("_", " ")}. Primary paper execution continues with its approved baseline.</p>}
      {(training?.reasons ?? []).map((reason: string) => <p key={reason} className="notice warning">Qualification check: {reason.replace(/_/g, " ")}</p>)}
    </Panel>
    <Panel><div className="section-heading"><div><p className="eyebrow">Current decision context</p><h2>{state?.state?.replaceAll("_", " ") ?? "Waiting for a current market observation"}</h2></div><Badge>Research interpretation</Badge></div>
      <p>{state?.reason ?? "The collector is reading immutable decision snapshots."} · Observed {date(latest?.observed_at, true)}</p>
      <p>Asset structure: 5m {state?.timeframes?.["5"]?.trend ?? "unknown"} · 15m {state?.timeframes?.["15"]?.trend ?? "unknown"} · 1h {state?.timeframes?.["60"]?.trend ?? "unknown"} · 4h {state?.timeframes?.["240"]?.trend ?? "unknown"}.</p>
      <CompactTable label="Benchmark timeframe context" empty={<p className="small muted">No completed benchmark snapshot has reached the collector yet.</p>} rows={Object.entries(state?.benchmarks ?? {}).map(([symbol, value]) => ({ symbol, ...(value as Row) }))} columns={[
        { label: "Benchmark", render: (r: Row) => r.symbol },
        { label: "5m / 15m", render: (r: Row) => `${r.timeframes?.["5"]?.trend ?? "unknown"} / ${r.timeframes?.["15"]?.trend ?? "unknown"}` },
        { label: "Hourly / 4h", render: (r: Row) => `${r.timeframes?.["60"]?.trend ?? "unknown"} / ${r.timeframes?.["240"]?.trend ?? "unknown"}` },
        { label: "30m midpoint move", render: (r: Row) => percent(r.return_30m) },
      ]}/>
      <p>Latest recorded primary stage: {latest?.stage?.replaceAll("_", " ") ?? "Waiting"}. Blocking admission gates: {blockers.length ? blockers.map(g => g.replace(/_/g, " ")).join(", ") : "No failed admission gate in this snapshot; execution still requires all risk and pricing checks"}.</p>
      <p className="small muted">The approved primary macro policy remains active. A research recovery classification does not authorize a trade. This snapshot is one candidate, not a claim about every market.</p>
    </Panel>
    <Panel><h2>Observation funnel</h2><div className="kpi-grid">
      <div className="kpi"><span>Unique recorded signals</span><strong>{funnel?.unique_signals ?? 0}</strong><small>Each immutable signal counted once</small></div>
      <div className="kpi"><span>Unpriced technical candidates</span><strong>{funnel?.stages?.TECHNICAL_VALID_UNPRICED ?? 0}</strong><small>{funnel?.stages?.TECHNICAL_REJECTED ?? 0} ordinary technical rejections</small></div>
      <div className="kpi"><span>Complete priced plans</span><strong>{funnel?.priced_plans ?? 0}</strong><small>{funnel?.stages?.ECONOMICS_REJECTED ?? 0} economic rejections</small></div>
      <div className="kpi"><span>True data-quality failures</span><strong>{funnel?.dispositions?.DATA_QUALITY_FAILED ?? 0}</strong><small>{funnel?.dispositions?.COVERAGE_EXCLUDED ?? 0} missing or legacy coverage · {funnel?.dispositions?.SOURCE_EXCLUDED ?? 0} source exclusions</small></div>
    </div><p>Market-path task: {market?.counts?.LABELED ?? 0} matured · {market?.counts?.PENDING ?? 0} pending · {market?.counts?.WINDOW_UNAVAILABLE ?? 0} unavailable windows · {market?.independent_episodes ?? 0} independent episodes.</p>
      <p>Market model: {market?.latest_training?.status?.replaceAll("_", " ") ?? "Collecting"}. Shadow challenger: {market?.active_challenger?.slice(0, 12) ?? "None qualified"}. Forward episodes: {market?.forward_episodes ?? 0} · Brier {market?.forward_brier?.toFixed(3) ?? "Insufficient evidence"}.</p>
      {market?.quarantined_challenger && <p className="notice warning">Market challenger quarantined: {market.quarantined_challenger.reason.replaceAll("_", " ")}</p>}
      <p className="small muted">Midpoint-path labels measure observed market movement and adverse excursions. They have no assumed entry, execution costs or achievable profit. Complete priced plans and actual managed-position outcomes train separate tasks. Retained legacy records: {Object.values(d?.legacy_dataset?.counts ?? {}).reduce((a: number, b) => a + Number(b), 0)}; original exclusions remain in research history.</p>
      <CompactTable label="Observation coverage exclusions" empty={<p className="small muted">No stage-aware coverage exclusions or data-quality failures recorded.</p>} rows={Object.entries(funnel?.coverage_reasons ?? {}).map(([reason, count]) => ({ reason, count }))} columns={[
        { label: "Coverage / quality reason", render: (r: Row) => r.reason }, { label: "Signals", render: (r: Row) => r.count },
      ]}/>
    </Panel>
    <Panel><h2>Provider and collector health</h2><CompactTable label="Provider measurement windows" empty={<p className="small muted">No measured provider window published yet.</p>} rows={windows} columns={[
      { label: "Measured from / until", render: (r: Row) => `${date(r.started_at, true)} / ${date(r.observed_until, true)}` },
      { label: "Successful requests", render: (r: Row) => r.request_success ?? 0 },
      { label: "HTTP 429", render: (r: Row) => r.request_429 ?? 0 },
      { label: "Coalesced reads / ticker hits", render: (r: Row) => `${r.coalesced_read ?? 0} / ${r.ticker_cache_hit ?? 0}` },
    ]}/><p className="small muted">Bounded 15-minute windows can include partial periods or an earlier release. Fresh observation and historical repair use separate restart-safe cursors. Protective monitoring runs independently.</p></Panel>
    <Panel><h2>Actual primary paper results</h2><div className="balance-summary">
      <div><span>Fees paid</span><strong>{money(primary?.performance?.fees_eur)}</strong></div>
      <div><span>Slippage / impact</span><strong>{money(primary?.performance?.modeled_slippage_and_impact_eur)}</strong></div>
      <div><span>Maximum drawdown</span><strong>{percent(primary?.performance?.max_drawdown)}</strong></div>
      <div><span>Profit factor</span><strong>{primary?.performance?.profit_factor ?? "Insufficient sample"}</strong></div>
      <div><span>Net expectancy</span><strong>{money(primary?.performance?.expectancy)}</strong></div>
    </div><CompactTable label="Reasons for primary losses" empty={<p className="small muted">No closed primary loss is available in this response.</p>} rows={(primary?.trade_reports ?? []).filter((r: Row) => Number(r.net_pnl_eur) < 0)} columns={[
      { label: "Market / entry profile", render: (r: Row) => <>{r.symbol}<div className="small muted">{r.execution_profile}</div></> },
      { label: "Net result", render: (r: Row) => money(r.net_pnl_eur) },
      { label: "Recorded cause", render: (r: Row) => r.explanation },
    ]}/><p className="small muted">Actual primary paper ledger. Execution impact is already in fill prices. Old entry profiles retain their own attribution.</p></Panel>
    <Panel><h2>Chronological model comparison</h2><CompactTable label="Learning validation" empty={<p className="small muted">No qualified chronological model comparison is available yet.</p>} rows={training?.comparisons ?? []} columns={[
      { label: "Evidence", render: (r: Row) => r.partition.replaceAll("_", " ") },
      { label: "Episodes / selected", render: (r: Row) => `${r.challenger.episodes} / ${r.challenger.selected}` },
      { label: "Challenger net R", render: (r: Row) => r.challenger.net_expectancy_r?.toFixed(3) ?? "Insufficient" },
      { label: "Baseline net R", render: (r: Row) => r.approved_baseline.net_expectancy_r?.toFixed(3) ?? "Insufficient" },
      { label: "2× cost net R", render: (r: Row) => r.cost_stress_2x.net_expectancy_r?.toFixed(3) ?? "Insufficient" },
      { label: "Calibration / Brier", render: (r: Row) => `${r.challenger.calibration_error?.toFixed(3)} / ${r.challenger.brier?.toFixed(3)}` },
    ]}/><p className="small muted">Historical modeled execution · equal unit risk, purged chronological partitions, holdouts sealed after first use. Calibration describes a defined modeled outcome, not guaranteed trading confidence.</p>
      <p>Actual position-outcome model: {training?.actual_outcomes_model?.status?.replaceAll("_", " ") ?? "Collecting"} · {training?.actual_outcomes_model?.independent_episodes ?? 0} independent episodes. Actual outcomes and modeled path targets train separate tasks.</p>
      <p>Forward shadow: {d?.forward_evaluation?.selected_independent_episodes ?? 0} selected independent episodes · modeled expectancy {d?.forward_evaluation?.modeled_net_expectancy_r?.toFixed(3) ?? "insufficient evidence"} R. Predictions are prospective; their candle-based outcome estimates remain hypothetical execution.</p>
    </Panel>
    <Panel><h2>Strategy and market context</h2><CompactTable label="Learning strategy and regime" empty={<p className="small muted">Waiting for matured priced-plan paths with recorded market context.</p>} rows={d?.strategy_regime_performance ?? []} columns={[
      { label: "Strategy / regime", render: (r: Row) => r.strategy_regime },
      { label: "Signals", render: (r: Row) => r.signals },
      { label: "Independent episodes", render: (r: Row) => r.independent_episodes },
      { label: "Modeled expectancy R", render: (r: Row) => r.modeled_net_expectancy_r?.toFixed(3) },
    ]}/><p className="small muted">Historical conditional path research. Primary portfolio fees, slippage, drawdown, profit factor and expectancy remain in the portfolio overview and linked trade reports.</p></Panel>
    <Panel><h2>Rejected candidates and retained coverage</h2><CompactTable label="Learning rejections" empty={<p className="small muted">No ordinary rejection reasons have been collected in the current funnel.</p>} rows={Object.entries(d?.rejection_reasons ?? {}).map(([reason, count]) => ({ reason, count }))} columns={[
      { label: "Reason recorded then", render: (r: Row) => r.reason.replaceAll("_", " ") }, { label: "Signals", render: (r: Row) => r.count },
    ]}/><CompactTable label="Learning coverage failures" empty={<p className="small muted">No retained legacy coverage exclusions are available.</p>} rows={Object.entries(d?.legacy_dataset?.coverage_failures ?? dataset?.coverage_failures ?? {}).map(([reason, count]) => ({ reason, count }))} columns={[
      { label: "Legacy collector exclusion", render: (r: Row) => r.reason }, { label: "Retained records", render: (r: Row) => r.count },
    ]}/><p className="small muted">Ordinary rejection reasons use the latest 10,000 stage-aware signals. Legacy collector exclusions remain for audit; their unpriced rejections do not count as new source corruption. A later rising price does not prove an executable missed trade.</p></Panel>
    <Panel><h2>Exit feedback</h2><p>{d?.exit_feedback?.modeled_stop_episodes ?? 0} modeled stop episodes · {d?.exit_feedback?.ambiguous_barrier_episodes ?? 0} ambiguous stop/target candles · {d?.exit_feedback?.short_horizon_positive_long_horizon_negative ?? 0} short-positive / long-negative paths.</p><p>{d?.exit_feedback?.policy ?? "Collecting matched historical conditions"}</p><p className="small muted">{d?.exit_feedback?.limitations}</p><p className="small muted">Actual ledger outcomes collected: {d?.realized_positions_collected ?? 0}. Research does not rewrite existing stops, targets or account history.</p></Panel>
  </div>;
}
