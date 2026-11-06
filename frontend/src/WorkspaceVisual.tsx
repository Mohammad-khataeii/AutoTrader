import React, { useMemo, useState, type ReactNode } from "react";
import {
  Activity, AlertTriangle, ArrowDownRight, ArrowRight, ArrowUpRight, BarChart3,
  BookOpen, CalendarClock, CheckCircle2, ChevronDown, CircleDollarSign, Clock3,
  Coins, Database, Eye, FileBarChart2, Filter, FlaskConical, Gauge,
  Layers3, LayoutGrid, ListFilter, LockKeyhole, Radio, Search, Settings2,
  ShieldAlert, ShieldCheck, SlidersHorizontal, TrendingUp, Wallet, X,
} from "lucide-react";
import { useResource, type Row } from "./api";
import { money, strategyName, humanize, date } from "./model";
import { ResourceState, Technical } from "./ui";
import "./WorkspaceVisual.css";

type View = "opportunities" | "strategies" | "activity" | "research" | "insights" | "settings";
type Mood = "green" | "red" | "amber" | "neutral";
const numeric = (value: unknown): number | null => value == null || value === "" || !Number.isFinite(Number(value)) ? null : Number(value);
const fmt = (value: unknown, decimals = 2) => numeric(value) == null ? "—" : new Intl.NumberFormat("en-GB", { maximumFractionDigits: decimals, minimumFractionDigits: decimals }).format(Number(value));
const cash = (v: unknown) => numeric(v) == null ? "—" : money(v);
const signed = (v: unknown) => numeric(v) == null ? "—" : `${Number(v) > 0 ? "+" : Number(v) < 0 ? "−" : ""}${money(Math.abs(Number(v)))}`;
const percent = (v: unknown, multiplied = false) => numeric(v) == null ? "—" : `${fmt(Number(v) * (multiplied ? 100 : 1), 2)}%`;
const mood = (v: unknown): Mood => numeric(v) == null || Number(v) === 0 ? "neutral" : Number(v) > 0 ? "green" : "red";
const title = (v: unknown) => humanize(v ?? "Unknown");
const time = (v: unknown) => v ? date(v, true) : "Not recorded";
const sum = (items: unknown[]) => items.reduce<number>((acc, v) => acc + (numeric(v) ?? 0), 0);
const clip = (v: unknown, n = 42) => {const s = String(v ?? "—").replace(/_/g, " "); return s.length > n ? s.slice(0, n - 1) + "…" : s;};

