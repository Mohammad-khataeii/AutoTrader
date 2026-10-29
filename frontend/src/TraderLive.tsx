import React, { useEffect, useState } from "react";
import { Activity, ArrowRight, Check, Circle, Radio, ScanEye } from "lucide-react";
import { type Row, useResource } from "./api";
import { date, money, price, strategyName } from "./model";
import { Panel, ResourceState } from "./ui";

const explanations: Record<string, string> = {
  primary_context_ready: "Aligned completed market and benchmark history is not ready.",
  primary_current_candle: "Another candle has completed since this evaluation. A fresh evaluation is required.",
  primary_macro_context: "Bitcoin and Ether both have bearish completed hourly trends, or their context is unavailable.",
  primary_local_reclaim: "The latest completed close has not reclaimed a rising short-term mean.",
  primary_recovery_reclaim: "The recovery has not reclaimed the completed fifteen-minute trend mean with a rising close.",
  paper_current_completed_candle_required: "The signal became outdated before broker admission; a new completed-candle evaluation is required.",
  paper_primary_admission_required: "This entry lacks the current primary account's context authorization.",
  paper_primary_context_required: "The primary account's completed market-context checks did not pass.",
  review_benchmark_support: "Synchronized Bitcoin and Ether context does not support this entry.",
  review_bullish_continuation: "A bullish continuation trend is required for this strategy.",
  review_completed_hourly_trend: "The completed one-hour trend does not confirm this setup.",
  review_target_within_overhead: "The first target would require breaking nearby resistance, or resistance evidence is missing.",
  review_target_cost_headroom: "Potential net profit at the first target is below twice the estimated round-trip cost, or the estimate is unavailable.",
  review_stop_above_noise: "The initial stop is less than one observed ATR from entry, or volatility evidence is unavailable.",
  nonbearish_trend: "The broader trend is still bearish.",
  higher_15m_bullish: "The 15-minute trend has not turned bullish.",
  recovering: "The pullback has not shown a confirmed recovery.",
  pullback_invalidation: "The pullback does not have a valid support / stop structure.",
  entry_not_chased: "Price is too extended; buying here would chase the move.",
  confirmed_delayed_retest: "The breakout has not held through a confirmed retest.",
  normalized_outperformance: "This asset is not outperforming enough after adjusting for volatility.",
  persistent_outperformance: "The relative strength has not persisted long enough.",
  relative_demand: "Trading demand is below the strategy’s threshold.",
  benchmarks_not_adverse: "Bitcoin or Ether context is unfavorable for this setup.",
  positive_local_trend: "The asset’s local trend is not positive.",
  recent_positive_returns: "Recent returns do not confirm upward momentum.",
  net_reward_risk_below_research_minimum: "The potential reward after fees and slippage is too small for the stop risk.",
  first_target_destroyed_by_execution_costs: "Estimated trading costs consume the first target’s potential gain.",
  target_not_supported_by_observed_structure_or_volatility: "The target is beyond what the observed price structure supports.",
  partial_exit_below_instrument_minimum: "The planned partial exits are below the market’s minimum order size.",
  insufficient_observed_exit_depth: "The observed buy-side liquidity is too thin to support the planned exit.",
  spread_too_wide: "The gap between buy and sell prices is too wide.",
  redundant_strategy_same_asset: "Another strategy already received priority for this asset.",
  completed_context_delayed: "Completed candle data is delayed; a fresh context is required.",
  latest_completed_candle_missing: "The latest completed candle is missing; fresh data is required.",
  completed_data: "Complete, synchronized candle history is not available yet.",
  not_extended: "Price is too far from its recent trend for this setup.",
  synchronized_relative_strength: "The asset and benchmark observations are not synchronized yet.",
  minimum_order_not_met: "The proposed amount is below the market’s minimum order size.",
  modeled_stop_loss_exceeds_account_budget: "The modeled stop loss exceeds the account’s risk budget.",
  risk_rejected: "The account’s final risk checks did not pass.",
  planned_loss_exceeded: "The planned loss is above the per-trade limit.",
  max_planned_loss_exceeded: "The planned loss is above the per-trade limit.",
  planned_loss: "The planned loss is above the per-trade limit.",
  reserve_preserved: "The trade would use cash that must remain in reserve.",
  cash_available: "The account does not have enough available cash.",
  total_exposure: "The trade would exceed the total exposure limit.",
  position_count: "The maximum number of open positions has been reached.",
  position_size: "The proposed position exceeds the size limit.",
  daily_loss_budget: "The daily loss limit has been reached.",
  weekly_loss_budget: "The weekly loss limit has been reached.",
  entry_frequency: "The maximum number of new entries for today has been reached.",
};

