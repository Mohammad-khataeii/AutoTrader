import { useMemo, useState } from "react";
import { Activity, ArrowDownRight, ArrowUpRight, BarChart3, BrainCircuit, Database, ExternalLink, Flame, Gauge, Info, LineChart as LineIcon, Newspaper, Pause, Play, RefreshCw, ShieldAlert, ShieldCheck, TrendingUp, Wallet } from "lucide-react";
import { ResponsiveContainer, AreaChart, Area, Line, CartesianGrid, Tooltip, XAxis, YAxis, Legend } from "recharts";
import { useApi, useResource } from "./api";
import { ScannerMonitor } from "./ScannerMonitor";
import "./StocksWatch.css";

type Row = Record<string, any>;
function n(value: unknown): number { const x = Number(value); return Number.isFinite(x) ? x : 0; }
function cash(v: unknown): string {return new Intl.NumberFormat("en-US", { style: "currency", currency: "USD", maximumFractionDigits: 2 }).format(n(v));}
function pct(v: unknown): string {return `${n(v) > 0 ? "+" : ""}${n(v).toFixed(2)}%`;}
function val(v: unknown): string {return v == null || v === "" ? "—" : String(v);}
function fromUTC(s: string | null | undefined): string {if(!s) return "—"; const d=new Date(s);return Number.isNaN(d.getTime())?s: d.toLocaleString(undefined,{month:"short",day:"numeric",hour:"2-digit",minute:"2-digit"});}
function elapsed(s?:string):string {
  const created=s?Date.parse(s):NaN;
  if (!Number.isFinite(created)) return "age unavailable";
  const mins=Math.max(0,Math.floor((Date.now()-created)/60000));
  return mins>=60?`${Math.floor(mins/60)}h ${mins%60}m`:`${mins}m`;
}
function Metric({ label, value, note, tone, icon: Icon }: {label:string,value:string,note?:string,tone?:string,icon:any}) {
  return <article className={`sw-metric ${tone??""}`}><div className="sw-metric-heading"><span>{label}</span><Icon size={18}/></div><strong>{value}</strong><small>{note || ""}</small></article>;
}
function Status({ value }: {value:string}){return <span className={`sw-state sw-${value.toLowerCase().replace(/[^a-z]+/g,"-")}`}>{value.replace(/_/g," ")}</span>;}
function Header({ icon:Icon, title, note }: {icon:any,title:string,note?:string}) {return <div className="sw-heading"><div className="sw-heading-icon"><Icon size={19}/></div><div><h3>{title}</h3>{note && <p>{note}</p>}</div></div>;}
function Blank({text}:{text:string}) {return <div className="sw-blank"><Info size={20}/>{text}</div>}

