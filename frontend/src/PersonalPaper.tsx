import React, { useState } from "react";
import { useApi, useResource, type Row } from "./api";
import { date, money, percent, price, strategyName } from "./model";
import { Badge, CompactTable, Empty, EquityChart, Panel, Pnl, ResourceState } from "./ui";

export function PersonalPaper({ view = "overview" }: { view?: "overview" | "activity" | "strategies" | "opportunities" | "monitor" | "research" }) {
  const resource = useResource("/api/personal-paper", { poll: 15000 });
  const historical = useResource("/api/personal-paper/research", { enabled: view === "research", ttl: 60000 });
  const api = useApi();
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const d = resource.data;
  const p = d?.portfolio;
  const performance = d?.performance;
  const control = async (action: string) => {
    setBusy(true); setError("");
    try { await api.request(`/api/personal-paper/control/${action}`, "POST"); await api.load("/api/personal-paper", true); }
    catch (e) { setError(e instanceof Error ? e.message : "Control failed"); }
    finally { setBusy(false); }
  };
  if (!p) return <><ResourceState resource={resource} label="€7,000 paper portfolio" />{d?.state === "NOT_INITIALIZED" && d?.enabled && <Panel><h2>€7,000 virtual portfolio</h2><p>Waiting for the worker to initialize the isolated paper account.</p></Panel>}</>;
  return <section className="page-stack personal-paper" aria-label="Personal Plan shared paper portfolio">
    <ResourceState resource={resource} label="€7,000 paper portfolio" />
    <Panel>
      <div className="section-heading"><div><p className="eyebrow">Personal Plan · V4.7</p><h2>€7,000 virtual portfolio</h2></div><Badge>Paper only</Badge></div>
      <p>{d?.state === "PAPER_EXPERIMENTAL_ACTIVE" ? "Autonomous experimental execution active" : d?.state?.replaceAll("_", " ") ?? "Connecting to the paper account"} · One EUR pool shared by three selected strategies.</p>
      <p className="small muted">Execution profile {d?.manifest?.version ?? "unavailable"} · {d?.evidence_category === "SYNTHETIC_ACCEPTANCE" ? "DETERMINISTIC ACCEPTANCE — synthetic fixtures" : "Prospective paper evidence · live Revolut X observations"}. Official €500 and research shadows are separate.</p>
      {view === "overview" && <>
        <div className="kpi-grid">
          <div className="kpi"><span>Current equity</span><strong>{money(p?.equity)}</strong><small>Starting virtual balance {money(p?.initial_cash)}</small></div>
          <div className="kpi"><span>Total net result</span><strong><Pnl value={p?.total_net_pnl}/></strong><small>Today <Pnl value={p?.daily_equity_change}/></small></div>
          <div className="kpi"><span>Positions</span><strong>{performance?.open_positions ?? "—"} open</strong><small>{performance?.closed_positions ?? "—"} completed</small></div>
          <div className="kpi"><span>Simulated execution</span><strong>{performance?.buy_fills ?? "—"} buys · {performance?.sell_fills ?? "—"} sells</strong><small>Filled broker records</small></div>
        </div>
        <div className="balance-summary">
          <div><span>Available cash</span><strong>{money(p?.available_cash)}</strong></div>
          <div><span>Reserved capital</span><strong>{money(p?.reserved_cash)}</strong></div>
          <div><span>Open exposure</span><strong>{money(p?.open_exposure)}</strong></div>
          <div><span>Realized P&L</span><strong><Pnl value={p?.realized_pnl}/></strong></div>
          <div><span>Unrealized P&L</span><strong><Pnl value={p?.unrealized_pnl}/></strong></div>
          <div><span>Fees paid</span><strong>{money(performance?.fees_eur)}</strong></div>
        </div>
        <div className="balance-summary">
          <div><span>Win rate</span><strong>{percent(performance?.win_rate)}</strong></div>
          <div><span>Net expectancy</span><strong>{money(performance?.expectancy)}</strong></div>
          <div><span>Profit factor</span><strong>{performance?.profit_factor ?? "Insufficient sample"}</strong></div>
          <div><span>Capital utilization</span><strong>{percent(performance?.capital_utilization)}</strong></div>
          <div><span>Modeled slippage / impact</span><strong>{money(performance?.modeled_slippage_and_impact_eur)}</strong></div>
        </div>
        <EquityChart rows={d?.equity_history ?? []} title="Shared portfolio equity" caption="Virtual EUR · separate from official and shadow accounts"/>
      </>}
      {(view === "overview" || view === "monitor") && <>
        <p>Last evaluation {date(d?.scan?.observed_at, true)} · {d?.scan?.strategies_evaluated ?? 0} strategy/market evaluations · {d?.scan?.markets?.length ?? 0} markets.</p>
        <p>Position monitor {date(d?.position_monitor?.heartbeat, true)} · Financial reconciliation {d?.reconciliation?.length === 0 ? "passed" : "unverified or requires attention"} · Risk {p?.risk_state ?? "unknown"}.</p>
        <div className="section-footer"><button disabled={busy || !p} onClick={() => control(p?.control === "RUNNING" ? "pause" : "resume")}>{p?.control === "RUNNING" ? "Pause paper entries" : "Resume paper entries"}</button><button disabled={busy || !p} onClick={() => control("emergency")}>Close paper positions safely</button></div>
        {error && <p role="alert" className="notice warning">{error}</p>}
      </>}
      {d?.runtime_matches === false && <p className="notice warning" role="alert">Execution source differs from the frozen experiment. New entries are suspended; protective monitoring continues.</p>}
      <p className="small muted">{performance?.closed_positions ?? 0} completed positions. Predictive edge is unvalidated. Current drawdown {percent(p?.current_drawdown)} · Maximum {percent(performance?.max_drawdown)}.</p>
    </Panel>
    {(view === "strategies" || view === "overview") && <Panel><h2>Competing strategies · shared capital</h2><CompactTable label="Primary paper strategies" rows={d?.strategies ?? []} columns={[
      { label: "Strategy", render: (r: Row) => <><strong>{strategyName(r.strategy_id)}</strong><div className="small muted">{r.strategy_version}</div></> },
      { label: "Status", render: () => <Badge>Experimental paper</Badge> },
      { label: "Completed", render: (r: Row) => r.closed_positions },
      { label: "Net realized", render: (r: Row) => <Pnl value={r.net_realized_pnl}/> },
      { label: "Expectancy / position", render: (r: Row) => money(r.expectancy) },
      { label: "Evidence", render: (r: Row) => r.confidence.replaceAll("_", " ").toLowerCase() },
    ]}/><p className="small muted">Frozen parameters. Equal prior weights; no automatic promotion based on a handful of trades. Maximum €700 per position, €35 planned stop risk, €140 aggregate stop risk and €2,100 crypto cluster exposure. Losses and missed opportunities remain recorded.</p></Panel>}
    {view === "research" && <>
      <Panel><h2>Continuous prospective review</h2><p>{d?.research_review?.conclusion ?? "Waiting for the first hourly evidence review"}</p><p className="small muted">Evidence cutoff {date(d?.research_review?.evidence_cutoff, true)}. Active parameters are frozen. Research proposals require a separate evaluation identity.</p>
        <CompactTable label="Prospective research proposals" rows={d?.research_review?.proposals ?? []} columns={[
          { label: "Version", render: (r: Row) => r.version },{ label: "Hypothesis", render: (r: Row) => r.hypothesis },{ label: "Next evaluation", render: (r: Row) => r.required_evaluation },
        ]}/>
      </Panel>
      <Panel><h2>Historical strategy comparison</h2><p className="small muted">Coinbase EUR historical proxy · original €500 research sizing · reused chronological holdout. This is separate from the €7,000 Revolut X prospective ledger. No validated edge is established.</p><ResourceState resource={historical} label="Historical evidence"/>
        <CompactTable label="Historical strategies and timeframes" rows={historical.data?.results ?? []} columns={[
          { label: "Strategy", render: (r: Row) => strategyName(r.strategy_id) },{ label: "Timeframe", render: (r: Row) => r.timeframe },
          { label: "Status", render: (r: Row) => r.status?.replaceAll("_", " ").toLowerCase() },
          { label: "Holdout positions", render: (r: Row) => (r.segments ?? r.trials?.[0]?.segments)?.reused_holdout?.trades ?? "—" },
          { label: "Holdout net P&L", render: (r: Row) => money((r.segments ?? r.trials?.[0]?.segments)?.reused_holdout?.net_profit) },
          { label: "Limitation", render: (r: Row) => r.reason ?? r.limitation ?? "Descriptive reused sample; no automatic strategy promotion" },
        ]}/>
      </Panel>
    </>}
    {view === "activity" && <>
      <Panel><h2>Primary portfolio positions</h2><CompactTable label="Primary paper positions" rows={d?.positions ?? []} empty={<Empty title="No primary positions yet">Only qualifying opportunities become durable broker fills.</Empty>} columns={[
        { label: "Market / strategy", render: (r: Row) => <><strong>{r.symbol}</strong><div>{strategyName(r.strategy_id)}</div></> },
        { label: "Quantity", render: (r: Row) => r.quantity },
        { label: "Entry", render: (r: Row) => price(r.average_entry_price) },
        { label: "Stop", render: (r: Row) => price(r.protective_stop) },
        { label: "Remaining targets", render: (r: Row) => r.take_profit_targets?.map(price).join(" · ") },
        { label: "Expires", render: (r: Row) => date(r.expires_at, true) },
        { label: "Realized", render: (r: Row) => <Pnl value={r.realized_pnl}/> },
        { label: "Status", render: (r: Row) => r.closed_at ? "Closed" : "Open" },
      ]}/></Panel>
      <Panel><h2>Persisted simulated orders</h2><CompactTable label="Primary paper orders" rows={d?.orders ?? []} empty={<Empty title="No orders recorded">Research observations are separate from orders.</Empty>} columns={[
        { label: "Time", render: (r: Row) => date(r.created_at, true) }, { label: "Market", render: (r: Row) => r.symbol },
        { label: "Side", render: (r: Row) => r.side }, { label: "Status", render: (r: Row) => r.status },
        { label: "Strategy / type", render: (r: Row) => <>{strategyName(r.strategy_id)}<div>{r.order_type}</div><div className="small muted">{r.execution_profile}</div></> },
        { label: "Fees", render: (r: Row) => money(r.fee_eur) },
        { label: "Reason", render: (r: Row) => r.rejection_reason?.replaceAll("_", " ") || "—" },
        { label: "Quantity", render: (r: Row) => r.quantity }, { label: "Filled price", render: (r: Row) => price(r.average_fill_price) },
      ]}/><p className="small muted">Latest 80 orders. All fills, fees, order transitions and journals remain durable in PostgreSQL.</p></Panel>
    </>}
    {(view === "opportunities" || view === "monitor") && <Panel><h2>Execution qualification at actual account size</h2><CompactTable label="Primary paper opportunity admission" rows={d?.scan?.rows ?? []} columns={[
      { label: "Market / strategy", render: (r: Row) => <>{r.symbol}<div className="small muted">{strategyName(r.strategy_id)}</div></> },
      { label: "Technical", render: (r: Row) => r.technical ? "Qualified" : "Waiting" },
      { label: "Net economics", render: (r: Row) => r.economic ? "Feasible" : "Not qualified" },
      { label: "Broker outcome", render: (r: Row) => r.execution?.replaceAll("_", " ") },
      { label: "Reason", render: (r: Row) => r.reasons?.join(", ").replaceAll("_", " ") || "Account admission required" },
    ]}/><p className="small muted">Economics use current ask/bid depth, assumed taker fees and modeled slippage. USD markets remain excluded until a separate FX ledger is verified.</p></Panel>}
  </section>;
}
