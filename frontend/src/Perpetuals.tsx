import { useState } from "react";
import { errorMessage, useApi, useResource } from "./api";
import { Badge, Panel, ResourceState, Technical } from "./ui";

const path = "/api/perpetuals";
type Value = string | null | undefined;
type PositionMetrics = {
  underlying_price_change_pct: Value;
  direction_adjusted_price_change_pct: Value;
  gross_unrealized_pnl_usdt: Value;
  estimated_net_unrealized_pnl_usdt: Value;
  gross_margin_roi_pct: Value;
  estimated_net_margin_roi_pct: Value;
  estimated_position_account_roi_pct: Value;
  margin_utilization_pct: Value;
  liquidation_distance_pct: Value;
  estimated_net_at_existing_target_usdt: Value;
};
type Position = {
  side: number; qty: string; entry: string; notional: string; margin: string;
  stop: string; target: string; liquidation_mark: string; funding: string;
};
type Account = {
  leverage: number; equity: string; cash: string; realized: string;
  max_drawdown: string; closed: number; liquidations: number; halted: boolean;
  position: Position | null;
  metrics?: {
    account_roi_pct: Value; account_net_pnl_usdt: Value; valuation_fresh: boolean;
    position_metrics: PositionMetrics | null;
  };
};
type LabEvent = { kind: string; minute: number; leverage?: number; net?: string; amount?: string };
type Lab = {
  available: boolean; data_fresh: boolean; feed_status: string; entries_enabled: boolean;
  policy: string; mark: string | null; bar_closed_at: number | null;
  pending: { side: number; fill_at: number } | null; accounts: Account[]; events: LabEvent[];
  strategy?: {
    identity: string; timeframe: string; qualification: string; market_regime: string | null;
    signal_direction: string | null; approximate_round_trip_cost_pct: Value;
    break_even_underlying_move_long_pct: Value; break_even_underlying_move_short_pct: Value;
  };
};
type Candidate = {
  policy: string; direction: string; leverage: number; qualification: string;
  candidate_move_pct: Value; expected_underlying_move_pct: Value; expected_net_move_pct: Value;
  estimated_round_trip_cost_pct: Value; minimum_viable_move_pct: Value;
  expected_net_pnl_usdt: Value; expected_margin_roi_pct: Value; expected_account_roi_pct: Value;
  target_scenario_net_pnl_usdt?: Value; potential_loss_usdt: Value;
  estimated_win_probability: Value; expected_holding_minutes: Value;
  planned_max_holding_minutes: number; liquidation_buffer_pct: Value;
  estimated_entry?: Value; stop?: Value; target?: Value;
  notional_usdt?: Value; isolated_margin_usdt?: Value; margin_utilization_pct?: Value;
  rejection_reasons: string[]; probability_source: string;
};
type Research = {
  enabled: boolean; status: string; model_state: string; observed_at?: number;
  quote_expires_at?: number; strategies: string[]; candidate_rows: Candidate[];
  market?: { regime: string; spread_pct: Value; cutoff: number };
};

const amount = (value: Value, digits = 2) =>
  value == null || value === "" || !Number.isFinite(Number(value)) ? "Unknown" :
    Number(value).toLocaleString(undefined, { maximumFractionDigits: digits, minimumFractionDigits: digits });
