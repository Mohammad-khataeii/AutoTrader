import { useResource } from "./api";
import "./TradingOperations.css";

type Row = Record<string, any>;
type TradeState = "blocked" | "waiting" | "armed" | "unknown";
type OrderRow = { key:string; symbol:string; side:string; state:string; quantity:unknown; filled:unknown; type:string; requestPrice:unknown; fillPrice:unknown; stopPrice:unknown; targetPrice:unknown; at:unknown; source:string; reason?:string };

const list = (value:unknown):Row[] => Array.isArray(value) ? value : [];
const label = (value:unknown) => value == null || value === "" ? "—" : String(value).replace(/_/g, " ");
const money = (value:unknown):string => value == null || value === "" || !Number.isFinite(Number(value)) ? "—" : new Intl.NumberFormat("en-US",{style:"currency",currency:"USD",maximumFractionDigits:5}).format(Number(value));
const stamp = (value:unknown):string => {
  if (typeof value !== "string" || !value) return "—";
  const date = new Date(value);
  return Number.isFinite(date.getTime()) ? date.toLocaleString() : "—";
};
const fresh = (value:unknown, minutes:number):boolean => {
  if(typeof value !== "string") return false;
  const age=Date.now()-Date.parse(value);
  return Number.isFinite(age) && age >= -60_000 && age <= minutes*60_000;
};
const readable = (code:unknown):string => {
  const raw=String(code??"").trim();
  const known:Record<string,string>={
    BROKER_READ_ONLY:"Server configuration disables broker order submission.",
    BROKER_PAUSED:"The persistent paper-account pause is active.",
    BROKER_CHECK_FAILED:"The last broker verification failed.",
    NO_CERTIFIED_BENCHMARK:"Required certified market data is unavailable.",
    NO_CERTIFIED_CURRENT_SIGNALS:"There are no certified signals for the completed market session.",
    NO_APPROVED_BROKER_SIGNAL:"The latest strategy check did not approve a trade.",
    WAITING_FOR_NEXT_CORE_OPEN_WINDOW:"The EOD strategy is waiting for its next eligible US-market entry window.",
    UNCERTAIN_BROKER_INTENT:"An uncertain previous order must be reconciled before submitting another.",
    PROTECTION_MONITOR_UNAVAILABLE:"The protective-order monitor is unavailable; do not assume positions are protected.",
    insufficient_completed_history:"At least 220 completed daily and 220 completed hourly bars are required per crypto pair.",
    crypto_separate_paper_account_not_configured:"Dedicated crypto Alpaca Paper credentials are missing.",
    read_only_dedicated_paper_account:"Crypto broker observations are read-only; automatic paper orders are disabled."
  };
  return known[raw] || raw.replace(/_/g," ").replace(/\s+/g," ") || "No detailed reason was provided by the server.";
};
function Indicator({ title, state, reasons, checked, note }:{
  title:string;state:TradeState;reasons:string[];checked?:unknown;note:string;
}){
  const name=state==="armed"?"PAPER ORDERS ARMED":state==="waiting"?"WAITING":state==="blocked"?"NOT TRADING":"UNVERIFIED";
  return <section className={"to-status to-"+state} aria-label={title+" status"} role="status">
    <div className="to-status-heading"><div><p className="to-eyebrow">{title} · AUTOMATION STATUS</p>
      <h3><span className="to-dot" aria-hidden="true"/>{name}</h3></div>
      <div className="to-checked">Last evaluation: {stamp(checked)}</div></div>
    <p className="to-caption">{note}</p>
    <ul className="to-reasons">{reasons.map((reason,i)=><li key={i}>{reason}</li>)}</ul>
  </section>;
}
function Table({rows, empty, kind}:{rows:OrderRow[];empty:string;kind:"stocks"|"crypto"}){
 return <div className="to-scroll"><table className="to-table"><thead><tr>
   <th>Placed / updated</th><th>Asset</th><th>Action</th><th>Order state</th><th>Qty / notional</th><th>Requested price</th>
   <th>Filled qty</th><th>Actual fill</th><th>Stop-loss</th><th>Take-profit</th><th>Source / explanation</th>
 </tr></thead><tbody>{rows.length?rows.map(r=><tr key={r.key}>
   <td>{stamp(r.at)}</td><td><strong>{r.symbol}</strong></td><td>{label(r.side).toUpperCase()}</td>
   <td><span className={"to-order-state "+(/FILLED|ACKNOWLEDGED/.test(r.state.toUpperCase())?"to-order-active":"")}>{label(r.state)}</span></td>
   <td>{label(r.quantity)}</td><td>{r.type==="market"?"Market (no limit)":money(r.requestPrice)}</td>
   <td>{label(r.filled)}</td><td>{money(r.fillPrice)}</td><td>{money(r.stopPrice)}</td><td>{money(r.targetPrice)}</td>
   <td><span className="to-source">{r.source}</span>{r.reason&&<small>{readable(r.reason)}</small>}</td>
 </tr>):<tr><td colSpan={11} className="to-empty">{empty}</td></tr>}</tbody></table>
 {kind==="crypto"&&<p className="to-foot">Crypto market orders have no pre-set limit price. The current crypto API does not expose actual execution prices; an empty fill price is unknown, not zero. Crypto TP/SL levels are software-managed and not broker-native stop orders.</p>}
 </div>;
}
const recentFirst = (rows:OrderRow[]) => rows.sort((a,b)=>String(b.at??"").localeCompare(String(a.at??""))).slice(0,50);

