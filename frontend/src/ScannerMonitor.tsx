import { useMemo, useState } from "react";
import { Activity, ArrowDownToLine, CheckCircle2, Clock3, Database, Download, FileClock, ScanSearch, ShieldCheck, TrendingUp, TriangleAlert, XCircle } from "lucide-react";
import { useResource } from "./api";
import "./ScannerMonitor.css";

type Row = Record<string, any>;
function nBatch(v: unknown): boolean { return Number(v) > 0; }
function fmt(v: unknown): string { return Number(v || 0).toLocaleString("en-US"); }
function when(v?: string | null): string {if (!v) return "—";const d = new Date(v);return Number.isNaN(d.getTime()) ? "—" : d.toLocaleString(undefined, {month:"short",day:"numeric",hour:"2-digit",minute:"2-digit",second:"2-digit"});}
function stageLabel(v?: string | null): string {return String(v || "WAITING").replace(/_/g," ").toLowerCase().replace(/\b\w/g,x=>x.toUpperCase());}
const phases = [
 {key:"PRICE",title:"Prices",note:"Alpaca EOD"},
 {key:"SEC",title:"Filings",note:"SEC evidence"},
 {key:"MACRO",title:"Macro",note:"FRED indicators"},
 {key:"PAPER",title:"Signals",note:"Risk & virtual orders"},
 {key:"RESEARCH",title:"Research",note:"Replay & ML"},
 {key:"GEMINI",title:"AI",note:"Capped research"},
] as const;
const groups:Record<string,string[]> = {
 All:[],Prices:["PRICE"],Filings:["SEC"],Macro:["MACRO"],Decisions:["PAPER","SIGNAL"],Research:["RESEARCH","MODEL"],AI:["GEMINI"],Problems:["ERROR","BACKOFF"]
};
const exportTypes=[
 ["scanner_events","All scanner steps"], ["scanner_runs","Scanner run history"],
 ["signal_features","Decision feature snapshots"], ["decisions","Trading decisions"],
 ["bars","Historical OHLCV prices"], ["sources","Provider diagnostics"],
 ["orders","All virtual orders"], ["fills","Virtual fills"],
 ["filings","SEC filings"], ["facts","SEC fundamentals"],
 ["macro","Economic observations"], ["research","Historical backtests"],
 ["ml","ML challenger results"], ["ai","Gemini research"],
 ["equity","Equity timeline"], ["positions","Current virtual holdings"],
 ["portfolio","Paper account ledger"], ["assets","Stock universe"]
] as const;