export function explainReason(reason: string): string {
  if (/[:,]/.test(reason)) return reason.split(/[:,]/).filter(Boolean).map(explainReason).join(" ");
  return explanations[reason] ?? `Required check not met: ${reason.replace(/_/g, " ").replace(/:/g, " · ")}.`;
}

export function eventTitle(event: Row): string {
  if (event.kind === "FILL") return `${event.side === "BUY" ? "Bought" : "Sold"} ${event.symbol} · paper fill`;
  if (event.kind === "ORDER") return `Paper ${event.side} order · ${String(event.status).replace(/_/g, " ").toLowerCase()}`;
  if (event.broker_status === "REJECTED") return `Not buying ${event.symbol} · broker rejected`;
  return event.accepted ? `${event.symbol} qualified for paper admission` : `Not buying ${event.symbol} yet`;
}

function reasonsFor(event: Row): string[] {
  return [...new Set<string>([...(event.reasons ?? []), ...(event.decision_reason?.split(",") ?? [])])].filter(Boolean);
}

function age(timestamp: unknown, now: number): string {
  const stamp = timestamp ? new Date(String(timestamp)).getTime() : NaN;
  if (!Number.isFinite(stamp)) return "No observation yet";
  const seconds = Math.max(0, Math.floor((now - stamp) / 1000));
  return seconds < 60 ? `${seconds}s ago` : seconds < 3600 ? `${Math.floor(seconds / 60)}m ${seconds % 60}s ago` : `${Math.floor(seconds / 3600)}h ${Math.floor(seconds % 3600 / 60)}m ago`;
}

function Stage({ name, state, detail }: { name: string; state: boolean | null; detail: string }) {
  return <div className={`trader-stage ${state === true ? "passed" : state === false ? "blocked" : "unreached"}`}>
    {state === true ? <Check size={16} aria-hidden="true"/> : <Circle size={15} aria-hidden="true"/>}
    <div><strong>{name}</strong><span>{detail}</span></div>
  </div>;
}