function Pill({ children, tone = "neutral" }: { children: ReactNode; tone?: Mood }) {
  return <span className={`ws-pill ws-${tone}`}><i aria-hidden="true"/>{children}</span>;
}
function IconCircle({ children, tone = "neutral" }: { children: ReactNode; tone?: Mood }) {
  return <span className={`ws-icon ws-${tone}`}>{children}</span>;
}
function Header({ icon, title: heading, subtitle, right }: { icon?: ReactNode; title: string; subtitle?: string; right?: ReactNode }) {
  return <div className="ws-section-head"><div><h3>{icon}{heading}</h3>{subtitle && <p>{subtitle}</p>}</div>{right}</div>;
}
function Metric({ label, value, note, icon, tone = "neutral" }: {label: string; value: ReactNode; note?: string; icon?: ReactNode; tone?: Mood}) {
  return <div className="ws-metric"><div className="ws-metric-top"><span>{label}</span><IconCircle tone={tone}>{icon ?? <Activity size={17}/>}</IconCircle></div><strong className={`ws-figure ws-${tone}`}>{value}</strong><small>{note ?? "From recorded account data"}</small></div>;
}
function Section({ children, title: heading, subtitle, right, icon }: { children: ReactNode; title?: string; subtitle?: string; right?: ReactNode; icon?: ReactNode }) {
  return <section className="ws-surface">{heading && <Header title={heading} subtitle={subtitle} right={right} icon={icon}/>} {children}</section>;
}
function Bar({ fraction, tone = "green" }: { fraction: number | null; tone?: Mood }) {
  return <span className="ws-track"><span className={`ws-fill ws-${tone}`} style={{ width: `${Math.min(100,Math.max(0,fraction ?? 0))}%` }}/></span>;
}
function Empty({ children }: { children: ReactNode }) {
  return <div className="ws-empty"><Eye size={23}/><strong>Nothing to show yet</strong><span>{children}</span></div>;
}
function Segments({ value, options, onChange }: {value:string; options: string[]; onChange:(s:string)=>void}) {
  return <div className="ws-segments" role="group" aria-label="Display filter">{options.map(item=><button key={item} type="button" aria-pressed={value===item} onClick={()=>onChange(item)}>{item}</button>)}</div>;
}
function SearchBox({ value, setValue, placeholder = "Search markets or strategies" }: {value:string;setValue:(v:string)=>void;placeholder?:string}) {
  return <label className="ws-search"><Search size={15}/><span className="sr-only">Search</span><input value={value} onChange={e=>setValue(e.target.value)} placeholder={placeholder}/>{value && <button type="button" aria-label="Clear search" onClick={()=>setValue("")}><X size={13}/></button>}</label>;
}
function SimpleTable({ head, rows, empty }: {head:string[]; rows:ReactNode[][]; empty?: string}) {
  const [page,setPage] = useState(0);
  const max = Math.max(1, Math.ceil(rows.length/12));
  const actual = Math.min(page,max-1);
  if(!rows.length) return <Empty>{empty ?? "New records will appear when the scanner has observations."}</Empty>;
  return <><div className="ws-table-wrap" role="region" tabIndex={0} aria-label={head.join(", ") }><table className="ws-table"><thead><tr>{head.map(h=><th key={h} scope="col">{h}</th>)}</tr></thead><tbody>{rows.slice(actual*12,actual*12+12).map((row,i)=><tr key={`${actual}-${i}`}>{row.map((cell,j)=><td key={j}>{cell}</td>)}</tr>)}</tbody></table></div>{max>1 && <div className="ws-pager"><span>{actual*12+1}–{Math.min(rows.length,(actual+1)*12)} of {rows.length}</span><div><button disabled={actual===0} onClick={()=>setPage(actual-1)}>Previous</button><button disabled={actual===max-1} onClick={()=>setPage(actual+1)}>Next</button></div></div>}</>;
}
function ValueBars({ rows, label = "Recorded P&L" }: {rows:{name:string;value:number}[];label?:string}) {
  const max = Math.max(0.01,...rows.map(r=>Math.abs(r.value)));
  return <div className="ws-bars" aria-label={label}>{rows.map((r,i)=><div className="ws-bar-row" key={`${r.name}-${i}`}><span title={r.name}>{clip(r.name,22)}</span><Bar fraction={Math.abs(r.value)/max*100} tone={mood(r.value)}/><strong className={`ws-${mood(r.value)}`}>{signed(r.value)}</strong></div>)}</div>;
}
function Advanced({ children, title: heading = "Full reports & advanced tools", help = "Original detail view, historical evidence and controls" }: {children:ReactNode;title?:string;help?:string}) {
  const [opened,setOpened]=useState(false);
  return <section className="ws-advanced"><div><IconCircle><Layers3 size={19}/></IconCircle><div><strong>{heading}</strong><span>{help}</span></div></div><button onClick={()=>setOpened(!opened)} aria-expanded={opened}>{opened?"Hide details":"Open details"}<ChevronDown size={15} className={opened?"ws-turn":""}/></button>{opened && <div className="ws-advanced-content">{children}</div>}</section>;
}
function FeedWarning({resource,label}: {resource:ReturnType<typeof useResource>;label:string}) {return <ResourceState resource={resource} label={label}/>;}

