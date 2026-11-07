import { useMemo, useState } from "react";
import { Activity, BarChart3, Database, Lock, Pause, Play, RefreshCcw, ShieldCheck, TrendingUp, Wallet } from "lucide-react";
import { useApi, useResource } from "./api";
import "./AlpacaCrypto.css";

type Row = Record<string, any>;
function n(x: unknown):number{return Number.isFinite(Number(x))?Number(x):0;}
function fmt(x:unknown):string{return n(x).toLocaleString("en-US");}
function price(x:unknown):string{return x==null?"—":new Intl.NumberFormat("en-US",{style:"currency",currency:"USD",maximumFractionDigits:5}).format(n(x));}
function when(s:unknown):string{if(typeof s!=="string")return "—";const d=new Date(s);return Number.isFinite(d.getTime())?d.toLocaleString():"—";}
const order=["BTC/USD","ETH/USD","SOL/USD","AVAX/USD","LINK/USD","LTC/USD","BCH/USD","DOGE/USD","UNI/USD","AAVE/USD"];

export function AlpacaCrypto(){
 const api=useApi();
 const response=useResource("/api/stockswatch/alpaca-crypto",{poll:15000,ttl:7000});
 const [filter,setFilter]=useState("");
 const [working,setWorking]=useState(false);
 const [notice,setNotice]=useState("");
 const d:Row=response.data??{};
 const assets:Row[]=Array.isArray(d.assets)?d.assets:[];
 const signals:Row[]=Array.isArray(d.signals)?d.signals:[];
 const managed:Row[]=Array.isArray(d.managed)?d.managed:[];
 const intents:Row[]=Array.isArray(d.intents)?d.intents:[];
 const historyJobs:Row[]=Array.isArray(d.history_jobs)?d.history_jobs:[];
 const historyBars:Row[]=Array.isArray(d.history_bars)?d.history_bars:[];
 const completed=historyJobs.filter(j=>j.state==="COMPLETE").reduce((s,j)=>s+n(j.n),0);
 const total=historyJobs.reduce((s,j)=>s+n(j.n),0);
 const pct=total?Math.min(100,100*completed/total):0;
 const rows=useMemo(()=>order.filter(symbol=>symbol.toLowerCase().includes(filter.trim().toLowerCase())).map(symbol=>({
  symbol,asset:assets.find(a=>a.symbol===symbol)??{},signal:signals.find(s=>s.symbol===symbol)??{},
  managed:managed.find(m=>m.symbol===symbol),
 })),[assets,signals,managed,filter]);
 async function control(action:"pause"|"resume"){
  if(working)return;setWorking(true);setNotice("");
  try{
   await api.request("/api/stockswatch/alpaca-crypto/control","POST",{action});
   await api.refresh("/api/stockswatch/alpaca-crypto");
   setNotice(action==="pause"?"Crypto paper order admission paused. Existing broker orders are not canceled.":"Crypto paper order admission resumed.");
  }catch(e){setNotice("Control action was not confirmed. Crypto paper orders remain guarded by server settings.");}
  finally{setWorking(false);}
 }
 return <div className="ac-root">
  <section className="ac-hero">
   <div className="ac-label"><Activity size={16}/> ALPACA CRYPTO · SPOT RESEARCH · 24/7</div>
   <h2>AlpacaCrypto</h2>
   <p>Independent crypto research and long-only Alpaca Paper execution. Historical market bars are quote midpoints, not executable prices. This dashboard does not operate the legacy crypto engine.</p>
   <div className="ac-flags"><span><ShieldCheck size={14}/> Paper only</span><span><Lock size={14}/> No leverage</span><span><TrendingUp size={14}/> LONG / FLAT only</span><span>SHORT unsupported by Alpaca</span></div>
  </section>
  {response.error&&<div className="ac-warning" role="alert">AlpacaCrypto API unavailable. No trading state is assumed.</div>}
  <section className="ac-stats">
   <article><Database size={18}/><small>Downloaded historical bars</small><b>{fmt(historyBars.reduce((sum,r)=>sum+n(r.n),0))}</b></article>
   <article><BarChart3 size={18}/><small>Backfill jobs</small><b>{fmt(completed)} / {fmt(total)}</b></article>
   <article><ShieldCheck size={18}/><small>Eligible broker pairs</small><b>{fmt(assets.filter(a=>a.eligible===1).length)} / 10</b></article>
   <article><Wallet size={18}/><small>Managed spot positions</small><b>{fmt(managed.length)}</b></article>
  </section>
  <section className="ac-panel">
   <div className="ac-heading"><div><h3>History and execution gates</h3><p>Data collection is separate from order authorization and risk checks.</p></div><button onClick={()=>void api.refresh("/api/stockswatch/alpaca-crypto")}><RefreshCcw size={15}/> Refresh</button></div>
   <div className="ac-progress"><div style={{width:`${pct}%`}}/></div>
   <div className="ac-grid">
    <div><small>Job completion</small><b>{pct.toFixed(1)}%</b></div>
    <div><small>Daily bars</small><b>{fmt(historyBars.find(x=>x.timeframe==="1Day")?.n)}</b></div>
    <div><small>Hourly bars</small><b>{fmt(historyBars.find(x=>x.timeframe==="1Hour")?.n)}</b></div>
    <div><small>Signal update</small><b>{when(d.last_cycle)}</b></div>
   </div>
   <div className="ac-control">
    <div><strong>{d.paper_orders_enabled?(d.paused?"Paper orders paused":"Paper orders enabled"):"Research only · crypto orders disabled"}</strong><small>Separate Alpaca Paper account required for order submission. Legacy stock account and ledger are not shared.</small></div>
    <div className="ac-buttons"><button disabled={working||d.paused!==false} onClick={()=>void control("pause")}><Pause size={14}/> Pause</button><button disabled={working||!d.paper_orders_enabled||!d.paused} onClick={()=>void control("resume")}><Play size={14}/> Resume</button></div>
   </div>
   {d.last_error&&<p className="ac-warning">Last diagnostic: {String(d.last_error)}</p>}
   {notice&&<p role="status" className="ac-note">{notice}</p>}
  </section>
  <section className="ac-panel">
   <div className="ac-heading"><div><h3>Spot market scanner</h3><p>Completed hourly breakout and daily regime checks. No guarantee of profit.</p></div><input aria-label="Filter crypto pairs" placeholder="Search BTC, ETH…" value={filter} onChange={e=>setFilter(e.target.value)}/></div>
   <div className="ac-table-scroll"><table><thead><tr><th>Pair</th><th>Data eligibility</th><th>Last hourly bar</th><th>Action</th><th>Latest evidence</th><th>Price (USD)</th><th>Software stop</th><th>Target</th></tr></thead>
   <tbody>{rows.map(({symbol,asset,signal,managed})=><tr key={symbol}><td><strong>{symbol}</strong>{managed&&<span className="ac-owned"> OWNED</span>}</td><td>{asset.eligible===1?"Verified":asset.reason||"Pending"}</td><td>{when(asset.latest_hour)}</td><td><span className={`ac-action ac-${String(signal.action||"WAIT").toLowerCase()}`}>{signal.action||"WAIT"}</span></td><td>{signal.reason||"Awaiting completed history"}</td><td>{price(signal.price)}</td><td>{price(managed?.stop??signal.stop)}</td><td>{price(managed?.target??signal.target)}</td></tr>)}</tbody></table></div>
  </section>
  <section className="ac-panel">
   <div className="ac-heading"><div><h3>Broker order journal</h3><p>Only AlpacaCrypto-owned paper intents; never the stock or legacy crypto ledger.</p></div></div>
   <div className="ac-table-scroll"><table><thead><tr><th>Created</th><th>Pair</th><th>Side</th><th>State</th><th>Broker status</th><th>Notional / quantity</th></tr></thead><tbody>{intents.length?intents.map(x=><tr key={x.client_id}><td>{when(x.created_at)}</td><td>{x.symbol}</td><td>{String(x.side).toUpperCase()}</td><td>{x.state}</td><td>{x.broker_status||"—"}</td><td>{x.notional?price(x.notional):x.qty||"—"}</td></tr>):<tr><td colSpan={6} className="ac-empty">No submitted AlpacaCrypto orders yet.</td></tr>}</tbody></table></div>
   <p className="ac-footnote">Alpaca crypto does not offer short selling. Stops and targets here are software-managed checks using fresh quotes, not guaranteed broker stop executions. Paper fills can differ from live trading.</p>
  </section>
 </div>;
}