export function StocksTradingOperations({dashboard:d,health:h,isBroker,error}:{dashboard:Row;health:Row;isBroker:boolean;error?:string}){
  const protection=useResource("/api/stockswatch/profit-protection",{enabled:isBroker,poll:30000,ttl:12000});
  const p:Row=protection.data??{};
  const broker:Row=d.broker_account??h.broker_connection??{};
  const cycle:Row=h.cycle??d.status??{};
  const evaluation:Row=d.status?.paper??cycle.paper??{};
  const reasons:string[]=[];
  let state:TradeState="unknown";
  if(error) reasons.push("Cannot verify the trading state: "+error);
  else if(!isBroker){state="blocked";reasons.push("This screen is connected to the local simulator, not the Alpaca Paper execution backend.");}
  else {
    const blockers:string[]=[];
    if(broker.status!=="CONNECTED")
      blockers.push("Alpaca Paper broker status: "+label(broker.status||"UNAVAILABLE")+". "+(broker.reason?readable(broker.reason):"No verified recent broker snapshot."));
    if(broker.orders_enabled!==true)
      blockers.push("Server switch STOCKSWATCH_ALPACA_PAPER_ALLOW_ORDERS is OFF. Data collection can run without placing orders.");
    if(broker.paused!==false)
      blockers.push("The stock paper account's persistent pause is ON. New buys are not admitted.");
    if(h.provider&&h.provider!=="alpaca")
      blockers.push("The execution data provider is "+label(h.provider)+"; certified Alpaca observations are required.");
    const result=String(evaluation.status||cycle.state||"");
    if(["BROKER_CHECK_FAILED","PROTECTION_MONITOR_UNAVAILABLE","UNCERTAIN_BROKER_INTENT"].includes(result))
      blockers.push(readable(result)+(evaluation.reason?" — "+readable(evaluation.reason):""));
    if(broker.status==="CONNECTED"&&!fresh(broker.as_of,3))
      blockers.push("Broker snapshot is older than 3 minutes or has no valid timestamp. Current order admission cannot be verified.");
    if(blockers.length){state="blocked";reasons.push(...blockers);}
    else if(cycle.components?.market_session&&cycle.components.market_session!=="CORE_OPEN"){
      state="waiting";
      reasons.push("US equity session: "+readable(cycle.components.market_session)+". New EOD entries require an eligible market window.");
    } else {state="armed";reasons.push("Alpaca Paper order admission is ON, the account is connected, and the persistent pause is OFF.");}
    if(result && result!=="BROKER_ACKNOWLEDGED") reasons.push("Latest strategy decision: "+readable(result)+(evaluation.reason?" — "+readable(evaluation.reason):""));
  }
  if(!error&&cycle.completed_at&&!fresh(cycle.completed_at,40)) reasons.push("The scheduled market scan appears stale; last completed at "+stamp(cycle.completed_at)+".");
  const open=list(d.pending_orders),closed=list(d.order_history),intents=list(d.broker_intents);
  const observed=new Set<string>();
  const orders:OrderRow[]=[];
  for(const [source,items] of [["Alpaca Paper · open",open],["Alpaca Paper · history",closed]] as [string,Row[]][]){
    for(const r of items){
      const id=String(r.client_order_id||r.id||"");
      if(id) observed.add(id);
      const local=intents.find(x=>x.client_id===r.client_order_id);
      orders.push({key:source+":"+id,symbol:label(r.symbol),side:label(r.side),state:label(r.state),
        quantity:r.qty,filled:r.filled_qty,type:String(r.type||"").toLowerCase(),requestPrice:r.limit_price,
        fillPrice:r.filled_avg_price,stopPrice:r.stop_price,targetPrice:r.take_profit_price,at:r.filled_at||r.submitted_at||r.created_at,
        source,reason:local?.diagnostic??local?.reason});
    }
  }
  for(const r of intents){
    if(observed.has(String(r.client_id||""))) continue;
    orders.push({key:"intent:"+r.client_id,symbol:label(r.symbol),side:label(r.side),state:label(r.state)+" / "+label(r.broker_status||"unverified"),
      quantity:r.qty,filled:null,type:String(r.type||"limit").toLowerCase(),requestPrice:r.limit_price??r.requested_limit_price,
      fillPrice:null,stopPrice:null,targetPrice:null,at:r.updated_at||r.created_at,source:"Local order intent · broker proof not shown",reason:r.diagnostic??r.reason});
  }
  const holdings=list(d.positions);
  const protectionRows=list(p.positions);
  const candidates=list(d.signals).slice(0,10);
  const rejected=list(evaluation.why_no_trade).slice(0,10);
  return <div className="to-root" data-trading-observability="stocks">
    <Indicator title="StocksWatch" state={state} reasons={reasons} checked={broker.as_of||cycle.completed_at}
      note="An armed strategy can be waiting without submitting any orders. A healthy scanner is not proof of an executed trade."/>
    <section className="to-panel">
      <div className="to-heading"><h3>Orders: pending, submitted, filled and canceled</h3><span>{open.length} open broker orders · {closed.length} recent broker orders · {intents.length} local intents</span></div>
      <Table kind="stocks" rows={recentFirst(orders)} empty="No broker orders or local submission attempts are available in this snapshot."/>
      <p className="to-foot">Alpaca Paper broker status is authoritative. A local intent is never displayed as a confirmed fill. Broker history and fills may be limited to recent records.</p>
    </section>
    <section className="to-panel">
      <div className="to-heading"><h3>Held shares and exit protection</h3><span>Broker-verified stops only; proposed targets are not active orders</span></div>
      <div className="to-scroll"><table className="to-table"><thead><tr><th>Stock</th><th>Shares</th><th>Entry</th><th>Current mark</th><th>Unrealized</th><th>Broker stop-loss</th><th>Planned SL</th><th>Target</th><th>Protection state / reason</th></tr></thead><tbody>
        {holdings.length?holdings.map(x=>{const q=protectionRows.find(y=>y.symbol===x.symbol);const verified=q?.broker_state==="ACTIVE"&&q?.verified_broker_stop!=null;return <tr key={x.symbol}>
          <td><strong>{x.symbol}</strong></td><td>{label(x.qty)}</td><td>{money(x.avg_cost)}</td><td>{money(x.mark)}</td><td>{money(x.unrealized)}</td>
          <td>{verified?money(q?.verified_broker_stop):"NOT VERIFIED"}</td><td>{money(q?.planned_stop??q?.initial_stop)}</td><td>{money(q?.target)}</td>
          <td>{verified?"Broker OCO verified":label(q?.broker_state||"UNPROTECTED")}{q?.reason&&<small>{readable(q.reason)}</small>}</td></tr>}):
        <tr><td colSpan={9} className="to-empty">No broker-held stock positions in the latest verified view.</td></tr>}</tbody></table></div>
      {protection.error&&<p className="to-foot">Protection API unavailable: {protection.error}. No stop or target is assumed active.</p>}
    </section>
    <section className="to-panel">
      <div className="to-heading"><h3>Potential buys — NOT orders</h3><span>Signals do not become orders until all execution gates pass</span></div>
      <div className="to-scroll"><table className="to-table"><thead><tr><th>Symbol</th><th>Signal</th><th>Score</th><th>Execution decision</th><th>Why not bought</th><th>Order price</th></tr></thead><tbody>
        {candidates.length?candidates.map((x,i)=>{const gate=rejected.find(y=>y.symbol===x.symbol);return <tr key={x.symbol+"-"+i}>
          <td><strong>{x.symbol}</strong></td><td>{label(x.action??x.regime??"WATCH")}</td><td>{label(x.score)}</td>
          <td>{label(gate?.action??"RESEARCH ONLY")}</td><td>{readable(gate?.reason??evaluation.reason??evaluation.status??"No approved broker order")}</td>
          <td>Not priced / not submitted</td></tr>}):
        <tr><td colSpan={6} className="to-empty">No eligible candidates from the last completed strategy scan.</td></tr>}</tbody></table></div>
    </section>
  </div>;
}