function OpportunitiesBoard() {
  const observations = useResource("/api/opportunities?limit=40&cursor=0",{poll:30000});
  const intel = useResource("/api/intelligence?limit=30&cursor=0",{poll:45000});
  const raw:Row[] = observations.data?.rows ?? [];
  const candidates: Row[] = intel.data?.rows ?? [];
  const [tab,setTab] = useState("All"); const [query,setQuery] = useState(""); const [chosen,setChosen] = useState<Row|null>(null);
  const filtered = raw.filter(r => {
    const eligible= Boolean(r.economic_eligible);const technical=Boolean(r.technical_eligible);
    if(tab==="Feasible"&&!eligible)return false;
    if(tab==="Technical"&&!technical)return false;
    if(tab==="Blocked"&&(eligible||technical))return false;
    return `${r.symbol} ${r.strategy_id}`.toLowerCase().includes(query.toLowerCase());
  });
  const technical=numeric(observations.data?.technical_candidates),economic=numeric(observations.data?.economically_viable_candidates);
  return <>
    <div className="ws-kpis">
      <Metric label="Markets observed" value={numeric(observations.data?.discovery?.counts?.supported_eur) ?? (observations.data?raw.length:"—")} icon={<Coins size={17}/>} note="EUR markets / observation window"/>
      <Metric label="Technical setups" value={technical ?? "—"} tone="neutral" icon={<Gauge size={17}/>} note="Observed setups, not purchases"/>
      <Metric label="Cost-feasible" value={economic ?? "—"} tone={economic != null && economic>0?"green":"neutral"} icon={<CheckCircle2 size={17}/>} note="Indicative economics only"/>
      <Metric label="Market research" value={intel.data?.status ? title(intel.data.status):"Awaiting data"} tone={intel.data?.status==="CURRENT"?"green":"amber"} icon={<Radio size={17}/>} note="Latest intelligence snapshot"/>
    </div>
    <Section title="Opportunity qualification" subtitle="How many observed ideas pass each stage — not guaranteed profitable trades" icon={<Filter size={17}/>}>
      <div className="ws-funnel"><div><span>Observations</span><strong>{raw.length}</strong><Bar fraction={100}/></div><div><span>Technical</span><strong>{technical ?? "—"}</strong><Bar fraction={technical != null && raw.length ? technical/raw.length*100:null}/></div><div><span>Economic</span><strong>{economic ?? "—"}</strong><Bar fraction={economic != null && raw.length ? economic/raw.length*100:null}/></div><div><span>Confirmed edge</span><strong>Unproven</strong><Bar fraction={0} tone="amber"/></div></div>
    </Section>
    <Section title="Observed market setups" subtitle="Select a market for its recorded evidence; actual orders require separate portfolio checks" icon={<ListFilter size={17}/>} right={<Pill tone={observations.data?.research_freshness?.current?"green":"amber"}>{observations.data?.research_freshness?.current?"Current":"Check freshness"}</Pill>}>
      <FeedWarning resource={observations} label="Market observations"/>
      <div className="ws-toolbar"><Segments value={tab} options={["All","Technical","Feasible","Blocked"]} onChange={setTab}/><SearchBox value={query} setValue={setQuery}/></div>
      <SimpleTable head={["Coin / strategy","Trend","Target (gross)","Est. costs","Net R/R","Qualification"]} rows={filtered.map(r=>[
        <button className="ws-text-link" onClick={()=>setChosen(r)}><strong>{r.symbol}</strong><small>{strategyName(r.strategy_id)}</small></button>,
        <span className="ws-muted">{title(r.regime_assessment?.trend)}</span>,
        percent(r.economics?.measurements?.gross_target_return,true),
        cash(r.economics?.measurements?.estimated_total_round_trip_cost_eur),
        fmt(r.economics?.measurements?.net_reward_risk,2),
        <Pill tone={r.economic_eligible?"green":r.technical_eligible?"amber":"neutral"}>{r.economic_eligible?"Cost-feasible":r.technical_eligible?"Technical only":"Not qualified"}</Pill>
      ])}/>
      {chosen && <div className="ws-detail"><div className="ws-section-head"><div><h3>{chosen.symbol} · {strategyName(chosen.strategy_id)}</h3><p>Observed at {time(chosen.as_of)} · indicative paper hypothesis</p></div><button onClick={()=>setChosen(null)}><X size={15}/>Close</button></div><div className="ws-detail-grid"><Metric label="Proposed size" value={cash(chosen.sizing?.quote_budget_eur)} icon={<Wallet size={16}/>}/><Metric label="Potential net target" value={cash(chosen.economics?.measurements?.conditional_target_net_eur?.[0])} icon={<TrendingUp size={16}/>}/><Metric label="Modeled stop loss" value={cash(chosen.economics?.measurements?.expected_net_stop_loss_eur)} icon={<ShieldAlert size={16}/>}/></div><Technical value={chosen} label="Complete recorded qualifying evidence"/></div>}
    </Section>
    <Section title="Latest intelligence" subtitle="Separately recorded candidate status from the intelligence engine" icon={<Activity size={17}/>}>
      <FeedWarning resource={intel} label="Intelligence outcomes"/>
      <div className="ws-mini-list">{candidates.slice(0,8).map((r,i)=><div key={`${r.symbol}-${r.strategy_id}-${i}`}><div><strong>{r.symbol ?? "Unknown"}</strong><span>{strategyName(r.strategy_id)}</span></div><Pill tone={r.status==="READY"?"green":r.status==="STALE"?"amber":"neutral"}>{title(r.status)}</Pill></div>)}{!candidates.length && <Empty>No recent intelligence observations are available.</Empty>}</div>
    </Section>
  </>;
}

