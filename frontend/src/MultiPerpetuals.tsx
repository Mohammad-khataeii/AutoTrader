import { useState } from "react";
import { errorMessage, useApi, useResource, type Row } from "./api";
import { Badge, Panel, ResourceState, Technical } from "./ui";

const path = "/api/perpetuals/multi";
const num = (value: unknown, digits = 2) => value == null || value === "" || !Number.isFinite(Number(value)) ? "Unknown" : Number(value).toLocaleString(undefined, { minimumFractionDigits: digits, maximumFractionDigits: digits });
const money = (value: unknown) => `${num(value)} USDT`;
const pct = (value: unknown) => value == null ? "Unknown" : `${num(value, 3)}%`;
const words = (value: unknown) => typeof value === "string" ? value.toLowerCase().replace(/_/g, " ") : "Unknown";
const when = (value: unknown) => typeof value === "number" ? new Date(value).toLocaleString() : "Unknown";

function MultiHistory() {
  const [kind, setKind] = useState("EXIT_SETTLED");
  const [pages, setPages] = useState<number[]>([]);
  const cursor = pages.length ? pages[pages.length - 1] : undefined;
  const resource = useResource(path + "/history?limit=30" + (kind ? "&kind=" + kind : "") + (cursor ? "&cursor=" + cursor : ""), { poll: cursor ? 0 : 15000 });
  const rows = (resource.data?.rows ?? []) as Row[];
  return <Panel>
    <h3>Trading history and outcome evidence</h3>
    <label>Event type <select value={kind} onChange={e => { setKind(e.target.value); setPages([]); }}>
      <option value="EXIT_SETTLED">Closed trades: wins and losses</option>
      <option value="ENTRY_FILLED">Simulated entries</option>
      <option value="SIGNAL_REJECTED">Rejected hypotheses</option>
      <option value="ENTRY_MISSED">Missed entries</option>
      <option value="ENTRY_EXPIRED">Expired entries</option>
      <option value="HYPOTHETICAL_FORECAST_REVIEW">Hypothetical forecast reviews</option>
      <option value="">All journal events</option>
    </select></label>
    <ResourceState resource={resource} label="Multi-coin history" />
    {!rows.length && resource.data && <p>No recorded events in this category.</p>}
    {rows.map(event => <details key={event.id} className="perp-research-cohort">
      <summary>{when(event.at)} · {event.position?.symbol ?? event.signal?.symbol ?? event.symbol ?? "Ledger"} · {event.cohort ? event.cohort + "× · " : ""}{words(event.kind)}{event.net != null ? " · Net " + money(event.net) : ""}</summary>
      {event.net != null && <p>Gross {money(event.gross)} · Entry fee {money(event.entry_fee)} · Exit fee {money(event.exit_fee)} · Funding {money(event.funding)} · Margin ROI {pct(event.margin_roi_pct)} · Position account ROI {pct(event.account_roi_pct)}</p>}
      {event.position?.observed_exit?.classification && <p>{words(event.position.observed_exit.classification)}</p>}
      <p>{words(event.reason)}{event.planned_risk_exceeded ? " · Loss exceeded the planned stop risk." : ""}</p>
      {event.observed?.hypothetical_no_fill && <p>Forecast review only; no executable trade or profit is inferred. Barrier order may be ambiguous.</p>}
      <Technical value={event} label="Original event evidence" />
    </details>)}
    <div className="pagination">
      <button disabled={!pages.length} onClick={() => setPages(p => p.slice(0, -1))}>Newer</button>
      <button disabled={!resource.data?.next_cursor} onClick={() => setPages(p => [...p, resource.data.next_cursor])}>Older</button>
    </div>
  </Panel>;
}

