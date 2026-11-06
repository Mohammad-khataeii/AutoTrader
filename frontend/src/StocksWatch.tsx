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
 const d:Row=resource.data??{};const a:Row=d.account??{};
 const h:Row=health.data??{};
 const positions:Row[]=Array.isArray(d.positions)?d.positions:[];
 const signals:Row[]=Array.isArray(d.signals)?d.signals:[];
 const visible=useMemo(()=>signals.filter(s=>`${s.symbol} ${s.name} ${s.sector}`.toLowerCase().includes(ticker.trim().toLowerCase())),[signals,ticker]);
 const curve:Row[]=Array.isArray(d.equity_curve)?d.equity_curve:[];
 const firstBenchmark=curve.length>0?n(curve[0].spy_close):0;
 const graph=curve.map(x=>({day:x.day,Portfolio:n(x.equity),"SPY baseline":firstBenchmark&&n(x.spy_close)?n(a.initial_cash)*n(x.spy_close)/firstBenchmark:null}));
 const source=(h.provider??"Not configured").toString();
 const status=(d.status?.paper?.status??d.status?.state??"WAITING").toString();
 async function control(action:"pause"|"resume"){
   if(busy)return;setBusy(true);setNotice("");
   try {await api.request("/api/stockswatch/control","POST",{action}); await Promise.all([api.refresh("/api/stockswatch/dashboard"),api.refresh("/api/stockswatch/status")]);setNotice(action==="pause"?"New virtual purchases paused.":"Virtual research and order admission resumed.");}
   catch {setNotice("Action was not confirmed. Please check the service status.");}
   finally {setBusy(false);}
 }
 return <div className="sw-root" data-swatch="stockswatch-v1">
  <section className="sw-hero">
   <div className="sw-hero-main"><div className="sw-eyebrow"><span className="sw-led"/> US EQUITIES LAB <span className="sw-hero-sep">/</span> AUTONOMOUS PAPER RESEARCH</div>
     <h2>Invest with evidence.<br/><span>Learn from every market cycle.</span></h2>
     <p>Market prices, filings, quantitative signals and bounded AI research. A separate virtual account—never a real-money trading connection.</p>
     <div className="sw-hero-tags"><Status value="PAPER ONLY"/><Status value={status}/><span className="sw-subtle">Feed: {source} · EOD only</span></div>
   </div>
   <div className="sw-hero-right"><div className="sw-portfolio-label">STOCKSWATCH PORTFOLIO</div><strong>{cash(a.equity)}</strong><div className={n(a.pnl)>=0?"sw-up":"sw-down"}>{n(a.pnl)>=0?<ArrowUpRight size={17}/>:<ArrowDownRight size={17}/>} {pct(a.pnl_pct)} <span>{cash(a.pnl)} all time</span></div><small>Independent USD virtual ledger</small></div>
  </section>
  {(resource.error || health.error) && <p className="sw-warning" role="alert">StocksWatch service is unavailable or the data is stale. Existing crypto monitoring continues independently. {resource.error || health.error}</p>}
  {notice && <p className="sw-notice" role="status">{notice}</p>}
  <ScannerMonitor/>
  <section className="sw-metrics">
   <Metric icon={Wallet} label="Available cash" value={cash(a.cash)} note="Uncommitted virtual USD"/>
   <Metric icon={LineIcon} label="Virtual exposure" value={cash(a.exposure)} note={`${positions.length} of 5 position slots used`}/>
   <Metric icon={TrendingUp} label="Realized P&L" value={cash(a.realized)} note="Simulated fills only" tone={n(a.realized)<0?"sw-bad":"sw-good"}/>
   <Metric icon={ShieldCheck} label="Drawdown" value={pct(-n(a.drawdown_pct))} note="Safety pause at 12%" tone={n(a.drawdown_pct)>=10?"sw-bad":""}/>
  </section>
  <section className="sw-mid-grid">
   <article className="sw-panel sw-equity-panel"><div className="sw-panel-top"><Header icon={BarChart3} title="Equity performance" note="Virtual equity compared with SPY, aligned to available EOD history"/><div className="sw-small-tag">No live market execution</div></div>
     {graph.length>=2 ? <div className="sw-chart"><ResponsiveContainer width="100%" height="100%"><AreaChart data={graph} margin={{top:10,right:10,left:0,bottom:0}}><defs><linearGradient id="swblue" x1="0" y1="0" x2="0" y2="1"><stop offset="0%" stopColor="#5c8ef1" stopOpacity={.32}/><stop offset="100%" stopColor="#5c8ef1" stopOpacity={0}/></linearGradient></defs><CartesianGrid vertical={false} stroke="var(--sw-grid)" strokeDasharray="3 5"/><XAxis dataKey="day" tick={{fill:"var(--sw-muted)",fontSize:10}} tickLine={false} axisLine={false} minTickGap={30}/><YAxis tickFormatter={(v:number)=>`$${Math.round(v/1000)}k`} tick={{fill:"var(--sw-muted)",fontSize:11}} width={46} tickLine={false} axisLine={false} domain={["auto","auto"]}/><Tooltip formatter={(v:any)=>cash(v)} contentStyle={{background:"var(--sw-card)",border:"1px solid var(--sw-border)",borderRadius:12,color:"var(--sw-ink)"}}/><Legend wrapperStyle={{fontSize:11}}/><Area type="monotone" name="Portfolio" dataKey="Portfolio" stroke="#548dfb" strokeWidth={2.5} fill="url(#swblue)" connectNulls={false}/><Line type="monotone" name="SPY baseline" dataKey="SPY baseline" dot={false} stroke="#e9a54c" strokeWidth={1.8} strokeDasharray="5 4" connectNulls={false}/></AreaChart></ResponsiveContainer></div> : <Blank text="The equity chart will populate after the first completed daily research and valuation cycle."/>}
   </article>
   <article className="sw-panel sw-state-panel"><Header icon={Gauge} title="Market intelligence" note="Always-on analysis with evidence and risk gates"/>
      <div className="sw-intel-row"><span>Execution mode</span><strong>Next EOD bar open</strong></div>
      <div className="sw-intel-row"><span>Strategy regime</span><strong>{val(d.signals?.[0]?.regime ?? "AWAITING HISTORY")}</strong></div>
      <div className="sw-intel-row"><span>AI interpretation</span><strong>Advisory only · quota shared</strong></div>
      <div className="sw-intel-row"><span>Price feed</span><strong>{source}</strong></div>
      <div className="sw-intel-row"><span>Last research run</span><strong>{fromUTC(d.research?.created_at)}</strong></div>
      <div className="sw-risk-label"><span>Portfolio capital at risk</span><strong>{pct(n(a.initial_cash)?(n(a.exposure)/n(a.equity))*100:0)}</strong></div>
      <div className="sw-risk-track"><div style={{width:`${Math.min(100,100*n(a.exposure)/Math.max(1,n(a.equity)))}%`}}/></div>
      <div className="sw-actionline"><button disabled={busy||!d.account} onClick={()=>control(a.paused?"resume":"pause")}>{a.paused?<Play size={16}/>:<Pause size={16}/>} {a.paused?"Resume paper orders":"Pause new paper orders"}</button><span>Trade controls affect StocksWatch only.</span></div>
   </article>
  </section>
  <section className="sw-nav" role="tablist" aria-label="StocksWatch details">
   {(["Signals","Portfolio","Research","Catalysts"] as const).map(t=><button key={t} role="tab" aria-selected={tab===t} className={tab===t?"active":""} onClick={()=>setTab(t)}>{t}</button>)}
   <button className="sw-refresh" title="Refresh StocksWatch data" onClick={()=>{void api.refresh("/api/stockswatch/dashboard");void api.refresh("/api/stockswatch/status");}}><RefreshCw size={15}/></button>
  </section>
  {tab==="Signals" && <div className="sw-detail-grid"><article className="sw-panel sw-span2"><div className="sw-panel-top"><Header icon={Flame} title="Ranked market candidates" note="Deterministic multi-strategy score; only completed daily observations"/><input aria-label="Filter stocks" placeholder="Search ticker, company or sector" value={ticker} onChange={e=>setTicker(e.target.value)}/></div>
   {visible.length ? <div className="sw-table-scroll"><table className="sw-table"><thead><tr><th>Company</th><th>Model score</th><th>Signals</th><th>Regime</th><th>Decision</th></tr></thead><tbody>{visible.map((s,i)=><tr key={s.symbol+i}><td><strong>{s.symbol}</strong><small>{s.name}</small></td><td><span className="sw-score">{n(s.score).toFixed(2)}</span></td><td>{Object.entries(s.signals??{}).filter(([,v])=>v).slice(0,3).map(([k])=><span className="sw-mini" key={k}>{k.replace(/_/g," ")}</span>)}</td><td>{val(s.regime)}</td><td><Status value={s.action??"WATCH"}/></td></tr>)}</tbody></table></div> : <Blank text="No qualified candidates yet. Backfill must complete and SPY history must establish the market regime."/>}
   <details className="sw-disclosure"><summary>Why trades are accepted or rejected</summary>{visible.slice(0,15).map(s=><div className="sw-reason" key={s.symbol}><b>{s.symbol} · {s.action}</b><p>{(s.reasons??[]).join(" · ")||"No qualified evidence"} · Policy {s.policy_version}</p></div>)}</details></article></div>}
  {tab==="Portfolio" && <div className="sw-detail-grid"><article className="sw-panel"><Header icon={Wallet} title="Open virtual positions" note="Position-level P&L and EOD stop reference"/>{positions.length ? positions.map(p=><div className="sw-position" key={p.symbol}><div><b>{p.symbol}</b><small>{p.sector} · {p.qty} shares</small></div><div><b className={n(p.unrealized)>=0?"sw-up":"sw-down"}>{cash(p.unrealized)}</b><small>{cash(p.mark)} · Stop {cash(p.stop)}</small></div></div>):<Blank text="No open stock positions. New orders require validated EOD signals and the next completed session."/>}</article>
     <article className="sw-panel"><Header icon={Activity} title="Virtual order activity" note="Orders are queued at day t close and filled at t+1 open when published"/>{(d.pending_orders??[]).map((o:Row,i:number)=><div className="sw-position" key={i}><div><b>{o.symbol}</b><small>{o.signal_day}</small></div><Status value={`${o.side} pending`}/></div>)}{(d.fills??[]).slice(0,20).map((f:Row,i:number)=><div className="sw-position" key={i}><div><b>{f.symbol} <small>{f.side}</small></b><small>{f.qty} shares · {f.fill_day}</small></div><div><b>{cash(f.price)}</b><small>{cash(f.realized)} realized</small></div></div>)}{!(d.pending_orders?.length||d.fills?.length) && <Blank text="No completed virtual fills yet. No artificial fills are generated."/>}</article></div>}
  {tab==="Research" && <div className="sw-detail-grid"><article className="sw-panel"><Header icon={Database} title="Historical research database" note="Actual observations, provenance and universe limitations"/><div className="sw-research-count"><strong>{(d.coverage??[]).reduce((s:number,r:Row)=>s+n(r.bars),0).toLocaleString()}</strong><span>stored stock-day bars</span></div><div className="sw-table-scroll"><table className="sw-table"><thead><tr><th>Symbol</th><th>History</th><th>Latest session</th></tr></thead><tbody>{(d.coverage??[]).map((r:Row)=><tr key={r.symbol}><td>{r.symbol}</td><td>{n(r.bars).toLocaleString()}</td><td>{val(r.last_day)}</td></tr>)}</tbody></table></div></article><article className="sw-panel"><Header icon={BrainCircuit} title="Strategy & ML comparison" note="Research-only challenger; never automatically promoted"/><div className="sw-intel-row"><span>Historical replay</span><Status value={val(d.research?.status)}/></div><div className="sw-intel-row"><span>Completed backtests</span><strong>{n(d.research?.total_backtests)}</strong></div><div className="sw-intel-row"><span>ML challenger</span><Status value={val(d.ml?.status)}/></div>{Object.entries(d.research?.by_strategy??{}).map(([strategy,s])=><div className="sw-research-strategy" key={strategy}><div><b>{strategy.replace(/_/g," ")}</b><small>{n((s as Row).count)} symbols</small></div><strong>{(s as Row).mean_return_pct == null?"Unavailable":pct((s as Row).mean_return_pct)}</strong></div>)}<details className="sw-disclosure"><summary>Research limitations and model evidence</summary><div className="sw-notes">{(d.research?.warnings??[]).map((w:string,i:number)=><p key={i}>{w}</p>)}<p>Model Brier: {d.ml?.brier??"Not evaluated"}; null Brier: {d.ml?.no_skill_brier??"Not evaluated"}. ML trading authority: disabled.</p></div></details></article></div>}
  {tab==="Catalysts" && <div className="sw-detail-grid"><article className="sw-panel"><Header icon={Newspaper} title="SEC filings & announcements" note="Official source links; timestamps retained for time-of-knowledge controls"/>{(d.filings??[]).length ? (d.filings??[]).map((f:Row,i:number)=><div key={i} className="sw-filing"><span className="sw-mini">{f.form}</span><div><b>{f.symbol}</b><p>{f.description||"Official SEC filing"}</p><small>{fromUTC(f.accepted_at)}</small></div><a href={f.url} target="_blank" rel="noopener noreferrer" title="Open SEC filing"><ExternalLink size={15}/></a></div>):<Blank text="SEC integration requires a contact User-Agent; no filing claims are invented."/>}</article><article className="sw-panel"><Header icon={BrainCircuit} title="AI & macro research" note="AI explanations use sourced SEC evidence only; not trading instructions"/>{(d.ai_insights??[]).length?(d.ai_insights??[]).map((x:Row,i:number)=><div className="sw-ai-note" key={i}><b>{x.symbol} · {x.model}</b><p>{x.analysis?.summary}</p><small>{fromUTC(x.generated_at)} · <a href={x.source_url} target="_blank" rel="noopener noreferrer">Official filing</a></small></div>):<Blank text="AI waits for new official filings and shared Gemini quota. It does not control orders."/>}<div className="sw-macro-title">Current macro observations <small>Not backtest vintages</small></div>{(d.macro??[]).slice(0,6).map((m:Row,i:number)=><div className="sw-intel-row" key={i}><span>{m.series} · {m.observation_day}</span><strong>{m.value}</strong></div>)}<div className="sw-macro-title">Company financial facts <small>Official SEC XBRL · publication dated</small></div>{(d.fundamentals??[]).slice(0,10).map((f:Row,i:number)=><div className="sw-intel-row" key={"fund-"+i}><span>{f.symbol} · {f.tag} · {f.end_day}</span><strong>{f.unit==="USD"?cash(f.value):val(f.value)} <a href={f.source_url} target="_blank" rel="noopener noreferrer" aria-label="Open official SEC company facts"><ExternalLink size={12}/></a></strong></div>)}</article></div>}
  <footer className="sw-footer"><ShieldAlert size={15}/> Paper-only. No broker integration. Free EOD data may be delayed, throttled or corporate-action incomplete. ML remains shadow-only; backtests are affected by survivorship bias. <span>Updated {fromUTC(d.updated_at)}</span></footer>
 </div>;
}