function StrategiesBoard() {
  const paper=useResource("/api/personal-paper",{poll:30000});
  const shadows=useResource("/api/shadow/summary",{poll:30000});
  const strategies:Row[]=paper.data?.strategies??[];
  const attribution:Row[]=paper.data?.attribution?.strategy??[];
  const experiments:Row[]=shadows.data?.experiments??[];
  const [query,setQuery]=useState("");
  const grouped = useMemo<Row[]>(()=>strategies.map(s=>{const stats=attribution.find(x=>x.key===s.strategy_id);return { ...s, closed:stats?.closed_positions??s.closed_positions??0,net:stats?.realized_closed_net_pnl??s.net_realized_pnl, name:strategyName(s.strategy_id)}}),[strategies,attribution]);
  const ranked=[...grouped].filter(r=>r.name.toLowerCase().includes(query.toLowerCase()));
  return <>
    <div className="ws-kpis">
      <Metric label="Selected hypotheses" value={paper.data?strategies.length:"—"} icon={<FlaskConical size={17}/>} note="Primary simulated portfolio"/>
      <Metric label="Closed positions" value={paper.data?.performance?.closed_positions??"—"} icon={<CheckCircle2 size={17}/>} note="Entire primary portfolio"/>
      <Metric label="Primary realized P&L" value={signed(paper.data?.portfolio?.realized_pnl)} tone={mood(paper.data?.portfolio?.realized_pnl)} icon={<CircleDollarSign size={17}/>} note="After recorded execution costs"/>
      <Metric label="Shadow experiments" value={shadows.data?experiments.length:"—"} icon={<Layers3 size={17}/>} note="Different isolated accounts"/>
    </div>
    <Section title="Strategy performance" subtitle="Actual completed primary-account trades by recorded strategy; small samples are not predictive" icon={<BarChart3 size={17}/>} right={<Pill tone="amber">Forward evidence required</Pill>}>
      <FeedWarning resource={paper} label="Primary strategy analysis"/>
      <div className="ws-two-cols"><div><Header title="Net realized P&L by strategy" subtitle="Historical net results, not a forecast"/><ValueBars rows={grouped.filter(r=>numeric(r.net)!=null).slice(0,10).map(r=>({name:r.name,value:Number(r.net)}))}/></div><div className="ws-sample-note"><FlaskConical size={22}/><strong>Unproven predictive edge</strong><p>Results are from recorded virtual trading. Compare across independent market periods, cost stress, and unseen data before changing allocation.</p><div><span>Primary balance</span><strong>{cash(paper.data?.portfolio?.equity)}</strong></div><div><span>Open positions</span><strong>{paper.data?.performance?.open_positions??"—"}</strong></div></div></div>
    </Section>
    <Section title="Primary strategies" subtitle="The same €7,000 virtual portfolio, not separate balances" icon={<LayoutGrid size={17}/>} right={<SearchBox value={query} setValue={setQuery} placeholder="Find strategy"/>}>
      <div className="ws-strategy-grid">{ranked.map((r,i)=><div className="ws-strategy-card" key={`${r.strategy_id}-${i}`}><div className="ws-strategy-header"><IconCircle><FlaskConical size={19}/></IconCircle><Pill tone="amber">Experimental</Pill></div><h4>{r.name}</h4><div className={`ws-strategy-money ws-${mood(r.net)}`}>{signed(r.net)}</div><div className="ws-strategy-foot"><div><span>Closed trades</span><strong>{r.closed}</strong></div><div><span>Confidence</span><strong>{String(r.confidence??"Unknown").replace(/_/g," ").toLowerCase().includes("insufficient")?"Low sample":"Unvalidated"}</strong></div></div></div>)}{!ranked.length&&<Empty>No matching strategies in the current primary-account profile.</Empty>}</div>
    </Section>
    <Section title="Shadow accounts" subtitle="Isolated research experiments — do not add their capital to your personal portfolio" icon={<Layers3 size={17}/> }>
      <FeedWarning resource={shadows} label="Shadow experiments"/>
      <SimpleTable head={["Strategy","Status","Closed trades","Financial state","Account"]} rows={experiments.slice(0,35).map(r=>[
        <span className="ws-strong">{strategyName(r.manifest?.strategy_id)}</span>,
        <Pill tone={r.state==="SHADOW_ACTIVE"?"green":"amber"}>{title(r.state)}</Pill>,
        r.portfolio?.closed_positions??r.portfolio?.trades_closed??"—",
        <span className="ws-muted">{title(r.risk_state??r.portfolio?.risk_state)}</span>,
        <span className="ws-muted" title={r.experiment_id}>{String(r.experiment_id??"").slice(0,10)}</span>
      ])} empty="No shadow accounts are recorded."/>
    </Section>
  </>;
}