export function MultiPerpetuals() {
  const api = useApi();
  const resource = useResource(path, { poll: 10000 });
  const data = resource.data as Row | undefined;
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  async function control(enabled: boolean) {
    setBusy(true); setError("");
    try { await api.request(path + "/entries", "POST", { enabled }); await api.refresh(path); }
    catch (e) { setError(errorMessage(e)); }
    finally { setBusy(false); }
  }
  return <>
    <Panel>
      <h2>Multi-coin micro-move paper trading</h2>
      <ResourceState resource={resource} label="Multi-coin experiments" />
      <p>Independent virtual USDT accounts · 1× / 3× / 10× · Experimental deterministic strategies · No real exchange orders.</p>
      <p>Conditional target scenarios are not proven expected returns. Higher leverage changes collateral and liquidation risk, rather than multiplying total-account profit.</p>
      {data && <>
        <Badge tone={data.status === "ACTIVE" && data.scan_fresh ? "positive" : "warning"}>{words(data.status)}</Badge>
        <p>{data.experiment}</p>
        {!data.feature_enabled && <p>This independent feature is disabled in the current configuration.</p>}
        {data.feature_enabled && <button disabled={busy || (!data.entries_enabled && (!data.scan_fresh || data.status !== "ACTIVE"))} onClick={() => void control(!data.entries_enabled)}>
          {data.entries_enabled ? "Pause multi-coin entries" : "Enable experimental paper entries"}
        </button>}
        <p>Protective monitoring continues when entries are paused.</p>
        {error && <p className="notice warning" role="alert">{error}</p>}
        {data.scan && <>
          <p><strong>{data.scan.summary}</strong></p>
          <p>Scan observed {when(data.scan.at)} · {data.scan_fresh ? "Current" : "Stale or incomplete; previous counts are historical"}</p>
        </>}
        {data.monitor?.errors && Object.keys(data.monitor.errors).length > 0 && <Technical value={data.monitor} label="Protective data incidents" />}
      </>}
    </Panel>
    {data && <>
      <div className="perp-accounts">
        {(data.accounts ?? []).map((account: Row) => <Panel key={account.leverage}>
          <h3>{account.leverage}× multi-coin account</h3>
          <p>Equity <strong>{money(account.equity)}</strong> · Account ROI {pct(account.account_roi_pct)}</p>
          <p>Free collateral {money(account.free_collateral)} · Reserved {money(account.reserved)} · Margin in positions {money(account.margin_used)}</p>
          <p>Estimated open net P&amp;L {money(account.estimated_net_unrealized)} · Open-margin ROI {pct(account.open_margin_roi_pct)} · Margin utilization {pct(account.margin_utilization_pct)}</p>
          <p>Realized net P&amp;L {money(account.realized)} · Fees {money(account.fees)} · Funding {money(account.funding)} · Modeled residual slippage {money(account.slippage)}</p>
          <p>{account.closed} closed · {account.liquidations} liquidations · Max drawdown {pct(String(Number(account.drawdown) * 100))}</p>
          {account.halted && <Badge tone="warning">Drawdown halt</Badge>}
        </Panel>)}
      </div>
      <Panel>
        <h3>Market scanner</h3>
        <p>Dashboard asset identities map to validated USDT perpetuals. EUR spot quotes are not execution prices.</p>
        <div className="table-wrap" tabIndex={0} aria-label="Multi-coin perpetual market scanner">
          <table><thead><tr><th>Coin / contract</th><th>Price</th><th>Regime / strategy</th><th>Target move</th><th>Cost / qualification</th><th>Status / reason</th></tr></thead>
            <tbody>{(data.scan?.rows ?? []).map((row: Row) => <tr key={row.symbol}>
              <td>{row.base} / {row.symbol}</td><td>{money(row.price)}</td>
              <td>{words(row.regime)}<br />{row.policy ?? "Not detailed yet"}</td>
              <td>{pct(row.target_move_pct)}</td><td>{pct(row.plans?.[0]?.round_trip_cost_pct)}<br />{words(row.qualification)}</td><td>{words(row.status)}<br />{row.reason ? words(row.reason) : ""}</td>
            </tr>)}</tbody></table>
        </div>
        <Technical value={data.scan?.unsupported ?? []} label="Unsupported or ambiguous asset mappings" />
      </Panel>
      <Panel>
        <h3>Latest scenario-qualified opportunities</h3>
        <p>Each row retains its own signal time. Filled and already-consumed opportunities are not fresh orders.</p>
        {(data.scan?.top_opportunities ?? []).map((row: Row) => <details key={row.signal_id} className="perp-research-cohort">
          <summary>{row.symbol} · {row.direction === 1 ? "Long" : "Short"} · {row.policy} · {pct(row.target_move_pct)}</summary>
          <p>Observed {when(row.observed_at)} · {words(row.status)}</p>
          {(row.plans ?? []).map((plan: Row) => <p key={plan.leverage}>{plan.leverage}× · Entry estimate {money(plan.entry_estimate)} · Stop {money(plan.stop)} · Target {money(plan.target)} · Notional {money(plan.notional)} · Margin {money(plan.margin_estimate)} · Net at target scenario {money(plan.scenario_gain)} · Cost {pct(plan.round_trip_cost_pct)} · Expected net value: unknown</p>)}
        </details>)}
      </Panel>
      <Panel>
        <h3>Open simulated positions</h3>
        {!(data.positions ?? []).length && <p>No open multi-coin positions.</p>}
        {(data.positions ?? []).map((position: Row) => <div className="perp-research-policy" key={position.id}>
          <h4>{position.symbol} · {position.side === 1 ? "Long" : "Short"} · {position.leverage}×</h4>
          <p>{words(position.status)} · {num(position.age_minutes, 1)} minutes · {position.valuation_fresh ? "Fresh mark" : "Stale mark"}</p>
          <p>Entry {money(position.entry)} · Mark {money(position.mark)} · Gross unrealized {money(position.gross_unrealized)} · Estimated net unrealized {money(position.estimated_net_unrealized)}</p>
          <p>Underlying move {pct(position.underlying_move_pct)} · Margin ROI {pct(position.margin_roi_pct)} · Position contribution to account ROI {pct(position.position_account_roi_pct)}</p>
          <p>Stop {money(position.stop)} · Target {money(position.target)} · Liquidation {money(position.liquidation_mark)} · Liquidation distance {pct(position.liquidation_distance_pct)}</p>
          <p>Funding {money(position.funding)} · Collateral {money(position.margin)} · {position.signal.policy}</p>
        </div>)}
      </Panel>
      <Panel>
        <h3>Measured paper outcomes by coin, strategy and cohort</h3>
        <p>{data.performance_scope ?? "No settlement evidence yet."}</p>
        {(data.performance ?? []).map((stats: Row) => <div key={stats.symbol + stats.policy + stats.leverage} className="perp-research-policy">
          <p>{stats.symbol} · {stats.policy} · {stats.leverage}× · {stats.closed} closed · {stats.wins} wins / {stats.losses} losses · Net {money(stats.net)}</p>
          <p>Fees {money(stats.fees)} · Funding {money(stats.funding)} · {stats.stop_outs} stops / {stats.target_exits} target exits / {stats.time_exits} time exits. Regime accuracy remains unknown without independent labels.</p>
        </div>)}
      </Panel>
      <MultiHistory />
    </>}
  </>;
}
