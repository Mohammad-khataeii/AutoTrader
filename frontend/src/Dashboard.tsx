import React, { useRef, useState } from "react";
import { ArrowDownLeft, ArrowUpRight, Coins, Wallet } from "lucide-react";
import { type Row, useResource } from "./api";
import { date, money, percent, price } from "./model";
import { Badge, CompactTable, Empty, Panel, Pnl, ResourceState } from "./ui";
import { TraderLive } from "./TraderLive";
import { TradeReports } from "./TradeReports";
import { CoinChart } from "./CoinChart";

export function Dashboard() {
  const resource = useResource("/api/personal-paper", {poll: 15000});
  const d = resource.data;
  const p = d?.portfolio;
  const [symbol, setSymbol] = useState("BTC-EUR");
  const chart = useRef<HTMLElement>(null);
  const selectCoin = (coin: string, scroll = false) => {setSymbol(coin); if(scroll) chart.current?.scrollIntoView({behavior:"smooth", block:"start"});};
  const markets: Row[] = d?.markets ?? [];
  const symbols = [...new Set<string>(["BTC-EUR", "ETH-EUR", "SOL-EUR", ...markets.map(m=>m.symbol), ...(d?.holdings ?? []).map((h:Row)=>h.symbol)])];
  const ratio = (value: unknown) => p?.equity && Number(p.equity)>0 && value != null && value!=="" ? Math.max(0,Math.min(100,Number(value)/Number(p.equity)*100)) : 0;
  if (!p) return <><ResourceState resource={resource} label="Dashboard portfolio"/>{d && <Panel><h2>Paper account initializing</h2><p>Waiting for the worker’s funded portfolio records.</p></Panel>}</>;
  return <div className="page-stack dashboard" aria-label="Paper trading dashboard">
    <ResourceState resource={resource} label="Dashboard portfolio"/>
    <div className="dashboard-summary">
      <Panel className="dashboard-value"><div className="section-heading"><span className="eyebrow"><Wallet size={15} aria-hidden="true"/> Your portfolio</span><Badge>Paper only</Badge></div><strong className="dashboard-equity">{money(p?.equity)}</strong>
        <p><Pnl value={p?.total_net_pnl}/> <span className="muted">total return · Budget {money(p?.initial_cash)}</span></p>
        <div className="capital-bar" aria-label="Portfolio allocation"><span style={{width:`${ratio(p?.available_cash)}%`}}/><span style={{width:`${ratio(p?.open_exposure)}%`}}/><span style={{width:`${ratio(p?.reserved_cash)}%`}}/></div>
        <div className="capital-legend"><span>Cash {percent(p?.equity && p?.available_cash ? Number(p.available_cash)/Number(p.equity) : undefined)}</span><span>Invested {percent(d?.performance?.capital_utilization)}</span><span>Reserved {money(p?.reserved_cash)}</span></div>
      </Panel>
      <div className="dashboard-money-grid">
        <div className="dashboard-money"><span>Available to trade</span><strong>{money(p?.available_cash)}</strong><small>Uncommitted virtual cash</small></div>
        <div className="dashboard-money"><span>Spent on buys</span><strong>{money(d?.cash_flow?.spent_on_buys_eur)}</strong><small>All filled buys, including fees</small></div>
        <div className="dashboard-money"><span>Invested now</span><strong>{money(p?.open_exposure)}</strong><small>Current marked holdings</small></div>
        <div className="dashboard-money"><span>Fees paid</span><strong>{money(d?.cash_flow?.fees_total_eur)}</strong><small>All recorded BUY and SELL fills</small></div>
      </div>
    </div>
    <section className="dashboard-market-panel" ref={chart} aria-label="Coin market explorer">
      <div className="dashboard-coin-list"><div className="section-heading"><h2>Markets</h2><Coins size={18} aria-hidden="true"/></div><p className="small muted">Select a coin to inspect its chart.</p>
        <div className="dashboard-coins">{symbols.map(coin=>{const m=markets.find(r=>r.symbol===coin);return <button key={coin} className="dashboard-coin" aria-pressed={symbol===coin} aria-label={`View ${coin} chart`} onClick={()=>selectCoin(coin)}>
          <span className="coin-monogram">{coin.split("-")[0].slice(0,2)}</span><span><strong>{coin.split("-")[0]}</strong><small>Euro market</small></span><span className="coin-list-price"><strong>{price(m?.last_observed_price)}</strong><small>{m ? m.fresh ? "Last observed" : "Older observation" : "History"}</small></span>
        </button>;})}</div>
      </div>
      <CoinChart key={symbol} symbol={symbol}/>
    </section>
    <div className="dashboard-account-grid">
      <Panel><div className="section-heading"><h2>Your holdings</h2><span className="small muted">{d?.performance?.open_positions ?? 0} open positions</span></div><CompactTable label="Dashboard holdings" rows={d?.holdings ?? []} empty={<Empty title="No coins held yet">Your filled paper buys will appear here, with quantity, cost and current value.</Empty>} columns={[
        {label:"Coin",render:(r:Row)=><button className="coin-text-button" onClick={()=>selectCoin(r.symbol,true)}>{r.symbol} <ArrowUpRight size={13}/></button>},
        {label:"Quantity",render:(r:Row)=>Number(r.quantity).toLocaleString(undefined,{maximumSignificantDigits:8})},
        {label:"Cost",render:(r:Row)=>money(r.cost_basis_eur)},
        {label:"Value",render:(r:Row)=>money(r.market_value_eur)},
        {label:"Unrealized P&L",render:(r:Row)=><Pnl value={r.unrealized_pnl_eur}/>},
      ]}/><p className="small muted">Values use fresh observed midpoint marks. Missing or stale marks show as unavailable.</p></Panel>
      <Panel><div className="section-heading"><h2>Account results</h2><Badge>{p?.risk_state ?? "Checking"}</Badge></div><dl className="dashboard-results">
        <div><dt>Realized P&L</dt><dd><Pnl value={p?.realized_pnl}/></dd></div><div><dt>Unrealized P&L</dt><dd><Pnl value={p?.unrealized_pnl}/></dd></div><div><dt>Received from sells</dt><dd>{money(d?.cash_flow?.sale_proceeds_eur)}</dd></div><div><dt>Completed positions</dt><dd>{d?.performance?.closed_positions ?? "—"}</dd></div><div><dt>Drawdown</dt><dd>{percent(p?.current_drawdown)}</dd></div><div><dt>Reconciliation</dt><dd>{d?.reconciliation?.length === 0 ? "Passed" : "Checking"}</dd></div>
      </dl></Panel>
    </div>
    <TradeReports rows={d?.trade_reports}/>
    {d && p && <TraderLive paper={d} onSelectCoin={coin=>selectCoin(coin,true)}/>}
    <Panel><div className="section-heading"><h2>What you bought and sold</h2><span className="small muted">Actual paper fills</span></div><CompactTable label="Dashboard filled trades" rows={d?.fills ?? []} empty={<Empty title="No filled trades yet">The live trader explains why each candidate was bought or left waiting. An order becomes a purchase only when it fills.</Empty>} columns={[
      {label:"Coin",render:(r:Row)=><button className="coin-text-button" onClick={()=>selectCoin(r.symbol,true)}>{r.symbol} <ArrowUpRight size={13}/></button>},
      {label:"Action",render:(r:Row)=><span className={`fill-direction ${r.side==="BUY" ? "gain" : "muted"}`}>{r.side==="BUY" ? <ArrowDownLeft size={14}/> : <ArrowUpRight size={14}/>} {r.side==="BUY" ? "Bought" : "Sold"}</span>},
      {label:"Quantity",render:(r:Row)=>r.quantity},{label:"Price",render:(r:Row)=>price(r.price)},{label:"Fee",render:(r:Row)=>money(r.fee)},
      {label:"Time",render:(r:Row)=>date(r.timestamp ?? r.created_at,true)},
    ]}/><p className="small muted">Latest 80 fills shown. Spending, proceeds and fee totals include the complete ledger. This dashboard uses the single €7,000 primary paper account.</p></Panel>
  </div>;
}
