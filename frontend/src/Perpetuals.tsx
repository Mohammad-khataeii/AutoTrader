import { lazy, Suspense, useMemo, useState, type ReactNode } from "react";
import {
  Activity, ArrowDownRight, ArrowRight, ArrowUpRight, BarChart3, ChevronDown,
  Clock3, Coins, Gauge, Layers3, PauseCircle, PlayCircle, Radio, Search,
  ShieldCheck, TrendingUp, Wallet,
} from "lucide-react";
import { errorMessage, useApi, useResource, type Row } from "./api";
import { ResourceState, Technical } from "./ui";
import "./PerpetualsDashboard.css";

/* The original, full-detail page is retained for historical audit and research. */
const OriginalPage = lazy(() => import("./PerpetualsLegacy").then(m => ({ default: m.Perpetuals })));
const BTC_URL = "/api/perpetuals";
const MULTI_URL = "/api/perpetuals/multi";
type Desk = "multi" | "btc";
type Tone = "good" | "bad" | "warn" | "plain";

const numeric = (value: unknown): number | null =>
  value === null || value === undefined || value === "" || !Number.isFinite(Number(value)) ? null : Number(value);
const format = (value: unknown, digits = 2) => {
  const v = numeric(value);
  return v === null ? "—" : v.toLocaleString("en-US", { minimumFractionDigits: digits, maximumFractionDigits: digits });
};
const cash = (value: unknown) => numeric(value) === null ? "—" : `${format(value)} USDT`;
const percentage = (value: unknown, digits = 2) => numeric(value) === null ? "—" : `${format(value, digits)}%`;
const signedCash = (value: unknown) => {
  const v = numeric(value);
  return v === null ? "—" : `${v > 0 ? "+" : v < 0 ? "−" : ""}${format(Math.abs(v))} USDT`;
};
const toneOf = (value: unknown): Tone => (numeric(value) ?? 0) > 0 ? "good" : (numeric(value) ?? 0) < 0 ? "bad" : "plain";
const label = (value: unknown) => String(value ?? "Unknown").replace(/_/g, " ").replace(/\s+/g, " ").trim().toLowerCase().replace(/^./, c => c.toUpperCase());
const direction = (side: unknown) => Number(side) === 1 ? "Long" : Number(side) === -1 ? "Short" : label(side);
const timestamp = (value: unknown) => {
  const parsed = numeric(value);
  if (parsed === null && typeof value !== "string") return "—";
  const d = new Date(parsed ?? String(value));
  return Number.isNaN(d.getTime()) ? "—" : d.toLocaleString(undefined, { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" });
};
const shorten = (value: unknown, max = 44) => {
  const text = label(value);
  return text.length <= max ? text : `${text.slice(0, max - 1)}…`;
};
const sum = (values: unknown[]) => values.reduce<number>((total, value) => total + (numeric(value) ?? 0), 0);
const spread = (items: Row[]) => Math.max(1, ...items.map(a => Math.abs((numeric(a.equity) ?? 1000) - 1000)));

function Flag({ children, tone = "plain" }: { children: ReactNode; tone?: Tone }) {
  return <span className={`pd-flag pd-${tone}`}><i aria-hidden="true" />{children}</span>;
}
function Value({ amount, suffix = "USDT" }: { amount: unknown; suffix?: string }) {
  return <>{format(amount)}{numeric(amount) === null ? null : <small> {suffix}</small>}</>;
}
function Metric({ icon: Icon, name, value, note, tone = "plain" }: {
  icon: typeof Wallet; name: string; value: ReactNode; note: string; tone?: Tone;
}) {
  return <div className={`pd-metric pd-metric-${tone}`}>
    <div className="pd-metric-top"><span>{name}</span><Icon size={18} aria-hidden="true" /></div>
    <strong>{value}</strong><small>{note}</small>
  </div>;
}
function SectionTitle({ title, hint, right }: { title: string; hint?: string; right?: ReactNode }) {
  return <div className="pd-section-title"><div><h2>{title}</h2>{hint && <p>{hint}</p>}</div>{right}</div>;
}
function UsageBar({ value, labelText }: { value: unknown; labelText?: string }) {
  const v = numeric(value);
  const width = v === null ? 0 : Math.max(0, Math.min(100, v));
  return <div className="pd-usage"><div className="pd-track" role="progressbar" aria-label={labelText ?? "Margin utilization"} aria-valuemin={0} aria-valuemax={100} aria-valuenow={v === null ? undefined : width}><span style={{ width: `${width}%` }} /></div><span>{percentage(v, 1)}</span></div>;
}
function AccountCards({ accounts, desk }: { accounts: Row[]; desk: Desk }) {
  return <div className="pd-account-grid">{[...accounts].sort((a, b) => Number(a.leverage) - Number(b.leverage)).map(account => {
    const net = (numeric(account.equity) ?? 1000) - 1000;
    const unrealized = desk === "btc" ? account.metrics?.position_metrics?.estimated_net_unrealized_pnl_usdt ?? 0 : account.estimated_net_unrealized;
    const utilization = desk === "btc" ? account.metrics?.position_metrics?.margin_utilization_pct ?? 0 : account.margin_utilization_pct;
    const maxDrawdown = desk === "btc" ? (numeric(account.max_drawdown) ?? 0) * 100 : (numeric(account.drawdown) ?? 0) * 100;
    const hasPosition = desk === "btc" ? Boolean(account.position) : (numeric(account.margin_used) ?? 0) > 0;
    return <article className="pd-account" key={`${desk}-${account.leverage}`}>
      <div className="pd-account-heading"><span className="pd-leverage">{account.leverage}×</span><Flag tone={account.halted ? "bad" : hasPosition ? "good" : "plain"}>{account.halted ? "Risk halted" : hasPosition ? "In a trade" : "No position"}</Flag></div>
      <p className="pd-mini-label">Account equity</p>
      <strong className="pd-equity"><Value amount={account.equity} /></strong>
      <div className="pd-account-net"><span className={`pd-pnl pd-${toneOf(net)}`}>{signedCash(net)}</span><span className="pd-small-muted">{percentage(desk === "btc" ? account.metrics?.account_roi_pct : account.account_roi_pct)} ROI</span></div>
      <div className="pd-account-stats">
        <div><span>Realized</span><strong className={`pd-${toneOf(account.realized)}`}>{signedCash(account.realized)}</strong></div>
        <div><span>Open est.</span><strong className={`pd-${toneOf(unrealized)}`}>{signedCash(unrealized)}</strong></div>
        <div><span>Free cash</span><strong>{cash(desk === "btc" ? account.cash : account.free_collateral)}</strong></div>
        <div><span>Closed</span><strong>{format(account.closed, 0)} trades</strong></div>
      </div>
      <div className="pd-card-bottom"><div className="pd-card-row"><span>Margin used</span><span>{desk === "multi" ? cash(account.margin_used) : cash(account.position?.margin ?? 0)}</span></div><UsageBar value={utilization} labelText={`${account.leverage}× margin utilization`} /><div className="pd-card-row"><span>Max drawdown</span><strong>{percentage(maxDrawdown)}</strong></div></div>
      {Number(account.liquidations) > 0 && <p className="pd-card-warning">{account.liquidations} liquidation(s) recorded</p>}
    </article>;
  })}</div>;
}
function NetBars({ accounts }: { accounts: Row[] }) {
  const scale = spread(accounts);
  return <div className="pd-bars" role="img" aria-label="Net account profit and loss by leverage">
    {[...accounts].sort((a, b) => Number(a.leverage) - Number(b.leverage)).map(a => {
      const net = (numeric(a.equity) ?? 1000) - 1000;
      return <div className="pd-bar-row" key={a.leverage}>
        <span className="pd-bar-label">{a.leverage}×</span>
        <div className="pd-bar-track"><span className={`pd-bar-fill ${net < 0 ? "negative" : "positive"}`} style={{ width: `${Math.max(1, Math.abs(net) / scale * 100)}%` }} /></div>
        <strong className={`pd-${toneOf(net)}`}>{signedCash(net)}</strong>
      </div>;
    })}
    <p className="pd-footnote">Each leverage level is a separate simulated account. Profit does not imply a proven strategy.</p>
  </div>;
}
function PositionRange({ stop, mark, target }: { stop: unknown; mark: unknown; target: unknown }) {
  const a = numeric(stop), b = numeric(mark), c = numeric(target);
  if (a === null || b === null || c === null || a === c) return null;
  const progress = Math.max(0, Math.min(100, (b - a) / (c - a) * 100));
  return <div className="pd-position-range" aria-label={`Current price is ${format(progress, 0)} percent of the distance from stop to target`}>
    <div className="pd-range-track"><span style={{ left: `${progress}%` }} /></div>
    <div><span>Stop {format(a)}</span><span>Target {format(c)}</span></div>
  </div>;
}
function Positions({ data, desk }: { data: Row; desk: Desk }) {
  const positions: Row[] = desk === "multi" ? (data.positions ?? []).map((p: Row) => ({ ...p, symbol: p.symbol })) : (data.accounts ?? []).filter((a: Row) => a.position).map((a: Row) => ({
    ...a.position, symbol: "BTCUSDT", leverage: a.leverage, mark: data.mark, metrics: a.metrics?.position_metrics,
  }));
  return <section className="pd-surface">
    <SectionTitle title="Open positions" hint="Stops and targets are simulated protective levels" right={<Flag tone={positions.length ? "good" : "plain"}>{positions.length} open</Flag>} />
    {positions.length === 0 ? <div className="pd-empty"><ShieldCheck size={28} /><strong>No open positions</strong><span>The scanner will keep evaluating new setups while entries are enabled.</span></div> :
      <div className="pd-table-scroll" role="region" aria-label="Open perpetual positions" tabIndex={0}><table className="pd-table pd-positions-table"><thead><tr><th>Account</th><th>Position</th><th>Entry / current</th><th>Est. net open P&L</th><th>Stop → target</th><th>Liquidation</th></tr></thead><tbody>
        {positions.map((p, i) => {
          const pnl = desk === "btc" ? p.metrics?.estimated_net_unrealized_pnl_usdt : p.estimated_net_unrealized;
          return <tr key={p.id ?? `${p.leverage}-${i}`}>
            <td><span className="pd-cell-strong">{p.leverage}× isolated</span></td>
            <td><span className="pd-symbol">{p.symbol}</span><br /><Flag tone={Number(p.side) === 1 ? "good" : "warn"}>{direction(p.side)}</Flag></td>
            <td><span>{format(p.entry)}</span><br /><strong>{format(p.mark)}</strong></td>
            <td><strong className={`pd-${toneOf(pnl)}`}>{signedCash(pnl)}</strong><br /><span className="pd-small-muted">Net close estimate</span></td>
            <td><div className="pd-levels"><span>{format(p.stop)} → {format(p.target)}</span><PositionRange stop={p.stop} mark={p.mark} target={p.target} /></div></td>
            <td><span>{format(p.liquidation_mark)}</span><br /><span className="pd-small-muted">{percentage(desk === "btc" ? p.metrics?.liquidation_distance_pct : p.liquidation_distance_pct)} distance</span></td>
          </tr>;
        })}
      </tbody></table></div>}
    <p className="pd-footnote">Open P&L is an estimate after modeled exit costs; actual modeled settlement may differ. No real orders are placed.</p>
  </section>;
}
function Scanner({ scan, fresh }: { scan: Row | undefined; fresh: boolean }) {
  const [search, setSearch] = useState("");
  const [filter, setFilter] = useState("all");
  const [limit, setLimit] = useState(10);
  const rows: Row[] = scan?.rows ?? [];
  const visible = useMemo(() => rows.filter(row => {
    const term = search.trim().toLowerCase();
    const matches = !term || String(row.symbol ?? "").toLowerCase().includes(term) || String(row.base ?? "").toLowerCase().includes(term);
    const status = String(row.status ?? "").toLowerCase();
    return matches && (filter === "all" || (filter === "selected" && !["deferred", "rejected"].includes(status)) || status === filter);
  }), [rows, search, filter]);
  const stages = [
    ["Screened", numeric(scan?.markets_screened) ?? rows.length],
    ["Technical passes", numeric(scan?.technical_passed) ?? 0],
    ["Detailed", numeric(scan?.details_completed) ?? 0],
    ["Paper fills / scan", numeric(scan?.matched_opportunities_filled) ?? 0],
  ] as const;
  const max = Math.max(1, stages[0][1]);
  return <section className="pd-surface">
    <SectionTitle title="Market scanner" hint="Actual market observations · no fabricated candidates" right={<Flag tone={fresh ? "good" : "warn"}>{fresh ? "Current" : "Stale"}</Flag>} />
    <div className="pd-scanner-stages">{stages.map(([name, count], i) => <div className="pd-scanner-stage" key={name}><span>{name}</span><strong>{count}</strong><div className="pd-stage-bar"><i style={{ width: `${Math.max(1, count / max * 100)}%`, backgroundColor: i === 3 ? "#2a9367" : undefined }} /></div></div>)}</div>
    <div className="pd-search-row"><label className="pd-search"><Search size={17} aria-hidden="true"/><span className="sr-only">Search markets</span><input placeholder="Search BTC, ETH, SOL…" value={search} onChange={e => {setSearch(e.target.value);setLimit(10);}} /></label>
      <label className="pd-select"><span className="sr-only">Filter market status</span><select value={filter} onChange={e => {setFilter(e.target.value);setLimit(10);}}><option value="all">All markets</option><option value="selected">Candidates</option><option value="rejected">Rejected</option><option value="deferred">Deferred</option></select><ChevronDown size={14} /></label>
    </div>
    {rows.length ? <><div className="pd-table-scroll" tabIndex={0} role="region" aria-label="Market scanner results"><table className="pd-table"><thead><tr><th>Market</th><th>Price</th><th>Regime</th><th>Strategy</th><th>Status</th><th>Why</th></tr></thead><tbody>{visible.slice(0, limit).map((row, i) => {
      const s = String(row.status ?? "UNKNOWN").toUpperCase();
      const kind: Tone = s.includes("FILL") || s === "QUALIFIED" ? "good" : s === "REJECTED" ? "bad" : s === "DEFERRED" ? "plain" : "warn";
      return <tr key={`${row.symbol}-${i}`}><td><strong className="pd-symbol">{row.base ?? String(row.symbol ?? "").replace("USDT", "")}</strong><br /><span className="pd-small-muted">{row.symbol}</span></td><td>{cash(row.price)}</td><td>{label(row.regime)}</td><td>{row.policy ? label(row.policy) : <span className="pd-small-muted">Not detailed</span>}</td><td><Flag tone={kind}>{s === "PAPER_FILLED" ? "Filled" : label(s)}</Flag></td><td><span className="pd-reason" title={label(row.reason ?? row.selection)}>{shorten(row.reason ?? row.selection ?? "Not selected", 45)}</span></td></tr>;
    })}</tbody></table></div>{visible.length > limit && <button className="pd-more" onClick={() => setLimit(x => x + 12)}>Show more markets <ArrowRight size={16}/></button>}{visible.length === 0 && <div className="pd-empty pd-small-empty">No markets match this filter.</div>}</> : <div className="pd-empty pd-small-empty">No scanner results available yet.</div>}
    <details className="pd-collapse"><summary>Why candidates were rejected <ChevronDown size={16}/></summary><div className="pd-chip-wrap">{Object.entries(scan?.no_entry_reasons ?? {}).map(([reason, count]) => <span className="pd-reason-chip" key={reason}>{label(reason)} <strong>{String(count)}</strong></span>)}{!Object.keys(scan?.no_entry_reasons ?? {}).length && <span className="pd-small-muted">No rejection details recorded.</span>}</div></details>
    <p className="pd-footnote">Deferred markets were not fully evaluated. Technical passes and detailed evaluations are separate counts, not a conversion funnel. USDT contract prices are not EUR spot quotes.</p>
  </section>;
}
function Outcomes({ accounts, data, desk }: { accounts: Row[]; data: Row; desk: Desk }) {
  const rows: Row[] = desk === "multi" ? (data.performance ?? []) : [];
  const ranked = [...rows].sort((a, b) => Math.abs(numeric(b.net) ?? 0) - Math.abs(numeric(a.net) ?? 0)).slice(0, 6);
  return <section className="pd-surface"><SectionTitle title="Performance" hint="Measured virtual account results" />
    <div className="pd-performance-grid"><div className="pd-subpanel"><h3>Net P&L by leverage</h3><NetBars accounts={accounts}/></div><div className="pd-subpanel"><h3>{desk === "multi" ? "Recent strategy outcomes" : "Strategy status"}</h3>
      {ranked.length ? <div className="pd-results">{ranked.map((row, i) => <div className="pd-result" key={`${row.symbol}-${row.policy}-${row.leverage}-${i}`}><div><strong>{row.symbol}</strong><span>{row.leverage}× · {label(row.policy)}</span></div><div><strong className={`pd-${toneOf(row.net)}`}>{signedCash(row.net)}</strong><small>{row.wins ?? 0}W / {row.losses ?? 0}L</small></div></div>)}</div> : <div className="pd-empty pd-small-empty">{desk === "btc" ? "Baseline breakout model · paper results shown by account." : "No settled trades yet."}</div>}
    </div></div>
    {desk === "multi" && <p className="pd-footnote">Grouped outcomes may share the same market signal across 1× / 3× / 10× accounts. They are not independent samples.</p>}
  </section>;
}
function ActivityList({ desk, events, history }: { desk: Desk; events: Row[]; history?: Row }) {
  const rows: Row[] = desk === "multi" ? history?.rows ?? [] : events.slice(0, 16);
  return <section className="pd-surface"><SectionTitle title="Recent activity" hint="Saved simulated events, newest first" />
    {rows.length ? <div className="pd-activity">{rows.slice(0, 10).map((event: Row, i: number) => {
      const kind = String(event.kind ?? "EVENT");
      const value = desk === "multi" ? event.net : event.net ?? event.amount;
      const good = kind === "TARGET" || (numeric(value) ?? 0) > 0;
      const bad = kind === "STOP" || kind === "LIQUIDATION" || (numeric(value) ?? 0) < 0;
      const symbol = desk === "multi" ? (event.position?.symbol ?? event.signal?.symbol ?? event.symbol ?? "Ledger") : "BTCUSDT";
      const leverage = desk === "multi" ? event.cohort : event.leverage;
      return <div className="pd-activity-item" key={`${event.id ?? event.event_key ?? event.minute}-${i}`}><span className={`pd-activity-icon ${good ? "pd-good" : bad ? "pd-bad" : ""}`}>{good ? <ArrowUpRight size={16}/> : bad ? <ArrowDownRight size={16}/> : <Activity size={16}/>}</span><div><strong>{symbol} <span className="pd-small-muted">{leverage ? `${leverage}×` : ""}</span></strong><span>{label(kind)} · {timestamp(desk === "multi" ? event.at : event.minute)}</span></div><div className={`pd-activity-value pd-${toneOf(value)}`}>{value == null ? "" : signedCash(value)}</div></div>;
    })}</div> : <div className="pd-empty pd-small-empty">No completed events in this view yet.</div>}
    {desk === "multi" && <p className="pd-footnote">Latest settled trades only. Other event categories and the full journal remain in Advanced evidence.</p>}
  </section>;
}
export function Perpetuals() {
  const api = useApi();
  const [desk, setDesk] = useState<Desk>("multi");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [showOriginal, setShowOriginal] = useState(false);
  const multi = useResource(MULTI_URL, { poll: 12000, enabled: desk === "multi" });
  const btc = useResource(BTC_URL, { poll: 12000, enabled: desk === "btc" });
  const history = useResource(MULTI_URL + "/history?limit=20&kind=EXIT_SETTLED", { poll: 15000, enabled: desk === "multi" });
  const resource = desk === "multi" ? multi : btc;
  const data = resource.data as Row | undefined;
  const accounts = (data?.accounts ?? []) as Row[];
  const active = Boolean(data?.entries_enabled);
  const valid = desk === "multi" ? Boolean(data?.feature_enabled && data?.scan_fresh && data?.status === "ACTIVE" && !Object.keys(data?.monitor?.errors ?? {}).length) : Boolean(data?.available && data?.data_fresh);
  const marketFresh = desk === "multi" ? Boolean(data?.scan_fresh && data?.status === "ACTIVE") : Boolean(data?.data_fresh);
  const totalEquity = sum(accounts.map(a => a.equity));
  const net = totalEquity - 1000 * accounts.length;
  const openCount = desk === "multi" ? (data?.positions ?? []).length : accounts.filter(a => a.position).length;
  const scanCount = desk === "multi" ? (numeric(data?.scan?.markets_screened) ?? 0) : null;
  const lastTime = desk === "multi" ? data?.scan?.at : data?.bar_closed_at;
  const subtitle = desk === "multi" ? "Multi-coin strategy engine" : "Bitcoin breakout strategy";
  async function setEntries(enabled: boolean) {
    setBusy(true);setError("");
    try { await api.request((desk === "multi" ? MULTI_URL : BTC_URL) + "/entries", "POST", { enabled });await api.refresh(desk === "multi" ? MULTI_URL : BTC_URL); }
    catch (e) {setError(errorMessage(e));}
    finally {setBusy(false);}
  }
  return <div className="pd-shell" data-ui-revision="pd-visual-20261105-v1">
    <div className="pd-hero"><div><p className="pd-kicker"><Radio size={14}/> PAPER TRADING DESK</p><h2>See your strategies at a glance.</h2><p>Live market observations. Virtual trades. Independent leverage accounts.</p></div><div className="pd-hero-status"><Flag tone="good">Simulation only</Flag><span><Clock3 size={14}/> Data {timestamp(lastTime)}</span></div></div>
    <div className="pd-tabs" role="tablist" aria-label="Perpetual trading systems"><button role="tab" id="pd-tab-multi" aria-controls="pd-content" aria-selected={desk === "multi"} className={desk === "multi" ? "active" : ""} onClick={() => {setDesk("multi");setError("");}}><Layers3 size={17}/> Multi-coin <span>USDT markets</span></button><button role="tab" id="pd-tab-btc" aria-controls="pd-content" aria-selected={desk === "btc"} className={desk === "btc" ? "active" : ""} onClick={() => {setDesk("btc");setError("");}}><Coins size={17}/> Bitcoin <span>BTC / USDT</span></button></div>
    <div id="pd-content" role="tabpanel" aria-labelledby={desk === "multi" ? "pd-tab-multi" : "pd-tab-btc"} className="pd-content">
      <ResourceState resource={resource} label={subtitle}/>
      {data && <>
        <div className="pd-operation"><div><h3>{subtitle}</h3><div className="pd-operation-flags"><Flag tone={marketFresh ? "good" : "warn"}><Radio size={12}/> {marketFresh ? "Scanner current" : "Scanner unavailable"}</Flag><Flag tone={active ? "good" : "warn"}>{active ? "Entries on" : "Entries paused"}</Flag><Flag tone="plain">1× / 3× / 10×</Flag></div></div><button className={`pd-entry-control ${active ? "pd-control-stop" : "pd-control-start"}`} disabled={busy || Boolean(resource.error) || !data || (!active && !valid)} onClick={() => void setEntries(!active)}>{active ? <PauseCircle size={19}/> : <PlayCircle size={19}/>} {busy ? "Updating…" : active ? "Pause entries" : "Enable entries"}</button></div>
        {error && <div className="pd-error" role="alert">{error}</div>}
        {!marketFresh && <div className="pd-caution"><ShieldCheck size={16}/> Data freshness unavailable. New entries should stay paused until monitoring recovers.</div>}
        {desk === "btc" && data.pending && <div className="pd-caution">Queued {direction(data.pending.side)} BTC entry for {timestamp(data.pending.fill_at)}.</div>}
        <div className="pd-metrics">
          <Metric name="Total virtual equity" icon={Wallet} value={accounts.length ? <Value amount={totalEquity}/> : "—"} note={`${accounts.length} independent USDT accounts`} />
          <Metric name="Net account P&L" icon={TrendingUp} value={accounts.length ? signedCash(net) : "—"} tone={toneOf(net)} note="Equity minus starting virtual capital" />
          <Metric name="Open positions" icon={Activity} value={openCount} note="Across all three leverage accounts" />
          <Metric name={desk === "multi" ? "Markets screened" : "BTC market mark"} icon={desk === "multi" ? BarChart3 : Gauge} value={desk === "multi" ? scanCount ?? "—" : cash(data.mark)} note={desk === "multi" ? "Latest completed multi-coin scan" : "Observed USDT price"} />
        </div>
        <SectionTitle title="Your leverage accounts" hint="Compare separate simulated 1×, 3× and 10× portfolios" />
        <AccountCards accounts={accounts} desk={desk}/>
        <Positions data={data} desk={desk}/>
        {desk === "multi" && <Scanner scan={data.scan} fresh={marketFresh}/>}
        <div className="pd-two-columns"><Outcomes accounts={accounts} data={data} desk={desk}/><ActivityList desk={desk} events={data.events ?? []} history={history.data}/></div>
        <section className="pd-surface pd-research-summary"><SectionTitle title="Strategy & research" hint="Optional detail — no effect on live paper execution" /><div className="pd-research-row"><span><ShieldCheck size={17}/> {desk === "multi" ? "Experimental deterministic strategies; expected profitability unproven" : "BTC breakout baseline; fixed-model costs and candle-based execution"}</span><Flag tone="plain">Research only</Flag></div>{desk === "multi" ? <><details className="pd-collapse"><summary>Scenario candidates <ChevronDown size={15}/></summary><div className="pd-list-grid">{(data.scan?.top_opportunities ?? []).slice(0, 10).map((o: Row) => <div key={o.signal_id ?? o.symbol} className="pd-inline-row"><strong>{o.symbol} · {direction(o.direction)}</strong><span>{label(o.policy)} · {percentage(o.target_move_pct)} target move</span></div>)}{!(data.scan?.top_opportunities ?? []).length && <p className="pd-small-muted">No qualified scenarios in this scan.</p>}</div></details><details className="pd-collapse"><summary>Scanner / modeling evidence <ChevronDown size={15}/></summary><Technical value={data.scan?.unsupported ?? []} label="Unsupported asset mappings"/><Technical value={data.decision_counts} label="Decision evidence counts"/><Technical value={data.realized_distributions} label="Realized distributions"/></details></> : <details className="pd-collapse"><summary>Model assumptions <ChevronDown size={15}/></summary><div className="pd-inline-row"><span>Strategy</span><strong>{label(data.strategy?.identity ?? data.policy)}</strong></div><div className="pd-inline-row"><span>Estimated round-trip cost</span><strong>{percentage(data.strategy?.approximate_round_trip_cost_pct, 3)}</strong></div><div className="pd-inline-row"><span>Completed bar</span><strong>{timestamp(data.bar_closed_at)}</strong></div></details>}</section>
      </>}
    </div>
    <section className="pd-legacy"><div><h3>Full evidence and original reports</h3><p>Every technical field, complete research panel and historical report remains available.</p></div><button onClick={() => setShowOriginal(v => !v)} aria-expanded={showOriginal}>{showOriginal ? "Hide full reports" : "Open advanced reports"}<ChevronDown size={16}/></button></section>
    {showOriginal && <div className="pd-original"><Suspense fallback={<div className="pd-empty">Loading advanced reports…</div>}><OriginalPage/></Suspense></div>}
    <p className="pd-disclaimer">Paper simulation only. Observed market prices and modeled trading results are not executable returns, investment guarantees or proof of profitability.</p>
  </div>;
}