export function TraderLive({ paper, onSelectCoin }: { paper: Row; onSelectCoin?: (symbol: string) => void }) {
  const feed = useResource("/api/personal-paper/activity", { poll: 5000 });
  const [now, setNow] = useState(Date.now());
  const [selected, setSelected] = useState("");
  const [filter, setFilter] = useState("all");
  useEffect(() => { const timer = setInterval(() => setNow(Date.now()), 1000); return () => clearInterval(timer); }, []);
  const evaluations: Row[] = feed.data?.evaluations ?? [];
  const candidate = evaluations.find(e => e.id === selected) ?? evaluations[0];
  const events: Row[] = (feed.data?.events ?? []).filter((e: Row) => filter === "all" || (filter === "trades" ? e.kind !== "DECISION" : e.kind === "DECISION"));
  const observedAge = paper.observed_at ? (now - new Date(paper.observed_at).getTime()) / 1000 : Infinity;
  const fresh = !feed.error && Boolean(feed.updatedAt && now - feed.updatedAt < 20000) && observedAge < 40 && paper.worker_health?.fresh === true;
  const running = paper.portfolio?.control === "RUNNING" && paper.runtime_matches === true && paper.portfolio?.risk_state === "HEALTHY";
  const state = !fresh ? "Waiting for fresh status" : running ? "Worker connected" : "Entries suspended";
  const measurements = candidate?.economics?.measurements;
  const blocked = candidate ? reasonsFor(candidate) : [];
  const candidates = evaluations.filter((e, i) => evaluations.findIndex(r => r.symbol === e.symbol && r.strategy_id === e.strategy_id) === i);
  return <Panel className="trader-live">
    <div className="trader-live-heading">
      <div><p className="eyebrow">Live paper trader</p><h2>What the trader is doing</h2></div>
      <span className={`trader-connection ${fresh && running ? "connected" : "waiting"}`}><Radio size={15} aria-hidden="true"/>{state}</span>
    </div>
    <div className="trader-live-status">
      <Activity size={18} aria-hidden="true"/>
      <span>{!fresh ? "Showing the last recorded work. Fresh worker status is pending." : !running ? "New entries are suspended. Recorded decisions remain below." : paper.scan?.data_failures?.length ? "Market data checks need attention. Reviewing available markets and protecting positions." : `Watching ${paper.scan?.markets?.length ?? 0} markets. Waiting for new completed candles or a qualifying setup.`}</span>
    </div>
    <div className="trader-vitals">
      <span>Scan <strong>{age(paper.scan?.observed_at, now)}</strong></span>
      <span>Position checks <strong>{age(paper.position_monitor?.heartbeat, now)}</strong></span>
      <span>Feed refreshed <strong>{feed.updatedAt ? age(new Date(feed.updatedAt).toISOString(), now) : "Connecting…"}</strong></span>
      <span>Execution <strong>Virtual money only</strong></span>
    </div>
    <ResourceState resource={feed} label="Live activity"/>
    <div className="trader-workspace">
      <div className="trader-candidate">
        <div className="section-heading"><p className="eyebrow"><ScanEye size={15} aria-hidden="true"/> Latest completed evaluation</p>
          {selected && <button className="secondary" onClick={() => setSelected("")}>Follow latest</button>}</div>
        {candidate ? <>
          <div className="trader-market"><button className="trader-chart-link" onClick={() => onSelectCoin?.(candidate.symbol)} disabled={!onSelectCoin}>{candidate.symbol} <ArrowRight size={18}/></button><span>{strategyName(candidate.strategy_id)}</span></div>
          <h3>{eventTitle(candidate)}</h3>
          <p className="small muted">Recorded {date(candidate.timestamp, true)} · Candle {date(candidate.candle_at, true)}{selected && " · Pinned evaluation"}</p>
          <div className="trader-pipeline" aria-label="Candidate execution pipeline">
            <Stage name="Observed" state={true} detail="Recorded market candidate"/>
            <Stage name="Setup" state={candidate.technical ?? null} detail={candidate.technical === true ? "Technical checks passed" : candidate.technical === false ? "Conditions not met" : "Unverified"}/>
            <Stage name="Costs" state={candidate.technical === true ? candidate.economic ?? null : null} detail={candidate.technical !== true ? "Not reached" : candidate.economic === true ? "Economically feasible" : "Not qualified"}/>
            <Stage name="Entry quality" state={candidate.quality_policy?.gates ? Object.values(candidate.quality_policy.gates).every(v=>v===true) : null} detail={candidate.quality_policy ? "Benchmark, resistance, volatility and cost headroom" : "Earlier profile · no quality policy recorded"}/>
            {candidate.primary_admission && <Stage name="Primary context" state={Object.values(candidate.primary_admission.gates ?? {}).every(v=>v===true)} detail="Current completed candle, benchmark trend and local recovery confirmation"/>}
            <Stage name="Account decision" state={candidate.accepted === true} detail={candidate.accepted ? "Sent for locked admission" : "Wait · no buy decision"}/>
            <Stage name="Paper broker" state={candidate.broker_status ? ["FILLED", "PARTIALLY_FILLED"].includes(candidate.broker_status) ? true : false : null} detail={candidate.broker_status?.replaceAll("_", " ").toLowerCase() ?? (candidate.accepted ? "Awaiting broker record" : "No order submitted")}/>
          </div>
          <div className="trader-explanation">
            <strong>{candidate.broker_reason ? "Why the broker did not buy" : blocked.length ? "Why no buy happened" : candidate.accepted ? "What passed" : "Decision evidence"}</strong>
            {candidate.broker_reason && <p>{explainReason(candidate.broker_reason)}</p>}
            {blocked.length > 0 ? <ul>{blocked.map(r => <li key={r}>{explainReason(r)}</li>)}</ul> : <p>{candidate.accepted ? "The setup and estimated economics passed. A decision is only an intention; broker fills are recorded separately in the timeline." : "No detailed reason is available for this record."}</p>}
          </div>
          {measurements?.estimates_available && <div className="trader-estimates">
            <div><span>Proposed amount</span><strong>{money(candidate.quote_amount)}</strong></div>
            <div><span>Round-trip costs · estimate</span><strong>{money(measurements.estimated_total_round_trip_cost_eur)}</strong></div>
            <div><span>Net reward / risk · estimate</span><strong>{measurements.net_reward_risk ? Number(measurements.net_reward_risk).toFixed(2) : "Unavailable"}</strong></div>
          </div>}
          {candidate.ranking_components && <p className="small muted">Ranking uses conditional net reward/risk × reward/cost × portfolio fit ({Number(candidate.ranking_components.portfolio_fit).toFixed(2)}). Technical score breaks ties. Expected profitability is unknown.</p>}
          <label className="trader-candidate-select">Inspect another recent candidate
            <select value={candidate.id} onChange={e => {setSelected(e.target.value);}}>
              {candidate && !candidates.some(e => e.id === candidate.id) && <option value={candidate.id}>{candidate.symbol} · pinned evaluation</option>}
              {candidates.map(e => <option key={e.id} value={e.id}>{e.symbol} · {strategyName(e.strategy_id)} · {e.accepted ? "Qualified" : "Wait"}</option>)}
            </select>
          </label>
        </> : <div className="empty"><ScanEye size={30}/><h3>Waiting for recorded candidate evaluations</h3><p>The worker will add its actual decisions here. No demonstration trades are shown.</p></div>}
      </div>
      <div className="trader-feed">
        <div className="trader-feed-heading"><h3>Work timeline</h3><span className="small muted">Saved across restarts</span></div>
        <div className="trader-filter" role="group" aria-label="Activity type">
          {[["all", "All work"], ["decisions", "Candidates"], ["trades", "Orders & fills"]].map(([key, label]) => <button key={key} aria-pressed={filter === key} onClick={() => setFilter(key)}>{label}</button>)}
        </div>
        <ol className="trader-events" aria-label="Recorded paper activity">
          {events.slice(0, 40).map(e => <li key={e.id} className={`trader-event ${e.kind.toLowerCase()}`}>
            <div className="trader-event-icon" aria-hidden="true">{e.kind === "FILL" ? <Check size={15}/> : e.kind === "ORDER" ? <ArrowRight size={15}/> : <ScanEye size={15}/>}</div>
            <div><div className="trader-event-meta"><span>{e.kind === "FILL" ? "Actual paper fill" : e.kind === "ORDER" ? "Broker record" : "Candidate decision"}</span><time dateTime={e.timestamp} title={date(e.timestamp, true)}>{age(e.timestamp, now)}</time></div>
              <strong>{eventTitle(e)}</strong>
              {e.kind === "FILL" ? <p>{e.quantity} units at {price(e.price)} · Fee {money(e.fee_eur)}</p> : e.kind === "ORDER" ? <p>{e.symbol} · {e.reason ? explainReason(e.reason) : `Filled quantity ${e.filled_quantity} of ${e.quantity}.`}</p> : <p>{reasonsFor(e).length ? explainReason(reasonsFor(e)[0]) : "Setup passed; final account admission and broker execution are separate."}</p>}
              {onSelectCoin && <button className="trader-inspect" onClick={() => onSelectCoin(e.symbol)}>View {e.symbol} chart <ArrowRight size={12}/></button>}
              {e.strategy_id && <span className="small muted">{strategyName(e.strategy_id)}</span>}
              {e.kind === "DECISION" && <button className="trader-inspect" onClick={() => setSelected(e.id)}>Inspect checks <ArrowRight size={12} aria-hidden="true"/></button>}
            </div>
          </li>)}
        </ol>
        {!events.length && <p className="empty">{filter === "trades" ? "No recorded orders or fills in this window. Candidate decisions are under All work." : "Waiting for the first saved activity records."}</p>}
        <p className="small muted">Latest saved events · refreshes every 5 seconds while visible. Evaluations use completed candles; the feed can stay unchanged between them.</p>
      </div>
    </div>
    <p className="trader-evidence-note">{feed.data?.evidence_category === "SYNTHETIC_ACCEPTANCE" ? "Deterministic test fixtures — this is not live market evidence." : "Real Revolut X observations · simulated orders and fills · no real funds used."}</p>
  </Panel>;
}