function ActivityBoard() {
  const paper=useResource("/api/personal-paper",{poll:30000});
  const recent=useResource("/api/personal-paper/activity",{poll:10000});
  const [filter,setFilter]=useState("All");const [query,setQuery]=useState("");
  const events:Row[]=recent.data?.events??[];
  const visible=events.filter(r => (filter==="All"||(filter==="Trades"&&["ORDER","FILL"].includes(r.kind))||(filter==="Decisions"&&r.kind==="DECISION"))&&`${r.symbol} ${r.strategy_id} ${r.kind}`.toLowerCase().includes(query.toLowerCase()));
  const fills:Row[]=paper.data?.fills??[];
  return <>
    <div className="ws-kpis">
      <Metric label="Realized P&L" value={signed(paper.data?.portfolio?.realized_pnl)} tone={mood(paper.data?.portfolio?.realized_pnl)} icon={<CircleDollarSign size={17}/>} note="Primary paper portfolio"/>
      <Metric label="Closed positions" value={paper.data?.performance?.closed_positions??"—"} icon={<CheckCircle2 size={17}/>} note="Recorded completed trades"/>
      <Metric label="Executed fills" value={paper.data?.performance?.fills??"—"} icon={<ArrowRight size={17}/>} note="Buys and sells"/>
      <Metric label="Trading fees" value={cash(paper.data?.cash_flow?.fees_total_eur)} icon={<Wallet size={17}/>} note="Across recorded fills"/>
    </div>
    <Section title="Trading performance" subtitle="Recorded portfolio outcomes — past results do not prove future performance" icon={<BarChart3 size={17}/>}>
      <FeedWarning resource={paper} label="Portfolio performance"/>
      <div className="ws-outcomes"><div><span>Win rate</span><strong>{percent(paper.data?.performance?.win_rate,true)}</strong><Bar fraction={numeric(paper.data?.performance?.win_rate)!=null?Number(paper.data.performance.win_rate)*100:null}/></div><div><span>Open positions</span><strong>{paper.data?.performance?.open_positions??"—"}</strong><small>No active holdings means no market exposure for this account.</small></div><div><span>Unrealized P&L</span><strong className={`ws-${mood(paper.data?.portfolio?.unrealized_pnl)}`}>{signed(paper.data?.portfolio?.unrealized_pnl)}</strong><small>Mark-to-market estimate</small></div></div>
    </Section>
    <Section title="Recent account activity" subtitle="Actual simulated fills are distinguished from strategy decisions" icon={<CalendarClock size={17}/>}>
      <FeedWarning resource={recent} label="Trading activity"/>
      <div className="ws-toolbar"><Segments options={["All","Trades","Decisions"]} value={filter} onChange={setFilter}/><SearchBox value={query} setValue={setQuery} placeholder="Search coin or event"/></div>
      <SimpleTable head={["Time","Coin","Event","Quantity / status","Evidence"]} rows={visible.map(r=>[
        <span className="ws-muted ws-nowrap">{time(r.timestamp)}</span>,<strong>{r.symbol??"—"}</strong>,
        <Pill tone={r.kind==="FILL"?"green":r.kind==="ORDER"?"amber":"neutral"}>{r.kind==="FILL"?`Paper ${r.side=== "BUY"?"buy":"sell"}`:r.kind==="ORDER"?`Order · ${title(r.status)}`:r.accepted?"Qualified decision":"No-entry decision"}</Pill>,
        <span className="ws-muted">{r.kind==="FILL"?`${fmt(r.quantity,6)} × ${cash(r.price)}`:r.kind==="ORDER"?`${fmt(r.filled_quantity,4)} filled`:title(r.decision_reason)}</span>,
        <span className="ws-muted" title={String(r.reasons?.join(", ")??r.reason??"")}>{clip(r.reasons?.[0]??r.broker_reason??r.strategy_id??r.reason,34)}</span>
      ])} empty="The activity feed has no recent matching events."/>
      <p className="ws-footnote">The activity endpoint returns a bounded recent window; figures above come from the full recorded primary portfolio where available.</p>
    </Section>
    <Section title="Most recent actual fills" subtitle="Financial events only, with execution prices and fees" icon={<Wallet size={17}/>}>
      <SimpleTable head={["Coin","Side","Quantity","Fill price","Fee","Recorded"]} rows={fills.slice(0,20).map(r=>[
        <strong>{r.symbol}</strong>,<Pill tone={r.side==="BUY"?"green":"neutral"}>{r.side==="BUY"?"Buy":"Sell"}</Pill>,fmt(r.quantity,6),cash(r.price),cash(r.fee),<span className="ws-nowrap ws-muted">{time(r.created_at??r.timestamp)}</span>
      ])} empty="No paper fills yet."/>
    </Section>
  </>;
}