const usdt = (value: Value) => value == null || value === "" ? "Unknown" : amount(value) + " USDT";
const pct = (value: Value) => value == null || value === "" ? "Unknown" : amount(value, 3) + "%";
const at = (ms: number) => new Date(ms).toLocaleString();
const side = (value: number) => value === 1 ? "Long" : "Short";
const readable = (value: string) => value.toLowerCase().replace(/_/g, " ");
const feedLabel: Record<string, string> = {
  DISABLED: "Disabled", WAITING: "Waiting for market data", CURRENT: "Market data current",
  STALE: "Market data stale", DEGRADED: "Market data unavailable or incomplete",
};
const eventLabel: Record<string, string> = {
  SIGNAL: "Signal queued", OPEN: "Opened", FUNDING: "Funding", STOP: "Stop",
  TARGET: "Target", TIME_EXIT: "Time exit", LIQUIDATION: "Liquidated", RISK_HALT: "Risk halt",
  ENTRY_SKIPPED: "Entry skipped", ENTRY_EXPIRED: "Entry expired",
  RESUME_ENTRIES: "Entries resumed", PAUSE_ENTRIES: "Entries paused",
};
const policyLabel: Record<string, string> = {
  BTC_MICRO_CONTINUATION_V1: "Micro-trend continuation",
  BTC_MICRO_RETEST_V1: "Breakout and retest",
  BTC_MICRO_RANGE_V1: "Range mean reversion",
};

function ResearchPanel() {
  const resource = useResource(path + "/research", { poll: 15000 });
  const research = resource.data as Research | undefined;
  const expired = Boolean(research?.quote_expires_at && Date.now() > research.quote_expires_at);
  return <Panel>
    <h2>Micro-move research</h2>
    <ResourceState resource={resource} label="Micro-move research" />
    <p>Untested and unvalidated. These candidates cannot place trades or change the existing accounts.</p>
    {research && <>
      <Badge tone="warning">{research.enabled ? readable(research.status) : "Preview disabled"}</Badge>
      <p>Qualification: {readable(research.model_state)}. Probabilities and expected profits stay unknown until supported by reviewed outcome evidence.</p>
      {!research.enabled && <p>The optional preview is disabled by default. No micro-strategy is active.</p>}
      {research.market && <p>Regime: {readable(research.market.regime)} · Observed spread {pct(research.market.spread_pct)} · Completed data through {at(research.market.cutoff)}</p>}
      {research.observed_at && <p>Snapshot {at(research.observed_at)}{research.quote_expires_at && <> · Quote expires {at(research.quote_expires_at)}</>}. {expired ? "The depth quote has expired; values below are historical estimates." : "Depth estimates can change before execution."}</p>}
      {research.strategies.map(policy => <div className="perp-research-policy" key={policy}>
        <h3>{policyLabel[policy] ?? policy}</h3>
        <p className="small muted">{policy} · Completed 1m / 3m / 5m data</p>
        {research.candidate_rows.filter(row => row.policy === policy).map(row => <details key={row.leverage} className="perp-research-cohort">
          <summary>{row.leverage}× · {readable(row.direction)} · {row.rejection_reasons.length ? "Abstain" : "Research proposal only"}</summary>
          <dl className="perp-metrics">
            <div><dt>Candidate target move</dt><dd>{pct(row.candidate_move_pct)}</dd></div>
            <div><dt>Estimated round-trip cost</dt><dd>{pct(row.estimated_round_trip_cost_pct)}</dd></div>
            <div><dt>Move needed to break even</dt><dd>{pct(row.minimum_viable_move_pct)}</dd></div>
            <div><dt>Expected underlying move</dt><dd>{pct(row.expected_underlying_move_pct)}</dd></div>
            <div><dt>Expected net move</dt><dd>{pct(row.expected_net_move_pct)}</dd></div>
            <div><dt>Expected net P&amp;L</dt><dd>{usdt(row.expected_net_pnl_usdt)}</dd></div>
            <div><dt>Expected margin ROI</dt><dd>{pct(row.expected_margin_roi_pct)}</dd></div>
            <div><dt>Expected account ROI</dt><dd>{pct(row.expected_account_roi_pct)}</dd></div>
            <div><dt>Net at target scenario</dt><dd>{usdt(row.target_scenario_net_pnl_usdt)}</dd></div>
            <div><dt>Planned stop loss estimate</dt><dd>{usdt(row.potential_loss_usdt)}</dd></div>
            <div><dt>Notional / isolated margin</dt><dd>{usdt(row.notional_usdt)} / {usdt(row.isolated_margin_usdt)}</dd></div>
            <div><dt>Margin utilization</dt><dd>{pct(row.margin_utilization_pct)}</dd></div>
            <div><dt>Stop / target</dt><dd>{usdt(row.stop)} / {usdt(row.target)}</dd></div>
            <div><dt>Liquidation buffer</dt><dd>{pct(row.liquidation_buffer_pct)}</dd></div>
            <div><dt>Probability of target first</dt><dd>{row.estimated_win_probability == null ? "Unknown" : pct(String(Number(row.estimated_win_probability) * 100))}</dd></div>
            <div><dt>Holding period</dt><dd>{amount(row.expected_holding_minutes)} expected · {row.planned_max_holding_minutes} min limit</dd></div>
          </dl>
          <p>Gap losses can exceed the planned stop estimate. Target scenarios are conditional calculations.</p>
          <p>Qualification: {readable(row.qualification)}. Probability source: {readable(row.probability_source)}.</p>
          {row.rejection_reasons.length > 0 && <ul>{row.rejection_reasons.map(reason => <li key={reason}>{readable(reason)}</li>)}</ul>}
        </details>)}
      </div>)}
      {research.candidate_rows.length > 0 && <Technical value={research} label="Research assumptions and source timestamps" />}
    </>}
  </Panel>;
}

