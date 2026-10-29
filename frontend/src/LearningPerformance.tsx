import React from "react";
import { useResource, type Row } from "./api";
import { date, money, percent } from "./model";
import { Badge, CompactTable, Panel, ResourceState } from "./ui";

export function LearningPerformance({ primary }: { primary?: Row }) {
  const resource = useResource("/api/personal-paper/learning", { poll: 30000 });
  const d = resource.data;
  const dataset = d?.dataset;
  const training = d?.latest_training;
  return <div className="page-stack" aria-label="Learning and Performance">
    <Panel><div className="section-heading"><div><p className="eyebrow">Learning &amp; Performance</p><h2>Evidence before model promotion</h2></div><Badge>Shadow research only</Badge></div>
      <ResourceState resource={resource} label="Learning pipeline" />
      <p>Backend {d?.backend_version ?? "unavailable"} · Execution profile {d?.approved_execution_profile ?? "unavailable"}</p>
      <p>Approved model: {d?.approved_model?.replaceAll("_", " ") ?? "Unavailable"}. Primary execution changes require a separately approved frozen release.</p>
      <div className="kpi-grid">
        <div className="kpi"><span>Training status</span><strong>{d?.status?.replaceAll("_", " ") ?? "Loading"}</strong><small>Latest run {date(training?.trained_at, true)}</small></div>
        <div className="kpi"><span>Independent episodes</span><strong>{dataset?.independent_episodes ?? 0}</strong><small>{dataset?.required_episodes ?? "—"} required across {dataset?.required_days ?? "—"} days</small></div>
        <div className="kpi"><span>Dataset</span><strong>{dataset?.counts?.LABELED ?? 0} labeled</strong><small>{dataset?.counts?.PENDING ?? 0} pending · {dataset?.counts?.DATA_QUALITY_FAILED ?? 0} excluded</small></div>
        <div className="kpi"><span>Shadow challenger</span><strong>{d?.active_challenger ? d.active_challenger.slice(0, 12) : "No qualified model"}</strong><small>Drift {percent(d?.feature_drift)}</small></div>
      </div>
      <p className="small muted">Coverage {date(dataset?.from, true)} to {date(dataset?.until, true)} · Collector {date(d?.observed_at, true)}. Overlapping signals across crypto assets share an episode. Candle paths use explicit cost assumptions and cannot prove future fills.</p>
      {(d?.warnings ?? []).map((w: string) => <p key={w} className="notice warning" role="status">{w}</p>)}
      {d?.collector_stale && <p className="notice warning">Collection is stale. Research estimates must not be treated as current.</p>}
      {d?.quarantined_challenger && <p className="notice warning" role="status">Shadow model quarantined: {d.quarantined_challenger.reason.replaceAll("_", " ")}. Primary paper execution continues with its approved baseline.</p>}
      {(training?.reasons ?? []).map((reason: string) => <p key={reason} className="notice warning">Qualification check: {reason.replace(/_/g, " ")}</p>)}
    </Panel>
    <Panel><h2>Actual primary paper results</h2><div className="balance-summary">
      <div><span>Fees paid</span><strong>{money(primary?.performance?.fees_eur)}</strong></div>
      <div><span>Slippage / impact</span><strong>{money(primary?.performance?.modeled_slippage_and_impact_eur)}</strong></div>
      <div><span>Maximum drawdown</span><strong>{percent(primary?.performance?.max_drawdown)}</strong></div>
      <div><span>Profit factor</span><strong>{primary?.performance?.profit_factor ?? "Insufficient sample"}</strong></div>
      <div><span>Net expectancy</span><strong>{money(primary?.performance?.expectancy)}</strong></div>
    </div><CompactTable label="Reasons for primary losses" rows={(primary?.trade_reports ?? []).filter((r: Row) => Number(r.net_pnl_eur) < 0)} columns={[
      { label: "Market / entry profile", render: (r: Row) => <>{r.symbol}<div className="small muted">{r.execution_profile}</div></> },
      { label: "Net result", render: (r: Row) => money(r.net_pnl_eur) },
      { label: "Recorded cause", render: (r: Row) => r.explanation },
    ]}/><p className="small muted">Actual primary paper ledger. Execution impact is already in fill prices. Old entry profiles retain their own attribution.</p></Panel>
    <Panel><h2>Chronological model comparison</h2><CompactTable label="Learning validation" rows={training?.comparisons ?? []} columns={[
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
    <Panel><h2>Strategy and market context</h2><CompactTable label="Learning strategy and regime" rows={d?.strategy_regime_performance ?? []} columns={[
      { label: "Strategy / regime", render: (r: Row) => r.strategy_regime },
      { label: "Signals", render: (r: Row) => r.signals },
      { label: "Independent episodes", render: (r: Row) => r.independent_episodes },
      { label: "Modeled expectancy R", render: (r: Row) => r.modeled_net_expectancy_r?.toFixed(3) },
    ]}/><p className="small muted">Historical conditional path research. Primary portfolio fees, slippage, drawdown, profit factor and expectancy remain in the portfolio overview and linked trade reports.</p></Panel>
    <Panel><h2>Rejected candidates and data coverage</h2><CompactTable label="Learning rejections" rows={Object.entries(d?.rejection_reasons ?? {}).map(([reason, count]) => ({ reason, count }))} columns={[
      { label: "Reason recorded then", render: (r: Row) => r.reason.replaceAll("_", " ") }, { label: "Signals", render: (r: Row) => r.count },
    ]}/><CompactTable label="Learning coverage failures" rows={Object.entries(dataset?.coverage_failures ?? {}).map(([reason, count]) => ({ reason, count }))} columns={[
      { label: "Missing evidence", render: (r: Row) => r.reason }, { label: "Excluded", render: (r: Row) => r.count },
    ]}/><p className="small muted">A later rising price does not prove an achievable missed trade. Missing features and unobserved windows are excluded from training.</p></Panel>
    <Panel><h2>Exit feedback</h2><p>{d?.exit_feedback?.modeled_stop_episodes ?? 0} modeled stop episodes · {d?.exit_feedback?.ambiguous_barrier_episodes ?? 0} ambiguous stop/target candles · {d?.exit_feedback?.short_horizon_positive_long_horizon_negative ?? 0} short-positive / long-negative paths.</p><p>{d?.exit_feedback?.policy ?? "Collecting matched historical conditions"}</p><p className="small muted">{d?.exit_feedback?.limitations}</p><p className="small muted">Actual ledger outcomes collected: {d?.realized_positions_collected ?? 0}. Research does not rewrite existing stops, targets or account history.</p></Panel>
  </div>;
}