function ResearchBoard() {
  const reports=useResource("/api/research/summary",{ttl:300000});
  const shadows=useResource("/api/shadow/summary",{ttl:60000});
  const [query,setQuery]=useState("");
  const latest=reports.data?.latest;
  const exp=reports.data?.experimental_latest;
  const rows=useMemo<Row[]>(()=>[...[{name:"Baseline",doc:latest},{name:"Experimental",doc:exp}].flatMap(({name,doc})=>Object.entries(doc?.timeframes??{}).flatMap(([frame,data])=>Object.entries((data as Row)?.strategies??{}).map(([strategy,entry])=>({kind:name,frame,strategy,...(entry as Row)}))))],[latest,exp]);
  const visible=rows.filter(r=>`${r.strategy} ${r.frame} ${r.kind}`.toLowerCase().includes(query.toLowerCase()));
  return <>
    <div className="ws-kpis"><Metric label="Research reports" value={reports.data?(Number(Boolean(latest))+Number(Boolean(exp))):"—"} icon={<FileBarChart2 size={17}/>} note="Available baseline / experimental"/><Metric label="Strategy / timeframe rows" value={reports.data?rows.length:"—"} icon={<FlaskConical size={17}/>} note="Historical recorded comparisons"/><Metric label="Strategy registry" value={reports.data?(reports.data.registry?.length??0)+(reports.data.experimental_registry?.length??0):"—"} icon={<Database size={17}/>} note="Registered research hypotheses"/><Metric label="Validation" value="Not established" tone="amber" icon={<ShieldAlert size={17}/>} note="Historical proxy is not future edge"/></div>
    <Section title="Historical research overview" subtitle="Compare recorded evidence without confusing backtests with actual paper-trading profits" icon={<BarChart3 size={17}/>}>
      <FeedWarning resource={reports} label="Research evidence"/>
      <div className="ws-research-grid"><div className="ws-research-card"><IconCircle><BookOpen size={20}/></IconCircle><span>Baseline research</span><strong>{latest?"Report available":"No report"}</strong><small>Historical simulation only</small></div><div className="ws-research-card"><IconCircle><FlaskConical size={20}/></IconCircle><span>Experimental hypotheses</span><strong>{exp?"Report available":"No report"}</strong><small>Separate research evidence</small></div><div className="ws-research-card"><IconCircle tone="amber"><ShieldCheck size={20}/></IconCircle><span>Source and uncertainty</span><strong>Review assumptions</strong><small>Model costs and sample limitations</small></div></div>
    </Section>
    <Section title="Recorded strategy comparisons" subtitle="Observed metrics may use different samples, intervals and execution assumptions" icon={<ListFilter size={17}/>} right={<SearchBox value={query} setValue={setQuery} placeholder="Search report"/>}>
      <SimpleTable head={["Strategy","Data cohort","Timeframe","Trades","Net result","Max drawdown"]} rows={visible.map(r=>[
        <strong>{strategyName(r.strategy)}</strong>,<Pill tone={r.kind==="Experimental"?"amber":"neutral"}>{r.kind}</Pill>,r.frame,r.trades??r.trade_count??"—",<span className={`ws-${mood(r.net_profit)}`}>{signed(r.net_profit)}</span>,percent(r.max_drawdown,true)
      ])} empty="There are no recorded strategy/timeframe rows for this filter."/>
    </Section>
    <Section title="Research status" subtitle="Keep prospective and historical evidence separate" icon={<ShieldCheck size={17}/> }>
      <div className="ws-mini-list"><div><div><strong>Shadow experiments</strong><span>Isolated forward research accounts</span></div><strong>{shadows.data?.experiments?.length??"—"}</strong></div><div><div><strong>Data provenance</strong><span>Metrics should cite their recorded timeframes</span></div><Pill tone="amber">Check sources</Pill></div><div><div><strong>Future expected profitability</strong><span>No calibrated probability confirmed</span></div><Pill tone="amber">Unknown</Pill></div></div>
    </Section>
  </>;
}