export function Perpetuals() {
  const api = useApi();
  const resource = useResource(path, { poll: 12000 });
  const lab = resource.data as Lab | undefined;
  const [busy, setBusy] = useState(false);
  const [problem, setProblem] = useState("");
  async function change(enabled: boolean) {
    setBusy(true);
    setProblem("");
    try {
      await api.request(path + "/entries", "POST", { enabled });
      await api.refresh(path);
    } catch (error) {
      setProblem(errorMessage(error));
    } finally {
      setBusy(false);
    }
  }

  return <>
    <ResourceState resource={resource} label="Perpetuals lab" />
    {lab && <>
      <Panel>
        <h2>BTC/USDT perpetuals</h2>
        <p>Paper only · isolated margin · 1×, 3× and 10× accounts each start with 1,000 simulated USDT.</p>
        <p>Strategy: {lab.strategy?.identity ?? lab.policy} · {lab.strategy?.timeframe ?? "15m signal / 1m protection"}</p>
        <p>Qualification: {readable(lab.strategy?.qualification ?? "UNVALIDATED_BASELINE")} · Regime: {lab.strategy?.market_regime ? readable(lab.strategy.market_regime) : "Unknown"} · Signal: {lab.strategy?.signal_direction ? readable(lab.strategy.signal_direction) : "No queued entry"}</p>
        <p>10× changes required collateral and liquidation risk. Margin ROI and total-account ROI use different amounts of capital.</p>
        <Badge tone={lab.data_fresh && !resource.error ? "positive" : "warning"}>{feedLabel[lab.feed_status] ?? "Unknown"}</Badge>
        <p>Bybit mark: <strong>{usdt(lab.mark)}</strong>{lab.bar_closed_at && <> · Last processed minute closed {at(lab.bar_closed_at)}</>}</p>
        {lab.strategy && <p>Fixed-model round-trip cost approximately {pct(lab.strategy.approximate_round_trip_cost_pct)}. Underlying move to break even: long {pct(lab.strategy.break_even_underlying_move_long_pct)}, short {pct(lab.strategy.break_even_underlying_move_short_pct)}, before additional funding and observed liquidity costs.</p>}
        <p className="small muted">The existing strategy uses candle-based price proxies. Those records do not establish executable micro-move returns.</p>
        {lab.available ? <>
          <p>{lab.entries_enabled ? "New baseline entries enabled" : "New baseline entries paused"}. Pausing entries keeps protection running for open positions.</p>
          {lab.pending && <p>{side(lab.pending.side)} entry queued for the minute starting {at(lab.pending.fill_at)}.</p>}
          <button className="button" disabled={busy || (!lab.entries_enabled && (!lab.data_fresh || Boolean(resource.error)))}
            onClick={() => void change(!lab.entries_enabled)}>{lab.entries_enabled ? "Pause new entries" : "Enable baseline paper entries"}</button>
        </> : <p>Enable the Perpetuals lab in the local or staging configuration to start receiving market data.</p>}
        {problem && <p role="alert" className="notice warning">{problem}</p>}
      </Panel>
      <div className="perp-accounts">
        {lab.accounts.map(a => {
          const metrics = a.metrics?.position_metrics;
          return <Panel key={a.leverage}>
            <h3>{a.leverage}× isolated</h3>
            <p>Equity <strong>{usdt(a.equity)}</strong></p>
            <p>Total-account ROI {pct(a.metrics?.account_roi_pct)} · Net account P&amp;L {usdt(a.metrics?.account_net_pnl_usdt)}</p>
            <p>Free cash {usdt(a.cash)} · Realized net P&amp;L {usdt(a.realized)}</p>
            <p>{a.closed} closed · {a.liquidations} liquidated · {(Number(a.max_drawdown) * 100).toFixed(2)}% max drawdown</p>
            {a.halted && <Badge tone="warning">Drawdown limit reached; new entries halted</Badge>}
            {a.position ? <>
              <p><strong>{side(a.position.side)}</strong> · {amount(a.position.qty, 6)} BTC · Entry {usdt(a.position.entry)}</p>
              <p>Notional {usdt(a.position.notional)} · Margin {usdt(a.position.margin)} · Funding {usdt(a.position.funding)}</p>
              <dl className="perp-metrics">
                <div><dt>Underlying entry-price change</dt><dd>{pct(metrics?.underlying_price_change_pct)}</dd></div>
                <div><dt>Direction-adjusted move</dt><dd>{pct(metrics?.direction_adjusted_price_change_pct)}</dd></div>
                <div><dt>Gross unrealized P&amp;L</dt><dd>{usdt(metrics?.gross_unrealized_pnl_usdt)}</dd></div>
                <div><dt>Estimated net unrealized P&amp;L</dt><dd>{usdt(metrics?.estimated_net_unrealized_pnl_usdt)}</dd></div>
                <div><dt>Gross margin ROI</dt><dd>{pct(metrics?.gross_margin_roi_pct)}</dd></div>
                <div><dt>Estimated net margin ROI</dt><dd>{pct(metrics?.estimated_net_margin_roi_pct)}</dd></div>
                <div><dt>Position contribution to entry account equity</dt><dd>{pct(metrics?.estimated_position_account_roi_pct)}</dd></div>
                <div><dt>Current margin utilization</dt><dd>{pct(metrics?.margin_utilization_pct)}</dd></div>
                <div><dt>Mark distance to liquidation</dt><dd>{pct(metrics?.liquidation_distance_pct)}</dd></div>
                <div><dt>Net at existing target scenario</dt><dd>{usdt(metrics?.estimated_net_at_existing_target_usdt)}</dd></div>
              </dl>
              <p>Stop {usdt(a.position.stop)} · Target {usdt(a.position.target)} · Model liquidation mark {usdt(a.position.liquidation_mark)}</p>
              <p className="small muted">Net position estimates include paid entry fees, current funding and modeled closing fees and slippage. Account equity keeps the existing mark valuation. Future funding and liquidity can change the outcome.</p>
            </> : <p>No open position.</p>}
          </Panel>;
        })}
      </div>
      <ResearchPanel />
      <Panel>
        <h2>Recent simulated activity</h2>
        {lab.events.length === 0 ? <p>No activity yet.</p> : <>
          <ul>{lab.events.slice(0, 20).map((event, index) => <li key={event.minute + ":" + index}>
            {at(event.minute)} · {event.leverage ? event.leverage + "× · " : ""}{eventLabel[event.kind] ?? event.kind}
            {event.net != null || event.amount != null ? " · " + usdt(event.net ?? event.amount) : ""}
          </li>)}</ul>
          <Technical value={lab.events} label="Last 60 event records" />
        </>}
      </Panel>
    </>}
  </>;
}