export function StocksWatch(){
 const api = useApi();
 const resource=useResource("/api/stockswatch/dashboard",{poll:30000});
 const health=useResource("/api/stockswatch/status",{poll:30000});
 const [tab,setTab]=useState<"Signals"|"Portfolio"|"Research"|"Catalysts">("Signals");
 const [busy,setBusy]=useState(false);
 const [notice,setNotice]=useState("");
 const [ticker,setTicker]=useState("");
 const d:Row=resource.data??{};
 const h:Row=health.data??{};
 const isBroker=h.mode==="ALPACA_PAPER" || d.execution_mode==="ALPACA_PAPER";
 const a:Row=isBroker && !d.broker_account?{}:(d.account??{});
 const brokerReadOnly=isBroker && !d.broker_account?.order_submission_enabled;
 const positions:Row[]=Array.isArray(d.positions)?d.positions:[];
 const signals:Row[]=Array.isArray(d.signals)?d.signals:[];
 const visible=useMemo(()=>signals.filter(s=>`${s.symbol} ${s.name} ${s.sector}`.toLowerCase().includes(ticker.trim().toLowerCase())),[signals,ticker]);
 const curve:Row[]=Array.isArray(d.equity_curve)?d.equity_curve:[];
 const firstBenchmark=n(curve.find(point=>n(point.spy_close)>0)?.spy_close);
 const graph=curve.map(x=>({day:x.day,Portfolio:n(x.equity),"SPY baseline":firstBenchmark&&n(x.spy_close)?n(a.initial_cash)*n(x.spy_close)/firstBenchmark:null}));
 const source=(h.provider??"Not configured").toString();
 const status=(d.status?.state??"WAITING_FOR_DATA").toString();
 const paper:Row=d.status?.paper??{};
 const gates:Row[]=(paper.why_no_trade??[]).filter((row:Row)=>
   String(row.symbol).toLowerCase().includes(ticker.trim().toLowerCase()));
 const holdout=d.historical_comparison?.segments?.holdout;
 async function control(action:"pause"|"resume"){
   if(busy)return;setBusy(true);setNotice("");
   try {await api.request("/api/stockswatch/control","POST",{action}); await Promise.all([api.refresh("/api/stockswatch/dashboard"),api.refresh("/api/stockswatch/status")]);setNotice(isBroker&&action==="resume"&&brokerReadOnly?"Alpaca paper orders remain disabled in server configuration.":action==="pause"?"StocksWatch automated new orders paused.":"StocksWatch automated paper order admission resumed.");}
   catch {setNotice("Action was not confirmed. Please check the service status.");}
   finally {setBusy(false);}
 }
 return <div className="sw-root" data-swatch="stockswatch-v1">
  <section className="sw-hero">
   <div className="sw-hero-main"><div className="sw-eyebrow"><span className="sw-led"/> US EQUITIES LAB <span className="sw-hero-sep">/</span> AUTONOMOUS PAPER RESEARCH</div>
     <h2>Invest with evidence.<br/><span>Learn from every market cycle.</span></h2>
     <p>{isBroker?"Connected to Alpaca Paper Trading: balances, holdings and fills are broker-sourced. Orders use virtual money only.":"Market prices, filings, quantitative signals and bounded AI research. A separate virtual account—never a real-money trading connection."}</p>
     <div className="sw-hero-tags"><Status value={isBroker?"ALPACA PAPER":"LOCAL PAPER"}/>{brokerReadOnly&&<Status value="ORDERS DISABLED"/>}<Status value={status}/><span className="sw-subtle">{source} · EOD_ONLY</span></div>
   </div>
   <div className="sw-hero-right"><div className="sw-portfolio-label">{isBroker?"ALPACA PAPER EQUITY":"STOCKSWATCH PORTFOLIO"}</div><strong>{a.equity==null?"—":cash(a.equity)}</strong><div className={n(a.pnl)>=0?"sw-up":"sw-down"}>{n(a.pnl)>=0?<ArrowUpRight size={17}/>:<ArrowDownRight size={17}/>} {a.pnl==null?"—":pct(a.pnl_pct)} <span>{a.pnl==null?"—":cash(a.pnl)} {isBroker?"today":"all time"}</span></div><small>{isBroker?`Paper account ${d.broker_account?.masked??"unavailable"} · cash ${a.cash==null?"—":cash(a.cash)}`:`Starting balance ${cash(a.initial_cash)}`}</small></div>
  </section>
  {(resource.error || health.error || h.broker_connection?.broker==="DISCONNECTED") && <p className="sw-warning" role="alert">{isBroker?"Alpaca Paper is unavailable or account verification failed. No local balances or fills are substituted. ":"StocksWatch service is unavailable or the data is stale. Existing crypto monitoring continues independently. "}{resource.error || health.error || h.broker_connection?.reason}</p>}
  {notice && <p className="sw-notice" role="status">{notice}</p>}
  <ScannerMonitor/>
  <article className="sw-panel sw-execution-summary">
    <Header icon={Activity} title="Decision funnel" note={`Market day ${val(paper.market_day)} · ${fromUTC(paper.at)}`}/>
    <div className="sw-funnel">{Object.entries(paper.funnel??{}).map(([key,count])=>
      <div className="sw-intel-row" key={key}><span>{key.replace(/_/g," ")}</span><strong>{n(count)}</strong></div>)}</div>
    {(d.status?.reason || paper.reason || paper.entry_gate) && <p className="sw-warning">
      {val(d.status?.reason??paper.reason??paper.entry_gate).replace(/_/g," ")}</p>}
    <small>Latest BUY fill {fromUTC(d.last_fill?.last_buy)} · Latest SELL fill {fromUTC(d.last_fill?.last_sell)}</small>
  </article>
  <section className="sw-metrics">
   <Metric icon={Wallet} label="Available cash" value={a.cash==null?"—":cash(a.cash)} note={isBroker?`Alpaca paper buying power ${a.buying_power==null?"—":cash(a.buying_power)} (not available cash)`:"Uncommitted virtual USD"}/>
   <Metric icon={LineIcon} label="Virtual exposure" value={a.exposure==null?"—":cash(a.exposure)} note={`${positions.length} ${isBroker?"broker positions":"of 5 position slots used"}`}/>
   <Metric icon={TrendingUp} label={isBroker?"Unrealized P&L":"Realized P&L"} value={isBroker?cash(a.unrealized):cash(a.realized)} note={isBroker?"Based on open Alpaca paper positions":`${cash(a.unrealized)} unrealized`} tone={n(isBroker?a.unrealized:a.realized)<0?"sw-bad":"sw-good"}/>
   <Metric icon={ShieldCheck} label={isBroker?"Recent drawdown":"Drawdown"} value={a.drawdown_pct==null?"—":pct(-n(a.drawdown_pct))} note={isBroker?"Approximate from available broker history":"Safety pause at 12%"} tone={n(a.drawdown_pct)>=10?"sw-bad":""}/>
  </section>
  <section className="sw-mid-grid">
   <article className="sw-panel sw-equity-panel"><div className="sw-panel-top"><Header icon={BarChart3} title="Equity performance" note={isBroker?"Alpaca Paper portfolio history, directly from broker":"Virtual equity compared with SPY, aligned to available EOD history"}/><div className="sw-small-tag">{isBroker?"Alpaca virtual funds":"No live market execution"}</div></div>
     {graph.length>=2 ? <div className="sw-chart"><ResponsiveContainer width="100%" height="100%"><AreaChart data={graph} margin={{top:10,right:10,left:0,bottom:0}}><defs><linearGradient id="swblue" x1="0" y1="0" x2="0" y2="1"><stop offset="0%" stopColor="#5c8ef1" stopOpacity={.32}/><stop offset="100%" stopColor="#5c8ef1" stopOpacity={0}/></linearGradient></defs><CartesianGrid vertical={false} stroke="var(--sw-grid)" strokeDasharray="3 5"/><XAxis dataKey="day" tick={{fill:"var(--sw-muted)",fontSize:10}} tickLine={false} axisLine={false} minTickGap={30}/><YAxis tickFormatter={(v:number)=>`$${Math.round(v/1000)}k`} tick={{fill:"var(--sw-muted)",fontSize:11}} width={46} tickLine={false} axisLine={false} domain={["auto","auto"]}/><Tooltip formatter={(v:any)=>cash(v)} contentStyle={{background:"var(--sw-card)",border:"1px solid var(--sw-border)",borderRadius:12,color:"var(--sw-ink)"}}/><Legend wrapperStyle={{fontSize:11}}/><Area type="monotone" name="Portfolio" dataKey="Portfolio" stroke="#548dfb" strokeWidth={2.5} fill="url(#swblue)" connectNulls={false}/><Line type="monotone" name="SPY baseline" dataKey="SPY baseline" dot={false} stroke="#e9a54c" strokeWidth={1.8} strokeDasharray="5 4" connectNulls={false}/></AreaChart></ResponsiveContainer></div> : <Blank text="The equity chart will populate after the first completed daily research and valuation cycle."/>}
   </article>
   <article className="sw-panel sw-state-panel"><Header icon={Gauge} title="Market intelligence" note="Always-on analysis with evidence and risk gates"/>
      <div className="sw-intel-row"><span>Execution mode</span><strong>{isBroker?"Alpaca broker paper orders":d.execution_mode === "EOD_OBSERVED_PAPER" ? "Observed daily close" : "Legacy daily paper mode"}</strong></div>
      <div className="sw-intel-row"><span>Strategy regime</span><strong>{val(d.signals?.[0]?.regime ?? "AWAITING HISTORY")}</strong></div>
      <div className="sw-intel-row"><span>AI interpretation</span><strong>{val(d.status?.components?.gemini)} · advisory only</strong></div>
      <div className="sw-intel-row"><span>Price feed</span><strong>{source}</strong></div>
      {isBroker&&<div className="sw-intel-row"><span>Paper account</span><strong>{d.broker_account?.masked??"unavailable"} · {brokerReadOnly?"Orders disabled":"Orders enabled"}</strong></div>}
      <div className="sw-intel-row"><span>Last research run</span><strong>{fromUTC(d.research?.created_at)}</strong></div>
      <details className="sw-disclosure"><summary>Component health</summary>
        {Object.entries(d.status?.components??{}).map(([name,state])=><div className="sw-intel-row" key={name}><span>{name.replace(/_/g," ")}</span><strong>{val(state)}</strong></div>)}
        <div className="sw-intel-row"><span>Last completed cycle</span><strong>{fromUTC(d.status?.completed_at)}</strong></div>
        <div className="sw-intel-row"><span>Next core session opens</span><strong>{fromUTC(paper.next_core_open)}</strong></div>
      </details>
      <div className="sw-risk-label"><span>Portfolio capital at risk</span><strong>{pct(n(a.initial_cash)?(n(a.exposure)/n(a.equity))*100:0)}</strong></div>
      <div className="sw-risk-track"><div style={{width:`${Math.min(100,100*n(a.exposure)/Math.max(1,n(a.equity)))}%`}}/></div>
      <div className="sw-actionline"><button disabled={busy||!d.account} onClick={()=>control(a.paused?"resume":"pause")}>{a.paused?<Play size={16}/>:<Pause size={16}/>} {a.paused?"Resume paper orders":"Pause new paper orders"}</button><span>{isBroker?"Only affects StocksWatch automated Alpaca paper orders, not orders placed manually in Alpaca.":"Trade controls affect StocksWatch only."}</span></div>
   </article>
  </section>
  <section className="sw-nav" role="tablist" aria-label="StocksWatch details">
   {(["Signals","Portfolio","Research","Catalysts"] as const).map(t=><button key={t} role="tab" aria-selected={tab===t} className={tab===t?"active":""} onClick={()=>setTab(t)}>{t}</button>)}
   <button className="sw-refresh" title="Refresh StocksWatch data" onClick={()=>{void api.refresh("/api/stockswatch/dashboard");void api.refresh("/api/stockswatch/status");}}><RefreshCw size={15}/></button>
  </section>
  {tab==="Signals" && <div className="sw-detail-grid"><article className="sw-panel sw-span2"><div className="sw-panel-top"><Header icon={Flame} title="Ranked market candidates" note="Deterministic multi-strategy score; only completed daily observations"/><input aria-label="Filter stocks" placeholder="Search ticker, company or sector" value={ticker} onChange={e=>setTicker(e.target.value)}/></div>
   {visible.length ? <div className="sw-table-scroll"><table className="sw-table"><thead><tr><th>Company</th><th>Model score</th><th>Signals</th><th>Regime</th><th>Decision</th></tr></thead><tbody>{visible.map((s,i)=><tr key={s.symbol+i}><td><strong>{s.symbol}</strong><small>{s.name}</small></td><td><span className="sw-score">{n(s.score).toFixed(2)}</span></td><td>{Object.entries(s.signals??{}).filter(([,v])=>v).slice(0,3).map(([k])=><span className="sw-mini" key={k}>{k.replace(/_/g," ")}</span>)}</td><td>{val(s.regime)}</td><td><Status value={s.action??"WATCH"}/></td></tr>)}</tbody></table></div> : <Blank text="No qualified candidates yet. Backfill must complete and SPY history must establish the market regime."/>}
   <details className="sw-disclosure"><summary>Why each stock did or did not trade</summary>
     {gates.length ? gates.map(s=><div className="sw-reason" key={s.symbol}><b>{s.symbol} · {s.action}</b><p>{val(s.reason).replace(/_/g," ")} · observed {fromUTC(s.observed_at)}</p></div>)
       : <Blank text="No execution gate observations for this filter."/>}
   </details></article></div>}
  {tab==="Portfolio" && <div className="sw-detail-grid"><article className="sw-panel"><Header icon={Wallet} title="Open virtual positions" note="Position-level P&L and EOD stop reference"/>{positions.length ? positions.map(p=><div className="sw-position" key={p.symbol}><div><b>{p.symbol}</b><small>{p.sector} · {p.qty} shares</small></div><div><b className={n(p.unrealized)>=0?"sw-up":"sw-down"}>{cash(p.unrealized)}</b><small>{cash(p.mark)}{p.stop!=null?` · Stop ${cash(p.stop)}`:" · No broker stop placed"}</small></div></div>):<Blank text={isBroker?"No Alpaca paper positions are currently open.":"No open stock positions. New orders require validated EOD signals and the next completed session."}/>}</article>
     <article className="sw-panel"><Header icon={Activity} title="Pending paper orders" note={isBroker?"Orders returned by Alpaca Paper Trading API":"Awaiting the next eligible daily observation"}/>
       {(d.pending_orders??[]).map((o:Row)=><div className="sw-position" key={`${o.symbol}-${o.signal_day}`}><div><b>{o.symbol} · {o.side}</b>
         <small>Queued {fromUTC(o.created_at)} · {elapsed(o.created_at)}{isBroker?` · Filled ${val(o.filled_qty)} / ${val(o.qty)}`:` · Target ${val(o.target_day)}`}</small>
         {paper.order_checks?.[o.id] && <small>{String(paper.order_checks[o.id]).replace(/_/g," ")}</small>}
         </div><Status value={o.state}/></div>)}
       {!d.pending_orders?.length && <Blank text="No pending paper orders."/>}
       <details className="sw-disclosure"><summary>Completed order outcomes</summary>{(d.order_history??[]).map((o:Row,i:number)=>
         <div className="sw-reason" key={i}><b>{o.symbol} · {o.state}</b><p>{val(o.reason).replace(/_/g," ")} · {fromUTC(o.recorded_at)}</p></div>)}</details>
     </article>
     <article className="sw-panel"><Header icon={Activity} title="Actual virtual fills" note={isBroker?"Confirmed Alpaca paper fill activities, never simulated locally":"Daily close plus modeled execution cost. Fill time follows observation."}/>
       {(d.fills??[]).slice(0,20).map((f:Row,i:number)=><div className="sw-position" key={i}><div><b>{f.symbol} · {f.side}</b>
         <small>{f.qty} shares · filled {fromUTC(f.created_at)}</small>
         <small>{isBroker?"ALPACA PAPER · broker-confirmed":f.evidence?.mode ? `${f.source} · observed ${fromUTC(f.evidence.observed_at)}` : "Legacy fill · observation evidence unavailable"}</small>
         </div><div><b>{cash(f.price)}</b><small>{isBroker?"Confirmed paper fill":`${cash(f.realized)} realized · ${cash(f.fee)} fee`}</small></div></div>)}
       {!d.fills?.length && <Blank text="No completed virtual fills yet."/>}
     </article>
     <article className="sw-panel"><Header icon={Database} title="Observed prices" note="Certified daily observations used by the paper engine"/>
       {(d.price_updates??[]).slice(0,12).map((b:Row)=><div className="sw-position" key={`${b.symbol}-${b.day}`}><div><b>{b.symbol} · {b.day}</b>
         <small>{b.source} · {fromUTC(b.observed_at)}</small></div><b>{cash(b.c)}</b></div>)}
       {!d.price_updates?.length && <Blank text="No certified EOD observations yet."/>}
     </article></div>}
  {tab==="Research" && <div className="sw-detail-grid"><article className="sw-panel"><Header icon={Database} title="Historical research database" note="Actual observations, provenance and universe limitations"/><div className="sw-research-count"><strong>{(d.coverage??[]).reduce((s:number,r:Row)=>s+n(r.bars),0).toLocaleString()}</strong><span>stored stock-day bars</span></div><div className="sw-table-scroll"><table className="sw-table"><thead><tr><th>Symbol</th><th>History</th><th>Latest session</th></tr></thead><tbody>{(d.coverage??[]).map((r:Row)=><tr key={r.symbol}><td>{r.symbol}</td><td>{n(r.bars).toLocaleString()}</td><td>{val(r.last_day)}</td></tr>)}</tbody></table></div></article><article className="sw-panel"><Header icon={BrainCircuit} title="Strategy & ML comparison" note="HISTORICAL_REPLAY · research only"/><div className="sw-intel-row"><span>Historical replay</span><Status value={val(d.research?.status)}/></div><div className="sw-intel-row"><span>Completed backtests</span><strong>{n(d.research?.total_backtests)}</strong></div><div className="sw-intel-row"><span>ML challenger</span><Status value={val(d.ml?.status)}/></div>{Object.entries(d.research?.by_strategy??{}).map(([strategy,s])=><div className="sw-research-strategy" key={strategy}><div><b>{strategy.replace(/_/g," ")}</b><small>{n((s as Row).count)} symbols</small></div><strong>{(s as Row).mean_return_pct == null?"Unavailable":pct((s as Row).mean_return_pct)}</strong></div>)}{holdout && <details className="sw-disclosure"><summary>Offline challenger holdout · {holdout.start_day} to {holdout.end_day}</summary>
      <p>SPY {pct(holdout.spy_return_pct)} · 12 basis points modeled per side</p>
      <div className="sw-table-scroll"><table className="sw-table"><thead><tr><th>Policy</th><th>Return</th><th>Drawdown</th><th>Closed trades</th></tr></thead>
      <tbody>{Object.entries(holdout.strategies??{}).map(([mode,costs])=>{
        const m=(costs as Row)["12"]; return <tr key={mode}><td>{mode.replace(/_/g," ")}</td><td>{pct(m.return_pct)}</td><td>{pct(-m.max_drawdown_pct)}</td><td>{m.closed_trades}</td></tr>;
      })}</tbody></table></div>
      {(d.historical_comparison?.limitations??[]).map((w:string)=><p key={w}>{w}</p>)}
      <p>Earnings surprise study · {val(d.historical_comparison?.event_catalysts)}</p>
      </details>}<details className="sw-disclosure"><summary>Research limitations and model evidence</summary><div className="sw-notes">{(d.research?.warnings??[]).map((w:string,i:number)=><p key={i}>{w}</p>)}<p>Model Brier: {d.ml?.brier??"Not evaluated"}; null Brier: {d.ml?.no_skill_brier??"Not evaluated"}. ML trading authority: disabled.</p></div></details></article></div>}
  {tab==="Catalysts" && <div className="sw-detail-grid"><article className="sw-panel"><Header icon={Newspaper} title="SEC filings & announcements" note="Official source links; timestamps retained for time-of-knowledge controls"/>{(d.filings??[]).length ? (d.filings??[]).map((f:Row,i:number)=><div key={i} className="sw-filing"><span className="sw-mini">{f.form}</span><div><b>{f.symbol}</b><p>{f.description||"Official SEC filing"}</p><small>{fromUTC(f.accepted_at)}</small></div><a href={f.url} target="_blank" rel="noopener noreferrer" title="Open SEC filing"><ExternalLink size={15}/></a></div>):<Blank text="SEC integration requires a contact User-Agent; no filing claims are invented."/>}</article><article className="sw-panel"><Header icon={BrainCircuit} title="AI & macro research" note="AI explanations use sourced SEC evidence only; not trading instructions"/>{(d.ai_insights??[]).length?(d.ai_insights??[]).map((x:Row,i:number)=><div className="sw-ai-note" key={i}><b>{x.symbol} · {x.model}</b><p>{x.analysis?.summary}</p><small>{fromUTC(x.generated_at)} · <a href={x.source_url} target="_blank" rel="noopener noreferrer">Official filing</a></small></div>):<Blank text="AI waits for new official filings and shared Gemini quota. It does not control orders."/>}<div className="sw-macro-title">Current macro observations <small>Not backtest vintages</small></div>{(d.macro??[]).slice(0,6).map((m:Row,i:number)=><div className="sw-intel-row" key={i}><span>{m.series} · {m.observation_day}</span><strong>{m.value}</strong></div>)}<div className="sw-macro-title">Company financial facts <small>Official SEC XBRL · publication dated</small></div>{(d.fundamentals??[]).slice(0,10).map((f:Row,i:number)=><div className="sw-intel-row" key={"fund-"+i}><span>{f.symbol} · {f.tag} · {f.end_day}</span><strong>{f.unit==="USD"?cash(f.value):val(f.value)} <a href={f.source_url} target="_blank" rel="noopener noreferrer" aria-label="Open official SEC company facts"><ExternalLink size={12}/></a></strong></div>)}</article></div>}
  <footer className="sw-footer"><ShieldAlert size={15}/> {isBroker?"Connected only to Alpaca Paper Trading. Real-money execution is impossible from this adapter. EOD orders are not protected by intraday stops. Local legacy orders remain separate.":"Paper-only. No broker integration."} Free EOD data may be delayed or corporate-action incomplete. ML remains shadow-only; historical backtests have survivorship bias. <span>Updated {fromUTC(d.updated_at)}</span></footer>
 </div>;
}