function InsightsBoard() {
  const activity=useResource("/api/personal-paper/activity",{poll:15000});
  const personal=useResource("/api/personal-paper",{poll:15000});
  const system=useResource("/api/monitoring/summary",{poll:15000});
  const evaluations:Row[]=activity.data?.evaluations??[];
  const counts=useMemo(()=>{const result=new Map<string,number>();for(const r of evaluations)for(const reason of new Set<string>([...(r.reasons??[]),...(r.decision_reason?.split(",")??[])].filter(Boolean))){result.set(reason,(result.get(reason)??0)+1);}return [...result.entries()].sort((a,b)=>b[1]-a[1]).slice(0,9)},[evaluations]);
  const accepted=evaluations.filter(r=>r.accepted===true).length;
  const technical=evaluations.filter(r=>r.technical===true).length;
  const economic=evaluations.filter(r=>r.economic===true).length;
  const [filter,setFilter]=useState("All");
  const visible=evaluations.filter(r=>filter==="All"||(filter==="Qualified"&&r.accepted)||(filter==="Rejected"&&!r.accepted));
  return <>
    <div className="ws-kpis"><Metric label="Recent evaluations" value={activity.data?evaluations.length:"—"} icon={<Activity size={17}/>} note="Latest recorded decision page"/><Metric label="Technical passes" value={activity.data?technical:"—"} icon={<Gauge size={17}/>} note="Available annotated decisions"/><Metric label="Cost-feasible" value={activity.data?economic:"—"} icon={<Coins size={17}/>} note="Available economic assessments"/><Metric label="Accepted decisions" value={activity.data?accepted:"—"} tone={accepted>0?"green":"neutral"} icon={<CheckCircle2 size={17}/>} note="A decision is not an executed fill"/></div>
    <Section title="Decision funnel" subtitle="Counts refer to the latest bounded activity sample; stages can be unannotated" icon={<Filter size={17}/> }>
      <FeedWarning resource={activity} label="Decision evidence"/>
      <div className="ws-funnel"><div><span>Evaluated</span><strong>{evaluations.length}</strong><Bar fraction={100}/></div><div><span>Technical</span><strong>{technical}</strong><Bar fraction={evaluations.length?technical/evaluations.length*100:null}/></div><div><span>Economic</span><strong>{economic}</strong><Bar fraction={evaluations.length?economic/evaluations.length*100:null}/></div><div><span>Accepted</span><strong>{accepted}</strong><Bar fraction={evaluations.length?accepted/evaluations.length*100:null}/></div></div>
    </Section>
    <div className="ws-grid-two"><Section title="Most frequent blockers" subtitle="Recorded reasons may overlap for one decision" icon={<ShieldAlert size={17}/>}>
      {counts.length?<div className="ws-reasons">{counts.map(([name,value])=><div key={name}><div><span title={name}>{clip(name,44)}</span><strong>{value}</strong></div><Bar fraction={counts[0][1]?value/counts[0][1]*100:null} tone="amber"/></div>)}</div>:<Empty>No labeled rejection reasons in the recent sample.</Empty>}
      </Section><Section title="System safety" subtitle="Keep execution state distinct from strategy eligibility" icon={<ShieldCheck size={17}/>}>
        <FeedWarning resource={system} label="System health"/>
        <div className="ws-mini-list"><div><div><strong>Personal risk</strong><span>Primary virtual balance protection</span></div><Pill tone={personal.data?.portfolio?.risk_state==="HEALTHY"?"green":"amber"}>{title(personal.data?.portfolio?.risk_state)}</Pill></div><div><div><strong>Personal reconciliation</strong><span>Persisted journal consistency</span></div><Pill tone={Array.isArray(personal.data?.reconciliation)&&!personal.data.reconciliation.length?"green":"amber"}>{Array.isArray(personal.data?.reconciliation)&&!personal.data.reconciliation.length?"Passed":"Check"}</Pill></div><div><div><strong>Data feed</strong><span>Official monitoring summary</span></div><Pill tone={system.data?.market_data?.state==="OK"?"green":"amber"}>{title(system.data?.market_data?.state)}</Pill></div><div><div><strong>Real-money mode</strong><span>Read from reported service configuration</span></div><Pill tone={system.data?.live_trading_enabled===false?"green":"amber"}>{system.data?.live_trading_enabled===false?"Disabled":"Verify"}</Pill></div></div>
      </Section></div>
    <Section title="Latest decisions" subtitle="Showing actual recorded outcomes; rejected setups are not missed guaranteed profits" icon={<Activity size={17}/>} right={<Segments value={filter} onChange={setFilter} options={["All","Qualified","Rejected"]}/> }>
      <SimpleTable head={["Time","Market","Strategy","Technical","Economics","Decision"]} rows={visible.map(r=>[
        <span className="ws-muted ws-nowrap">{time(r.timestamp)}</span>,<strong>{r.symbol}</strong>,<span>{strategyName(r.strategy_id)}</span>,<Pill tone={r.technical===true?"green":r.technical===false?"amber":"neutral"}>{r.technical===true?"Passed":r.technical===false?"Blocked":"Unknown"}</Pill>,<Pill tone={r.economic===true?"green":r.economic===false?"amber":"neutral"}>{r.economic===true?"Passed":r.economic===false?"Blocked":"Unknown"}</Pill>,<Pill tone={r.accepted?"green":"neutral"}>{r.accepted?"Accepted":"Waiting"}</Pill>
      ])} empty="No recorded evaluations for this filter."/>
    </Section>
  </>;
}

