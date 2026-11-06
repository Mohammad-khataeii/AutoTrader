import { useResource, type Row } from "./api";

function label(value: unknown) {
  return value == null ? "—" : String(value).replace(/_/g, " ");
}
function timestamp(value?: string) {
  return value ? new Date(value).toLocaleString("en-US", { timeZone: "America/New_York", timeZoneName: "short", month: "short", day: "numeric", hour: "2-digit", minute: "2-digit", second: "2-digit" }) : "—";
}
function price(value: unknown) {
  return value == null ? "—" : Number(value).toLocaleString("en-US", { style: "currency", currency: "USD" });
}

export function IntradayMonitor() {
  const resource = useResource("/api/stockswatch/intraday", { poll: 2500, ttl: 1000 });
  const data: Row = resource.data ?? {};
  const observations: Row[] = (data.rows ?? []).slice().sort((a: Row, b: Row) =>
    (a.rank ?? 999) - (b.rank ?? 999) || a.symbol.localeCompare(b.symbol));
  const orders: Row[] = data.orders ?? [];
  return <article className="sw-panel" aria-label="StocksWatch intraday paper monitor">
    <div className="sw-intel-row"><h3>Intraday paper strategy</h3><strong>{label(data.current_phase ?? data.phase)}</strong></div>
    {resource.error && <p role="alert" className="sw-warning">Intraday status could not be refreshed.</p>}
    <p>{data.tracked ?? "—"} tracked · {data.daily_refresh_due ?? "—"} due for EOD refresh · {data.valid ?? 0} intraday valid</p>
    <p>Feed {label(data.feed_scope)} · Last fetch {timestamp(data.at)} · Decision {timestamp(data.finished_at)}</p>
    <p>{data.stale ? "Saved evidence is stale or belongs to a prior session. " : ""}{label(data.execution ?? data.reason ?? data.status)} · {label(data.order_gate ?? "Paper configuration eligible")}</p>
    {data.daily_loss_paused && <p className="sw-warning">Daily loss pause is active. Owned-position exit checks continue.</p>}
    {data.transport_recovered && <p>Broker transport recovered. Admission checks ran again.</p>}
    <div className="sw-intel-row"><span>Intraday realized / unrealized fill P&amp;L</span><strong>{price(data.pnl?.realized_usd)} / {price(data.pnl?.unrealized_usd)}</strong></div>
    <div className="sw-intel-row"><span>Rejected setups with later positive quote proxy</span><strong>{data.missed_proxies?.positive ?? 0} / {data.missed_proxies?.resolved ?? 0}</strong></div>
    <details className="sw-disclosure"><summary>Rank, quote freshness and decisions</summary>
      <div className="sw-table-scroll"><table className="sw-table"><thead><tr>
        <th>Rank</th><th>Symbol</th><th>Bid / ask</th><th>Quote</th><th>Ownership</th><th>Action</th><th>Evidence or risk decision</th>
      </tr></thead><tbody>{observations.map(row => <tr key={row.symbol}>
        <td>{row.rank ?? "—"}</td><td>{row.symbol}</td><td>{price(row.quote?.bp)} / {price(row.quote?.ap)}</td>
        <td>{timestamp(row.quote?.t)}</td><td>{label(row.position_owner)}</td><td>{row.action}</td><td>{label(row.risk_decision ?? row.reason)}</td>
      </tr>)}</tbody></table></div>
      <a href="/api/stockswatch/export/intraday_observations" download>Download intraday evidence</a>
    </details>
    <details className="sw-disclosure"><summary>Intraday broker intent history · {orders.length} latest</summary>
      <div className="sw-table-scroll"><table className="sw-table"><thead><tr>
        <th>Symbol</th><th>Order</th><th>Filled / requested</th><th>State</th><th>Updated</th>
      </tr></thead><tbody>{orders.map(row => <tr key={row.client_id}>
        <td>{row.symbol}</td><td>{row.side} · {price(row.limit_price)} · {label(row.session)}</td>
        <td>{row.filled_qty ?? "—"} / {row.qty}</td><td>{label(row.broker_status ?? row.state)}</td><td>{timestamp(row.updated_at)}</td>
      </tr>)}</tbody></table></div>
    </details>
  </article>;
}
