import { useState } from "react";
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

export function IntradayMonitor({ eod, positions = [] }: { eod?: Row, positions?: Row[] }) {
  const resource = useResource("/api/stockswatch/intraday", { poll: 2500, ttl: 1000 });
  const registry = useResource("/api/stockswatch/universe", { poll: 60000, ttl: 30000 });
  const [search, setSearch] = useState("");
  const [sector, setSector] = useState("");
  const [filter, setFilter] = useState("");
  const data: Row = resource.data ?? {};
  const listings: Row[] = registry.data?.symbols ?? [];
  const observationsBySymbol = new Map<string, Row>((data.rows ?? []).map((row: Row) => [row.symbol, row]));
  const open = new Map(positions.map(p => [p.symbol, p]));
  const observations = (listings.length ? listings : (data.rows ?? []) as Row[]).map<Row>(meta => {
    const row = observationsBySymbol.get(meta.symbol) ?? {};
    const asset = meta.asset ?? {};
    const verified = asset.verified_at && Date.now() - new Date(asset.verified_at).getTime() <= 21600000;
    const borrow = row.borrow ?? (verified && asset.verified ? asset.halted || asset.trading_halted || asset.short_sale_restricted
      ? "RESTRICTED" : asset.shortable && asset.marginable && (asset.borrow_status === "easy_to_borrow" ||
        (asset.borrow_status == null && asset.easy_to_borrow)) ? "ETB" : "UNAVAILABLE" : "UNKNOWN");
    const action = data.stale ? "WAIT" : ({BUY:"LONG", SELL:"EXIT LONG", COVER_SHORT:"COVER SHORT"} as Record<string,string>)[row.action] ?? row.action ?? "WAIT";
    return { ...meta, ...row, borrow, action };
  }).sort((a, b) => (a.rank ?? 999) - (b.rank ?? 999) || a.symbol.localeCompare(b.symbol))
    .filter(row => (!sector || row.sector === sector) && (
      !filter || (filter === "OPEN" ? open.has(row.symbol) : filter === "ETB" ? row.borrow === "ETB" :
        filter === "LONG" ? row.action === "LONG" || row.candidate :
        filter === "SHORT" ? row.action === "SHORT" || row.short_reason === "short_candidate" : row.action === "WAIT"))
      && `${row.symbol} ${row.name ?? ""}`.toLowerCase().includes(search.trim().toLowerCase()));
  const orders: Row[] = data.orders ?? [];
  return <article className="sw-panel" aria-label="StocksWatch intraday paper monitor">
    <div className="sw-intel-row"><h3>StocksWatch strategy monitor</h3><strong>{label(data.current_phase ?? data.phase)}</strong></div>
    {resource.error && <p role="alert" className="sw-warning">Intraday status could not be refreshed.</p>}
    <p>{data.tracked ?? "—"} tracked · {data.daily_refresh_due ?? "—"} due for EOD refresh · {data.valid ?? 0} intraday valid</p>
    <p>Feed {label(data.feed_scope)} · Last fetch {timestamp(data.at)} · Decision {timestamp(data.finished_at)}</p>
    <p>{data.stale ? "Saved evidence is stale or belongs to a prior session. " : ""}{label(data.execution ?? data.reason ?? data.status)} · {label(data.order_gate ?? "Paper configuration eligible")}</p>
    {data.daily_loss_paused && <p className="sw-warning">Daily loss pause is active. Owned-position exit checks continue.</p>}
    {data.transport_recovered && <p>Broker transport recovered. Admission checks ran again.</p>}
    <div className="sw-intel-row"><span>EOD LONG · first core hour · {label(eod?.status)} · {eod?.signals?.length ?? 0} signals</span><strong>{eod?.broker_orders_submitted ?? 0} last-cycle orders</strong></div>
    <div className="sw-intel-row"><span>INTRADAY LONG · premarket, core and after-hours · {label(data.order_gate ?? "configured")}</span><strong>{price(data.pnl?.realized_usd)} / {price(data.pnl?.unrealized_usd)} P&amp;L · {data.pnl?.confirmed_fills ?? 0} fills</strong></div>
    <div className="sw-intel-row"><span>SHORT · core only · {label(data.short_order_gate ?? "configured")} · {data.short_candidates ?? 0} candidates</span><strong>{price(data.short_pnl?.realized_usd)} / {price(data.short_pnl?.unrealized_usd)} P&amp;L · {data.short_pnl?.confirmed_fills ?? 0} fills</strong></div>
    {!!data.short_positions?.length && <ul>{data.short_positions.map((p: Row) => <li key={p.symbol}>SHORT {p.symbol} · {p.quantity} shares · entry {price(p.entry_price)} · gross {price(p.gross)} · broker mark P&amp;L {price(p.broker_unrealized)}</li>)}</ul>}
    <div className="sw-intel-row"><span>Rejected setups with later positive quote proxy</span><strong>{data.missed_proxies?.positive ?? 0} / {data.missed_proxies?.resolved ?? 0}</strong></div>
    <details className="sw-disclosure"><summary>Unified scanner · {registry.data?.companies ?? "—"} companies and {registry.data?.benchmarks ?? "—"} benchmarks</summary>
      <div className="sw-actionline">
        <input aria-label="Search stock universe" placeholder="Ticker or company" value={search} onChange={e=>setSearch(e.target.value)} />
        <select aria-label="Filter stock decisions" value={filter} onChange={e=>setFilter(e.target.value)}>
          <option value="">All decisions</option><option>LONG</option><option>SHORT</option><option>WAIT</option>
          <option value="OPEN">Open positions</option><option value="ETB">Eligible borrow evidence</option>
        </select>
        <select aria-label="Filter sectors" value={sector} onChange={e=>setSector(e.target.value)}>
          <option value="">All sectors</option>{Array.from(new Set(listings.map(row=>row.sector))).sort().map(s=><option key={s}>{s}</option>)}
        </select>
      </div>
      <div className="sw-table-scroll"><table className="sw-table"><thead><tr>
        <th>Rank / ticker</th><th>Last price / move</th><th>Quote / source</th><th>Long / short score</th><th>Ownership / decision</th><th>Borrow / EOD evidence</th><th>Reason</th>
      </tr></thead><tbody>{observations.map(row => <tr key={row.symbol}>
        <td>{row.rank ?? "—"} · {row.symbol}<br/><small>{row.name ?? row.instrument_type}</small></td>
        <td>{price(row.trade?.p)} · {row.gap == null ? "—" : `${(100*Number(row.gap)).toFixed(2)}%`}</td>
        <td>{timestamp(row.quote?.t)} · {label(row.feed)}</td>
        <td>{row.score == null ? "—" : Number(row.score).toFixed(1)} / {row.short_score == null ? "—" : Number(row.short_score).toFixed(1)}</td>
        <td>{label(row.position_owner)} · {row.action}</td>
        <td>{row.borrow} · {row.eod_certified_window_complete ? "201 certified sessions" : `${row.missing_sessions?.length ?? "—"} missing raw sessions`}
          <br/><small>{(row.coverage ?? []).map((x: Row)=>`${x.feed} ${x.timeframe} ${x.rows} through ${x.last}`).join(" · ")}</small></td>
        <td>{label(row.short_risk ?? row.risk_decision ?? row.reason)} · {label(row.short_reason)}</td>
      </tr>)}</tbody></table></div>
      <a href="/api/stockswatch/export/intraday_observations" download>Download intraday evidence</a>
    </details>
    <details className="sw-disclosure"><summary>Intraday broker intent history · {orders.length} latest</summary>
      <div className="sw-table-scroll"><table className="sw-table"><thead><tr>
        <th>Symbol</th><th>Order</th><th>Filled / requested</th><th>State</th><th>Updated</th>
      </tr></thead><tbody>{orders.map(row => <tr key={row.client_id}>
        <td>{row.symbol}</td><td>{label(row.action ?? row.side)} · {price(row.limit_price)} · {label(row.session)}</td>
        <td>{row.filled_qty ?? "—"} / {row.qty}</td><td>{label(row.broker_status ?? row.state)}</td><td>{timestamp(row.updated_at)}</td>
      </tr>)}</tbody></table></div>
    </details>
  </article>;
}