function SettingsBoard({ label }: {label?:string}) {
  const system=useResource("/api/monitoring/summary",{poll:20000});
  const paper=useResource("/api/personal-paper",{poll:20000});
  const ready=useResource("/readyz",{poll:30000});
  const state=system.data;
  return <>
    <div className="ws-kpis"><Metric label="Execution environment" value={ready.data?.live_trading_enabled===false?"Paper only":ready.data?"Review":"Checking"} tone={ready.data?.live_trading_enabled===false?"green":"amber"} icon={<LockKeyhole size={17}/>} note="Verify before changing any control"/><Metric label="Worker" value={title(state?.service?.worker)} tone={state?.service?.worker==="ok"?"green":"amber"} icon={<Activity size={17}/>} note="Legacy/official worker heartbeat"/><Metric label="Data source" value={title(state?.market_data?.state)} tone={state?.market_data?.state==="OK"?"green":"amber"} icon={<Radio size={17}/>} note="Reported market feed condition"/><Metric label="Personal account" value={title(paper.data?.portfolio?.control)} tone={paper.data?.portfolio?.control==="RUNNING"?"green":"amber"} icon={<Wallet size={17}/>} note="Primary simulated portfolio control"/></div>
    <Section title="Configuration and safety" subtitle="Overview of real monitoring values; the original tools remain available below" icon={<Settings2 size={17}/> }>
      <FeedWarning resource={ready} label="Execution mode"/>
      <FeedWarning resource={system} label="Monitoring"/>
      <div className="ws-setting-grid"><div><IconCircle tone={ready.data?.live_trading_enabled===false?"green":"amber"}><LockKeyhole size={20}/></IconCircle><strong>Exchange execution</strong><span>{ready.data?.live_trading_enabled===false?"Real trading disabled":"Execution mode not verified"}</span></div><div><IconCircle tone={paper.data?.reconciliation?.length===0?"green":"amber"}><ShieldCheck size={20}/></IconCircle><strong>Financial journal</strong><span>{paper.data?.reconciliation?.length===0?"Primary reconciliation passed":"Review reconciliation"}</span></div><div><IconCircle><Database size={20}/></IconCircle><strong>PostgreSQL</strong><span>{title(state?.service?.postgresql)}</span></div><div><IconCircle><Radio size={20}/></IconCircle><strong>Redis</strong><span>{title(state?.service?.redis)}</span></div></div>
    </Section>
    <Section title="Selected settings area" subtitle="A simplified entry point to the existing advanced controls" icon={<SlidersHorizontal size={17}/> }>
      <div className="ws-settings-selection"><IconCircle><Settings2 size={20}/></IconCircle><div><strong>{label??"Settings"}</strong><p>The detailed view below keeps the existing control confirmations, trading safeguards and operational reports intact.</p></div><Pill tone="amber">Review before changes</Pill></div>
    </Section>
  </>;
}

const viewMeta: Record<View, {title:string;intro:string;icon:ReactNode}> = {
  opportunities:{title:"Opportunity radar",intro:"See which market ideas have credible setups — and why others wait.",icon:<Gauge size={18}/>},
  strategies:{title:"Strategy studio",intro:"Compare measured paper outcomes without losing the research context.",icon:<FlaskConical size={18}/>},
  activity:{title:"Trading activity",intro:"Your actual virtual fills and decisions, in one readable timeline.",icon:<Activity size={18}/>},
  research:{title:"Research lab",intro:"Historical evidence, sample sizes and uncertainty — without the clutter.",icon:<BookOpen size={18}/>},
  insights:{title:"Decision insights",intro:"See exactly where signals qualify or fail, with clear safety checks.",icon:<ShieldCheck size={18}/>},
  settings:{title:"Control centre",intro:"System health and configuration, organized around safe operation.",icon:<Settings2 size={18}/>},
};
export function WorkspaceVisual({view,label,legacy}: {view:View;label?:string;legacy:ReactNode}) {
  const meta=viewMeta[view];
  return <div className="ws-shell" data-visual-release="ws-visual-20261105-v1">
    <header className="ws-hero"><div className="ws-hero-text"><div className="ws-kicker">{meta.icon}<span>PERSONAL PLAN / VISUAL WORKSPACE</span></div><h2>{meta.title}</h2><p>{meta.intro}</p></div><div className="ws-hero-badges"><Pill tone="green"><LockKeyhole size={12}/> Simulated mode</Pill><small>Real-money actions are outside these dashboard summaries.</small></div></header>
    <div className="ws-main">
      {view==="opportunities"&&<OpportunitiesBoard/>}
      {view==="strategies"&&<StrategiesBoard/>}
      {view==="activity"&&<ActivityBoard/>}
      {view==="research"&&<ResearchBoard/>}
      {view==="insights"&&<InsightsBoard/>}
      {view==="settings"&&<SettingsBoard label={label}/>}
    </div>
    <Advanced title={view==="settings"?`Full ${label??"settings"} tools`:"Detailed reports & original workspace"} help={view==="settings"?"Existing controls and confirmation steps remain unchanged":"Open the original screen, research tables and original evidence"}>{legacy}</Advanced>
    <p className="ws-disclaimer">Visual summaries are based on recorded application data. Some views show bounded recent windows. Research hypotheses, simulated fills and real-money performance are different evidence categories.</p>
  </div>;
}

