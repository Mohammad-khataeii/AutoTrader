import { useResource } from "./api";
import { ShieldCheck, ShieldAlert, TrendingUp } from "lucide-react";

type Row=Record<string,any>;
const money=(v:unknown)=>v==null?"—":new Intl.NumberFormat("en-US",{style:"currency",currency:"USD",maximumFractionDigits:2}).format(Number(v));
const text=(v:unknown)=>v==null?"—":String(v).replace(/_/g," ");
export function StocksWatchProtection(){
 const response=useResource("/api/stockswatch/profit-protection",{poll:15000,ttl:8000});
 const d:Row=response.data??{};
 const positions:Row[]=Array.isArray(d.positions)?d.positions:[];
 return <div className="sw-detail-grid" aria-label="StocksWatch profit and stop protection">
  <article className="sw-panel sw-span2">
   <div className="sw-heading"><div className="sw-heading-icon"><ShieldCheck size={19}/></div><div><h3>Broker take-profit and rising stop-loss</h3><p>ATR14 risk, fixed 2.5R target, monotone profit-lock; Alpaca Paper only.</p></div></div>
   <p className="sw-warning">{d.configured_for_paper_orders
    ?"OCO protection is configured for PAPER orders; confirm the verified broker status of EACH position below."
    :"Observation only. Targets and stop suggestions shown below are NOT active broker orders. Existing positions are not protected by this proposal."}</p>
   {response.error&&<p role="alert" className="sw-warning">Could not verify broker protection. No protection is assumed.</p>}
   {positions.length?<div className="sw-table-scroll"><table className="sw-table">
    <thead><tr><th>Stock</th><th>Entry / quantity</th><th>Initial SL</th><th>Broker SL</th><th>Take profit</th><th>Peak verified price</th><th>Profit at trigger</th><th>Proof</th></tr></thead>
    <tbody>{positions.map((p:Row,i:number)=><tr key={String(p.symbol)+i}>
      <td><b>{text(p.symbol)}</b></td>
      <td>{p.entry!=null?<>{money(p.entry)} · {text(p.qty)} shares</>:"—"}</td>
      <td>{money(p.initial_stop)}</td>
      <td><b>{p.verified_broker_stop!=null?money(p.verified_broker_stop):"NOT VERIFIED"}</b></td>
      <td>{money(p.target)}</td>
      <td>{money(p.highwater)}</td>
      <td>{p.verified_broker_stop!=null?money(p.trigger_profit_usd):"—"}</td>
      <td><small>{text(p.broker_state)} · {text(p.reason)}</small></td>
     </tr>)}</tbody></table></div>
     : <p>No verified Alpaca Paper EOD positions were available in the latest protection scan.</p>}
   <div className="sw-intel-row"><span><TrendingUp size={16}/> Policy</span><strong>Initial 3–8% volatility risk; TP 2.5× risk</strong></div>
   <div className="sw-intel-row"><span>Progressive profit lock</span><strong>40% / 60% / 80% / 90% of TP</strong></div>
   <div className="sw-intel-row"><span>Last broker monitor</span><strong>{d.at?new Date(d.at).toLocaleString():"Unavailable"}</strong></div>
   <p className="sw-risk-label"><ShieldAlert size={15}/> Raising a stop changes the trigger, not a guaranteed fill. Native stop-market execution occurs only during regular stock-market hours. Stop orders may fill below the trigger after a gap.</p>
   <p><small>Risk rule: At 80% of the original TP distance, the minimum lock is 60% of the highest observed unrealized profit, subject to broker price clearance and valid quotes. No automatic stop lowering or uncertain order retries.</small></p>
   <p><small>Pre-existing EOD strategy exits cannot also place a second sell while OCO orders reserve the position. These orders must be reconciled before any change in exit authority.</small></p>
  </article>
 </div>;
}
