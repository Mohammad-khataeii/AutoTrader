import React from "react";
import { type Row } from "./api";
import { date, money, price, strategyName } from "./model";
import { Badge, Empty, Panel, Pnl } from "./ui";

const duration = (value: unknown) => value == null ? "Unavailable" : `${Math.floor(Number(value)/3600)}h ${Math.floor(Number(value)%3600/60)}m ${Math.floor(Number(value)%60)}s`;
export function TradeReports({rows = []}: {rows?: Row[]}) {
  return <Panel className="trade-reports"><div className="section-heading"><h2>Completed position reports</h2><Badge>From the ledger</Badge></div>
    <p className="small muted">Entry evidence, actual exit and costs for each completed position. Expected profitability remains unknown.</p>
    {!rows.length && <Empty title="No completed positions">A report appears when a paper position closes.</Empty>}
    {rows.map(r=><details key={r.position_id} className="trade-report">
      <summary><strong>{r.symbol}</strong><span>{strategyName(r.strategy_id)}</span><span>{r.exit_reasons?.join(" · ") || "Exit unavailable"}</span><Pnl value={r.net_pnl_eur}/></summary>
      <div className="trade-report-body">
        <p>{r.explanation}</p>
        <dl className="trade-report-grid">
          <div><dt>Price P&amp;L before fees</dt><dd><Pnl value={r.gross_price_pnl_eur}/></dd></div>
          <div><dt>Total fees</dt><dd>{money(r.fees_eur)}</dd></div>
          <div><dt>Net P&amp;L</dt><dd><Pnl value={r.net_pnl_eur}/></dd></div>
          <div><dt>Realized risk multiple</dt><dd>{r.realized_r == null ? "Unavailable" : `${Number(r.realized_r).toFixed(2)}R`}</dd></div>
          <div><dt>Entry → exit</dt><dd>{price(r.entry_price)} → {price(r.exit_price)}</dd></div>
          <div><dt>Original stop</dt><dd>{price(r.initial_stop)}</dd></div>
          <div><dt>TP1 · TP2 · TP3</dt><dd>{r.targets?.map((t:string)=>price(t)).join(" · ")}</dd></div>
          <div><dt>Planned → actual holding</dt><dd>{duration(r.planned_holding_seconds)} → {duration(r.actual_holding_seconds)}</dd></div>
          <div><dt>Opened</dt><dd>{date(r.opened_at,true)}</dd></div><div><dt>Closed</dt><dd>{date(r.closed_at,true)}</dd></div>
          <div><dt>Planned net reward / risk</dt><dd>{r.expected_net_reward_risk == null ? "Unavailable" : Number(r.expected_net_reward_risk).toFixed(2)}</dd></div>
          <div><dt>Slippage / impact in prices</dt><dd>{money(r.modeled_slippage_and_impact_eur)}</dd></div>
          <div><dt>Entry regime</dt><dd>{r.entry_regime?.trend ?? "Unavailable"} · BTC/ETH {r.entry_regime?.benchmark ?? "unavailable"}</dd></div>
          <div><dt>Exit regime</dt><dd>{r.exit_regime?.local_trend ?? "Not recorded at exit"}</dd></div>
        </dl>
        <p className="small muted">{r.cost_note}</p>
        <h3>Why the entry qualified</h3><ul>{Object.entries(r.entry_reason ?? {}).map(([condition,passed])=><li key={condition}>{condition.replace(/_/g," ")}: {passed ? "passed" : "failed"}</li>)}</ul>
        {!!r.entry_concerns_known_then?.length && <><h3>Quality concerns visible at entry</h3><ul>{r.entry_concerns_known_then.map((c:string)=><li key={c}>{c}</li>)}</ul><p className="small muted">The reviewed experimental policy checks these concerns before new entries. It cannot guarantee a winning trade.</p></>}
        {!!r.issues?.length && <div className="notice warning"><strong>Record review</strong>{r.issues.map((issue:string)=><p key={issue}>{issue}</p>)}</div>}
        <details><summary>Fill evidence and attribution</summary><div className="trade-fill-evidence">{r.fills?.map((f:Row)=><div key={f.fill_id}><strong>{f.side} · {date(f.timestamp,true)}</strong><p>{f.quantity} at {price(f.price)} · fee {money(f.fee_eur)} · {f.exit_reason ?? "entry"}</p><p className="small">Strategy {strategyName(f.strategy_id)} · original raw label {f.raw_strategy_id}</p><p className="small muted">Observed bid {price(f.book?.bids?.[0]?.[0])} / ask {price(f.book?.asks?.[0]?.[0])} · modeled slippage {f.slippage_bps_assumption ?? "unavailable"} bps. Order {f.order_id}</p></div>)}</div></details>
      </div>
    </details>)}
    <p className="small muted">Latest 80 completed positions. Historical fills and original labels are preserved; corrected strategy attribution follows the entry plan.</p>
  </Panel>;
}