export function ScannerMonitor() {
 const data = useResource("/api/stockswatch/scanner",{poll:2500,ttl:1000});
 const history = useResource("/api/stockswatch/backfill",{poll:12000,ttl:5000});
 const [filter,setFilter] = useState("All");
 const [details,setDetails]=useState(false);
 const d:Row=data.data??{};const live:Row=d.live??{};const counts:Row=d.counts??{};
 const backfill:Row=history.data??{};const archive:Row[]=Array.isArray(backfill.historical_archive)?backfill.historical_archive:[];
 const dailyBars=archive.filter(x=>x.timeframe==="1Day").reduce((sum,x)=>sum+Number(x.bars||0),0);
 const minuteBars=archive.filter(x=>x.timeframe==="1Min").reduce((sum,x)=>sum+Number(x.bars||0),0);
 const backfillProgress=Number(backfill.jobs_total)>0?Math.min(100,100*Number(backfill.jobs_completed||0)/Number(backfill.jobs_total)):0;
 const events:Row[]=Array.isArray(d.events)?d.events:[];
 const recent:Row[]=Array.isArray(d.runs)?d.runs:[];
 const active=live.state==="RUNNING";
 const lastAt=live.updated_at ? new Date(live.updated_at).getTime() : 0;
 const stalled=active&&(!lastAt||Date.now()-lastAt>90000);
 const status=stalled?"STALLED":active?"SCANNING":live.state==="ERROR"?"ERROR":live.state==="INTERRUPTED"?"INTERRUPTED":"IDLE";
 const progress = live.batch_size > 0 ? Math.max(0,Math.min(100,Math.round(100*Number(live.completed||0)/Number(live.batch_size)))) : 0;
 const stage=String(live.stage??"");
 const phaseIndex=phases.findIndex(p=>stage.startsWith(p.key)||stage==="SIGNAL_EVALUATED"&&p.key==="PAPER"||stage.startsWith("MODEL")&&p.key==="RESEARCH");
 const visible=useMemo(()=>events.filter(e=>{
  if(filter==="All")return true;
  if(filter==="Problems")return e.severity==="ERROR"||e.severity==="WARNING";
  return (groups[filter]??[]).some(x=>String(e.stage).startsWith(x));
 }),[events,filter]);
 return <section className="sw-scanner" aria-label="StocksWatch automatic scanner activity">
  <div className="sw-scanner-top">
   <div className="sw-scanner-title"><div className="sw-scanner-icon"><ScanSearch size={21}/></div><div><div className="sw-scanner-kicker">AUTOMATED STOCKS RESEARCH ENGINE</div><h3>Scanner activity <span className={`sw-scanner-pill sw-scanner-${status.toLowerCase()}`}><span className="sw-scanner-dot"/>{status}</span></h3><p>Records each step in SQLite · refreshes every 2.5 seconds · source prices are end-of-day</p></div></div>
   <div className="sw-scanner-actions"><span className="sw-scanner-id" title={live.run_id??""}>Run {live.run_id?String(live.run_id).slice(-8):"not started"}</span><a href="/api/stockswatch/export/all" className="sw-scanner-export" download><ArrowDownToLine size={15}/> Export all evidence</a></div>
  </div>
  {data.error&&<div className="sw-scanner-error" role="alert"><TriangleAlert size={16}/> Scanner status could not be refreshed. Last saved events remain available.</div>}
  <div className="sw-scanner-now">
    <div className="sw-scanner-now-copy"><span className="sw-scanner-eyebrow">{status==="SCANNING"?"CURRENT OPERATION":status==="STALLED"?"NO RECENT PROGRESS":"LAST RECORDED OPERATION"}</span><strong>{stageLabel(stage)}</strong><small>{active&&live.symbol?`Currently processing ${live.symbol}`:active?"Executing the next research stage":status==="IDLE"?`Waiting for the next automatic ${Number(live.batch_size||4)}-symbol EOD refresh`:`Last update: ${when(live.updated_at)}`}</small></div>
    <div className="sw-scanner-progress"><div><b>{nBatch(live.batch_size) ? `${fmt(live.completed)} / ${fmt(live.batch_size)}` : "0 due"}</b><span>Symbols in this EOD batch</span></div><div className="sw-scanner-meter"><div style={{width:`${progress}%`}}/></div><small>{active?`Started ${when(live.started_at)}`:live.next_due_at?`Next cycle approximately ${when(live.next_due_at)}`:"Scheduling next cycle"}</small></div>
  </div>
  <div className="sw-scanner-phases">
   {phases.map((p,i)=><div className={`sw-scanner-phase ${active&&i===phaseIndex?"current":active&&phaseIndex>=0&&i<phaseIndex?"done":""}`} key={p.key}><span>{i+1}</span><div><b>{p.title}</b><small>{p.note}</small></div>{active&&phaseIndex>=0&&i<phaseIndex?<CheckCircle2 size={14}/>:null}</div>)}
  </div>
  <div className="sw-scanner-totals">
   <div><Database size={16}/><strong>{fmt(counts.bars)}</strong><small>Legacy EOD bars</small></div>
   <div><TrendingUp size={16}/><strong>{fmt(counts.assets_with_history)} / {fmt(counts.assets)}</strong><small>Stocks covered</small></div>
   <div><ShieldCheck size={16}/><strong>{fmt(counts.feature_snapshots)}</strong><small>Saved signal features</small></div>
   <div><Activity size={16}/><strong>{fmt(counts.decisions)}</strong><small>Trade decisions</small></div>
   <div><FileClock size={16}/><strong>{fmt(counts.events)}</strong><small>Audit events</small></div>
  </div>
  <div className="sw-scanner-lower">
   <div className="sw-scanner-feed">
    <div className="sw-scanner-subhead"><div><b>Execution timeline</b><small>Persisted scanner events, latest first</small></div><select aria-label="Filter scanner events" value={filter} onChange={e=>setFilter(e.target.value)}>{Object.keys(groups).map(g=><option key={g} value={g}>{g}</option>)}</select></div>
    <div className="sw-scanner-events" role="log" aria-live="off">
     {visible.length ? visible.slice(0,42).map(e=><div className="sw-scanner-event" key={e.id}><div className={`sw-scanner-event-marker ${String(e.severity||"info").toLowerCase()}`}>{e.severity==="ERROR"?<XCircle size={14}/>:e.severity==="WARNING"?<TriangleAlert size={14}/>:e.severity==="OK"?<CheckCircle2 size={14}/>:<Clock3 size={14}/>}</div><div className="sw-scanner-event-main"><div><b>{stageLabel(e.stage)}</b>{e.symbol&&<span className="sw-scanner-symbol">{e.symbol}</span>}</div><p>{e.message}</p><small>{Object.entries(e.details??{}).slice(0,4).map(([k,v])=>`${stageLabel(k)}: ${String(v)}`).join(" · ")}</small></div><time>{when(e.at)}</time></div>) : <div className="sw-scanner-empty">No saved events matching this filter yet. The next automatic cycle will populate this log.</div>}
    </div>
   </div>
   <aside className="sw-scanner-side"><div className="sw-scanner-subhead"><div><b>Research archive</b><small>Extract every observation for analysis and improvements</small></div><Database size={18}/></div><p>Historical OHLCV, each scored feature set, decisions, orders, fills, SEC and macro records are stored separately. Exports contain actual persisted rows, not synthetic summaries.</p><div className="sw-scanner-archive-row"><span>Historical backfill jobs</span><b>{history.error?"Unavailable":backfill.jobs_total!=null?`${fmt(backfill.jobs_completed)} / ${fmt(backfill.jobs_total)}`:"Loading"}</b></div><div className="sw-scanner-meter" role="progressbar" aria-label="Historical backfill completion" aria-valuenow={Math.round(backfillProgress)} aria-valuemin={0} aria-valuemax={100}><div style={{width:`${backfillProgress}%`}}/></div><div className="sw-scanner-archive-row"><span>New daily / minute bars</span><b>{fmt(dailyBars)} / {fmt(minuteBars)}</b></div><div className="sw-scanner-archive-row"><span>Verified Alpaca assets</span><b>{backfill.verified_assets==null?"—":`${fmt(backfill.verified_assets)} / 52`}</b></div><div className="sw-scanner-archive-row"><span>History worker</span><b>{backfill.worker_interval_seconds? `${backfill.worker_interval_seconds}s / batch` : "—"}</b></div><small className="sw-scanner-note">Archive progress is separate from the legacy EOD bar count. Data ingestion does not imply trading readiness.</small><div className="sw-scanner-archive-row"><span>Research & ML</span><b>{fmt(counts.research_runs)} / {fmt(counts.model_runs)}</b></div><div className="sw-scanner-archive-row"><span>Financial facts</span><b>{fmt(counts.facts)}</b></div><div className="sw-scanner-archive-row"><span>Official filings</span><b>{fmt(counts.filings)}</b></div><div className="sw-scanner-archive-row"><span>AI insights</span><b>{fmt(counts.ai_insights)}</b></div><div className="sw-scanner-downloads"><a href="/api/stockswatch/export/signal_features" download><Download size={14}/> Feature snapshots</a><a href="/api/stockswatch/export/decisions" download><Download size={14}/> All decisions</a><a href="/api/stockswatch/export/bars" download><Download size={14}/> Historical bars</a></div><details open={details} onToggle={e=>setDetails((e.currentTarget as HTMLDetailsElement).open)} className="sw-scanner-disclosure"><summary>Download other datasets</summary><div>{exportTypes.map(([k,label])=><a key={k} href={`/api/stockswatch/export/${k}`} download>{label}</a>)}</div></details>
    <div className="sw-scanner-history"><b>Completed scan runs</b>{recent.slice(0,6).map((r,i)=><div key={r.id??i}><span>{when(r.started_at)}</span><span>{r.state}</span></div>)}</div>
    <small className="sw-scanner-note">This monitor shows the actual scheduler workflow, not live tick-by-tick market data. Existing past decisions before this upgrade cannot be retroactively reconstructed.</small>
   </aside>
  </div>
 </section>;
}