/** Distinct top-of-page status: no order-journal polling or duplicated tables. */
export function CryptoTradingStatus({dashboard:d,error}:{dashboard:Row;error?:string}){
  const paper:Row=d.broker_snapshot??{};
  const assets=list(d.assets),jobs=list(d.history_jobs),signals=list(d.signals);
  const finished=jobs.filter(x=>x.state==="COMPLETE").reduce((s,x)=>s+Number(x.n||0),0);
  const total=jobs.reduce((s,x)=>s+Number(x.n||0),0);
  const reasons:string[]=[];
  let state:TradeState="unknown";
  if(error){reasons.push("Cannot verify AlpacaCrypto: "+error);}
  else{
    if(!d.broker_account_verified) reasons.push("Dedicated AlpacaCrypto Paper account has not been verified. Check ALPACA_CRYPTO_PAPER_KEY, ALPACA_CRYPTO_PAPER_SECRET and ALPACA_CRYPTO_PAPER_ACCOUNT_ID on the server.");
    if(!paper.observed_at) reasons.push("No verified dedicated crypto broker account snapshot is available.");
    else if(!fresh(paper.observed_at,5)) reasons.push("The crypto broker snapshot is stale: "+stamp(paper.observed_at)+".");
    if(d.paper_orders_enabled!==true) reasons.push("Server switch ALPACA_CRYPTO_ALLOW_PAPER_ORDERS is OFF (research-only mode).");
    if(d.paused!==false) reasons.push("Crypto entry admission is persistently paused.");
    const eligible=assets.filter(x=>x.eligible===1).length;
    if(eligible<assets.length) reasons.push(eligible+" of "+assets.length+" pairs are broker-verified as eligible. Unverified assets cannot be bought.");
    if(total>0&&finished<total) reasons.push("Historical backfill: "+finished+"/"+total+" jobs complete. Signal readiness is checked separately per symbol.");
    if(!fresh(d.last_cycle,5)) reasons.push("Crypto worker cycle is stale or not yet observed.");
    if(d.last_error) reasons.push("Last worker error: "+readable(d.last_error));
    const waits=signals.filter(x=>x.action==="WAIT");
    if(waits.length) reasons.push(waits.length+" of "+signals.length+" latest signals say WAIT; e.g. "+label(waits[0].symbol)+": "+readable(waits[0].reason)+".");
    const blocked=!d.broker_account_verified || !paper.observed_at || !fresh(paper.observed_at,5) || d.paper_orders_enabled!==true || d.paused!==false || !!d.last_error;
    state=blocked?"blocked":(!fresh(d.last_cycle,5)?"unknown":"armed");
    if(!blocked&&!signals.some(x=>x.action==="BUY")){state="waiting";reasons.unshift("Paper engine is authorized but no approved crypto BUY signal is present.");}
    if(!reasons.length) reasons.push("Paper order admission is enabled; individual trades still require fresh quotes and all risk gates.");
  }
  return <Indicator title="AlpacaCrypto" state={state} reasons={reasons} checked={d.last_cycle}
    note="The 24/7 research scanner is separate from paper order permission. A verified dedicated Alpaca account is required for execution."/>;
}

export function CryptoTradingOperations({dashboard:d,error}:{dashboard:Row;error?:string}){
  const brokerJournal=useResource("/api/stockswatch/alpaca-crypto/orders",{poll:20000,ttl:10000});
  const verifiedBook:Row=brokerJournal.data??{};
  const brokerOrders=list(verifiedBook.orders);
  const paper:Row=d.broker_snapshot??{};
  const assets=list(d.assets),jobs=list(d.history_jobs),signals=list(d.signals);
  const positions=list(paper.positions),intents=list(d.intents),managed=list(d.managed);
  const finished=jobs.filter(x=>x.state==="COMPLETE").reduce((s,x)=>s+Number(x.n||0),0);
  const total=jobs.reduce((s,x)=>s+Number(x.n||0),0);
  const orders:OrderRow[]=intents.map((x,i)=>{
    const verified=verifiedBook.available===true?brokerOrders.find(o=>o.client_order_id===x.client_id):undefined;
    const levels=managed.find(m=>m.symbol===x.symbol);
    return {key:String(x.client_id??i),symbol:label(x.symbol),side:label(x.side),
      state:verified?label(verified.state):label(x.broker_status||x.state),
      quantity:verified?.notional!=null?money(verified.notional)+" notional":verified?.qty??(x.notional!=null?money(x.notional)+" notional":label(x.qty)),
      filled:verified?.filled_qty??null,type:String(verified?.type||"market").toLowerCase(),
      requestPrice:verified?.limit_price??null,fillPrice:verified?.filled_avg_price??null,
      stopPrice:levels?.stop,targetPrice:levels?.target,
      at:verified?.filled_at||verified?.submitted_at||verified?.created_at||x.created_at,
      source:verified?"Alpaca Paper · broker-verified":x.broker_status?"Local intent · cached broker status":"Local intent · broker not verified",reason:x.reason
    };
  });
  return <div className="to-root" data-trading-observability="crypto">
    <section className="to-panel">
      <div className="to-heading"><h3>Crypto paper orders and execution journal</h3><span>{intents.length} recorded intents · {verifiedBook.available===true?label(verifiedBook.open_broker_orders):paper.open_order_count==null?"Unknown":label(paper.open_order_count)} open broker orders</span></div>
      <Table kind="crypto" rows={recentFirst(orders)} empty="No AlpacaCrypto paper orders have been recorded. Scanner signals are not orders."/>
      <p className="to-foot">{verifiedBook.available===true
        ?"Verified paper fill price, fill quantity, and order state are read directly from Alpaca; the visible broker history is limited to recent orders."
        :("Live broker order detail unavailable"+(verifiedBook.reason?": "+readable(verifiedBook.reason):brokerJournal.error?": "+brokerJournal.error:"; waiting for verified paper account")+". Cached intent states are not proof of a current fill.")}</p>
    </section>
    <section className="to-panel">
      <div className="to-heading"><h3>Held crypto and software TP / SL</h3><span>These are monitored software thresholds, not broker-native stop orders</span></div>
      <div className="to-scroll"><table className="to-table"><thead><tr><th>Pair</th><th>Quantity</th><th>Market value</th><th>Unrealized</th><th>Software SL</th><th>Software TP</th><th>Protection</th></tr></thead><tbody>
        {positions.length?positions.map((x,i)=>{const symbol=String(x.symbol||"");const m=managed.find(y=>String(y.symbol).replace("/","")===symbol.replace("/",""));return <tr key={symbol+i}>
          <td><strong>{symbol}</strong></td><td>{label(x.qty)}</td><td>{money(x.market_value)}</td><td>{money(x.unrealized_pl)}</td>
          <td>{money(m?.stop)}</td><td>{money(m?.target)}</td><td>{m?"Software-managed; execution not guaranteed":"No owned protection verified"}</td></tr>}):
        <tr><td colSpan={7} className="to-empty">No dedicated crypto broker holdings reported in the latest snapshot.</td></tr>}</tbody></table></div>
    </section>
    <section className="to-panel">
      <div className="to-heading"><h3>Scanner opportunities — not submitted orders</h3><span>Data is research midpoints, not executable quotes</span></div>
      <div className="to-scroll"><table className="to-table"><thead><tr><th>Pair</th><th>Signal</th><th>Research price</th><th>Proposed SL</th><th>Proposed TP</th><th>Last evaluation</th><th>Exact reason</th></tr></thead><tbody>
        {signals.length?signals.map(x=><tr key={x.symbol}><td><strong>{x.symbol}</strong></td><td>{label(x.action)}</td><td>{money(x.price)}</td>
        <td>{money(x.stop)}</td><td>{money(x.target)}</td><td>{stamp(x.as_of||x.evaluated_at)}</td><td>{readable(x.reason)}</td></tr>):
        <tr><td colSpan={7} className="to-empty">No crypto signals evaluated yet.</td></tr>}</tbody></table></div>
    </section>
  </div>;
}
