import React, { useCallback, useEffect, useState } from "react";
import { createRoot } from "react-dom/client";
import { Area, AreaChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import "./styles.css";
import { PilotPanel } from "./PilotPanel";
import { ExecutionQuality, OpportunityIntelligence, StrategyLab } from "./ResearchPanels";

type Row = Record<string, any>;
type Data = { overview: Row; scanner: Row; history: Row; ai: Row; system: Row; settings: Row; backtests: Row; execution: Row; research: Row; intelligence: Row };
const tabs = ["Command Center", "Market Scanner", "Opportunities", "Autonomous Decisions", "Portfolio", "Position Management", "Order History", "Backtesting Lab", "Execution Quality", "Strategy Lab", "Opportunity Intelligence", "AI Intelligence", "Risk Center", "System Health", "Paper Pilot", "Settings"];
const controls = [["start", "START PAPER TRADING"], ["pause", "PAUSE NEW ENTRIES"], ["resume", "RESUME PAPER TRADING"], ["stop", "STOP PAPER TRADING"], ["emergency", "EMERGENCY PAPER HALT"]];

export function displayMoney(value: unknown): string {
  if (value === "" || value === null || value === undefined || !Number.isFinite(Number(value))) return "Unavailable";
  return `EUR ${Number(value).toFixed(2)}`;
}

async function request(path: string, auth: string, method = "GET", body?: Row) {
  const response = await fetch(path, { method, headers: { Authorization: auth, "Content-Type": "application/json" }, body: body ? JSON.stringify(body) : undefined, cache: "no-store" });
  const payload = await response.json();
  if (!response.ok) throw new Error(`${response.status}: ${typeof payload.detail === "string" ? payload.detail : JSON.stringify(payload.detail ?? payload)}`);
  return payload;
}

function App() {
  const [active, setActive] = useState("Command Center");
  const [auth, setAuth] = useState("");
  const [username, setUsername] = useState("admin");
  const [password, setPassword] = useState("");
  const [data, setData] = useState<Data | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const refresh = useCallback(async (credential = auth) => {
    if (!credential) return;
    try {
      const [overview, scanner, history, ai, system, settings, backtests, execution, research, intelligence] = await Promise.all(["overview", "scanner", "history", "ai", "system", "settings", "backtests", "execution", "research", "intelligence"].map(path => request(`/api/${path}`, credential)));
      setData({ overview, scanner, history, ai, system, settings, backtests, execution, research, intelligence });
      setError("");
    } catch (reason) { setError(String(reason)); }
  }, [auth]);
  useEffect(() => { if (!auth) return; void refresh(); const timer = setInterval(() => void refresh(), 10000); return () => clearInterval(timer); }, [auth, refresh]);
  const control = async (action: string) => {
    setBusy(true);
    try { await request(`/api/controls/${action}`, auth, "POST"); await refresh(); }
    catch (reason) { setError(String(reason)); }
    finally { setBusy(false); }
  };
  if (!auth) return <main><section className="workspace"><h1>Revolut X AutoTrader</h1><p>Paper trading dashboard</p><form className="panel" onSubmit={async event => {
    event.preventDefault();
    try { const credential = `Basic ${btoa(`${username}:${password}`)}`; await request("/api/overview", credential); setAuth(credential); setPassword(""); }
    catch (reason) { setError(String(reason)); }
  }}><label>Username <input aria-label="Username" autoComplete="username" value={username} onChange={e => setUsername(e.target.value)} /></label><label>Password <input aria-label="Password" type="password" autoComplete="current-password" value={password} onChange={e => setPassword(e.target.value)} required /></label><button type="submit">Sign in</button>{error && <p role="alert">{error}</p>}</form></section></main>;
  const portfolio = data?.overview.portfolio ?? {};
  return <main><aside><div className="brand">Revolut X AutoTrader</div><nav>{tabs.map(tab => <button key={tab} className={active === tab ? "active" : ""} onClick={() => setActive(tab)}>{tab}</button>)}</nav></aside><section className="workspace"><header><div><h1>{active}</h1><p>V{data?.overview.application_version ?? "…"} · PAPER MODE · {data?.system.operational_state ?? "INITIALIZING"} · Risk: {portfolio.risk_state ?? "Unknown"} · Controls: {portfolio.control ?? "Unknown"}</p></div><button onClick={() => { setAuth(""); setData(null); }}>Sign out</button></header><div className="controls">{controls.map(([action, label]) => <button disabled={busy} key={action} onClick={() => void control(action)}>{label}</button>)}</div>{error && <div className="panel danger" role="alert">{error}</div>}{!data ? <p>Loading account state…</p> : <Dashboard active={active} data={data} auth={auth} refresh={refresh} />}</section></main>;
}

function Table({ rows, fields }: { rows: Row[]; fields: string[] }) {
  if (!rows.length) return <p className="panel">No records.</p>;
  return <div className="panel table-wrap"><table><thead><tr>{fields.map(field => <th key={field}>{field.replace(/_/g, " ")}</th>)}</tr></thead><tbody>{rows.map((row, index) => <tr key={row.target_id ?? row.fill_id ?? row.transition_id ?? row.order_id ?? `${row.position_id ?? row.decision_id ?? "row"}-${index}`}>{fields.map(field => <td key={field}>{typeof row[field] === "object" ? JSON.stringify(row[field]) : String(row[field] ?? "—")}</td>)}</tr>)}</tbody></table></div>;
}

function Dashboard({ active, data, auth, refresh }: { active: string; data: Data; auth: string; refresh: () => Promise<void> }) {
  const p = data.overview.portfolio;
  const [jobError, setJobError] = useState("");
  const [running, setRunning] = useState(false);
  const [entryOrderType, setEntryOrderType] = useState("MARKET");
  if (active === "Paper Pilot") return <PilotPanel auth={auth} />;
  if (active === "Execution Quality") return <ExecutionQuality data={data.execution} />;
  if (active === "Strategy Lab") return <StrategyLab data={data.research} auth={auth} refresh={refresh} />;
  if (active === "Opportunity Intelligence") return <OpportunityIntelligence data={data.intelligence} />;
  if (active === "Command Center") {
    const values = [["Starting virtual capital", p.initial_cash], ["Current equity", p.equity], ["Available cash", p.available_cash], ["Reserved cash", p.reserved_cash], ["Open exposure", p.open_exposure], ["Realized P&L", p.realized_pnl], ["Unrealized P&L", p.unrealized_pnl], ["Total net P&L", p.total_net_pnl], ["Daily equity change", p.daily_equity_change], ["Weekly equity change", p.weekly_equity_change]];
    const curve = (data.history.equity ?? []).filter((r: Row) => !r.degraded && Number.isFinite(Number(r.equity))).slice(0, 100).reverse().map((r: Row) => ({ time: r.timestamp, equity: Number(r.equity) }));
    const research = data.execution.entry_policy;
    return <><section className="panel"><strong role="status">{research?.allowed_strategy_ids?.length ? "PAPER STRATEGY APPROVED" : "NO VALIDATED STRATEGY"}</strong><p>{data.system.operational_state} · Daily risk: {p.daily_risk_status} · Weekly risk: {p.weekly_risk_status} · Current drawdown: {p.current_drawdown === "" || p.current_drawdown == null ? "Unavailable" : `${(Number(p.current_drawdown) * 100).toFixed(2)}%`}</p><p>AI: {data.ai.provider} · {data.ai.budget?.daily_used ?? "Unavailable"}/{data.ai.budget?.daily_limit ?? "Unavailable"} today · {data.ai.budget?.rolling_hour_used ?? "Unavailable"}/{data.ai.budget?.hourly_limit ?? "Unavailable"} rolling hour</p></section><div className="metrics">{values.map(([label, value]) => <div className="metric" key={label}><span>{label}</span><strong>{displayMoney(value)}</strong></div>)}<div className="metric"><span>Active positions / pending orders</span><strong>{p.positions} / {p.pending_orders}</strong></div><div className="metric"><span>Worker</span><strong>{data.system.worker}</strong></div></div>{curve.length > 1 ? <div className="chart"><ResponsiveContainer width="100%" height={260}><AreaChart data={curve}><XAxis dataKey="time" hide /><YAxis domain={["auto", "auto"]} /><Tooltip /><Area dataKey="equity" stroke="#0f766e" fill="#99f6e4" isAnimationActive={false} /></AreaChart></ResponsiveContainer></div> : <p className="panel">Equity history needs at least two validated observations.</p>}<p className="panel">Scanner: {data.scanner.status}. Last worker heartbeat: {data.system.worker_heartbeat ?? "Absent"}</p></>;
  }
  if (active === "Market Scanner" || active === "Opportunities") return <><p className="panel">{data.scanner.status} · {data.scanner.scanned} markets · {data.scanner.provider_errors?.join("; ")}</p><Table rows={(data.scanner.candidates ?? []).map((c: Row) => ({ ...c, ...c.market, research_status: data.execution.entry_policy?.status, strategies: c.signals?.filter((s: Row) => s.evidence?.entry_eligible).map((s: Row) => s.strategy_id), regime: c.signals?.[0]?.evidence?.regime }))} fields={["symbol", "best_bid", "best_ask", "spread_bps", "regime", "strategies", "research_status", "decision"]} /><Table rows={data.scanner.signals ?? []} fields={["strategy_id", "score", "evidence", "explanation"]} /><Table rows={data.scanner.rejected ?? []} fields={["symbol", "reasons"]} /></>;
  if (active === "Autonomous Decisions") return <><p className="panel">Observed market → strategy evidence → proposal → risk check → order transition → confirmed fill → position management → recorded exit</p><Table rows={data.history.decisions ?? []} fields={["created_at", "symbol", "action", "accepted", "rejected_reason", "payload_json"]} /><Table rows={data.history.transitions ?? []} fields={["created_at", "order_id", "to_status", "reason"]} /></>;
  if (active === "Portfolio") return <><p className="panel">Midpoint marked equity: {displayMoney(data.execution.mark_equity)}. Bid liquidation after exit costs: {displayMoney(data.execution.executable_bid_equity_after_exit_costs)}. Full executable valuation: {String(data.execution.executable_valuation_complete)}.</p><Table rows={data.overview.positions ?? []} fields={["position_id", "symbol", "quantity", "cost_basis", "average_entry_price", "realized_pnl", "closed_at"]} /></>;
  if (active === "Position Management") return <><Table rows={data.overview.positions ?? []} fields={["position_id", "symbol", "original_quantity", "quantity", "protective_stop", "initial_stop", "highest_price", "trailing_distance", "expires_at", "last_monitored_at"]} /><Table rows={data.overview.targets ?? []} fields={["position_id", "target_number", "target_price", "original_planned_quantity", "filled_quantity", "reserved_quantity", "remaining_quantity", "status"]} /><Table rows={data.history.exit_intents ?? []} fields={["position_id", "reason", "quantity", "reserved_quantity", "status"]} /></>;
  if (active === "Order History") return <><Table rows={data.overview.orders ?? []} fields={["order_id", "position_id", "symbol", "side", "status", "quantity", "filled_quantity", "exit_target_id"]} /><Table rows={data.overview.fills ?? []} fields={["fill_id", "position_id", "exit_target_id", "side", "quantity", "price", "fee"]} /></>;
  if (active === "AI Intelligence") return <><div className="metrics">{[["UTC day", `${data.ai.budget?.daily_used}/${data.ai.budget?.daily_limit} · ${data.ai.budget?.daily_remaining} remaining`], ["Rolling 60 minutes", `${data.ai.budget?.rolling_hour_used}/${data.ai.budget?.hourly_limit} · ${data.ai.budget?.hourly_remaining} remaining`], ["Monthly estimated spend", `USD ${data.ai.budget?.estimated_spend_usd}`], ["Confirmed provider spend", `USD ${data.ai.budget?.confirmed_spend_usd}`], ["Reserved / remaining budget", `USD ${data.ai.budget?.reserved_usd} / ${data.ai.budget?.remaining_usd}`], ["Cache hits / quota rejections", `${data.ai.budget?.cache_hits} / ${data.ai.budget?.rejected_requests}`]].map(([label, value]) => <div className="metric" key={label}><span>{label}</span><strong>{value}</strong></div>)}</div><div className="panel"><p>Paid AI enabled: {String(data.ai.paid_enabled)}. UTC daily reset: {data.ai.budget?.daily_reset_at}. Next rolling-hour release: {data.ai.budget?.next_hourly_release_at ?? "No active reservations"}. Monthly reset: {data.ai.budget?.monthly_reset_at}. Last successful analysis: {data.ai.budget?.last_successful_analysis ?? "None"}.</p><h2>Provider: {data.ai.provider}</h2><p>Model: {data.ai.model || "Off"}. Paid requests: {data.ai.budget?.requests ?? 0}.</p><pre>{JSON.stringify(data.ai.budget, null, 2)}</pre></div><pre className="panel">{JSON.stringify(data.scanner.ai, null, 2)}</pre></>;
  if (active === "Risk Center") return <><div className="panel"><h2>{p.risk_state}</h2><p>Daily change: {displayMoney(p.daily_equity_change)}. Weekly change: {displayMoney(p.weekly_equity_change)}.</p><p>Valuation degraded: {p.valuation_degraded}. Missing marks: {p.missing_marks || "None"}.</p><pre>{JSON.stringify(data.settings.risk_limits, null, 2)}</pre><button onClick={async () => { try { await request("/api/risk/recover", auth, "POST"); await refresh(); } catch (e) { setJobError(String(e)); } }}>Request risk recovery</button>{jobError && <p role="alert">{jobError}</p>}</div><Table rows={data.history.incidents ?? []} fields={["created_at", "severity", "status", "message"]} /></>;
  if (active === "System Health") return <pre className="panel">{JSON.stringify({ ...data.system, mature_feedback_backlog: data.intelligence.mature_feedback_backlog, protection_watches: data.execution.protection_watches, entry_policy: data.execution.entry_policy }, null, 2)}</pre>;
  if (active === "Backtesting Lab") return <><div className="panel"><p>Replay uses persisted closed candles and paper accounting. Results include execution assumptions and data provenance.</p><label>Replay entry policy <select aria-label="Replay entry policy" value={entryOrderType} onChange={e => setEntryOrderType(e.target.value)}><option value="MARKET">Market IOC</option><option value="LIMIT">Limit IOC at observed ask</option></select></label><button disabled={running} onClick={async () => { setRunning(true); setJobError(""); try { await request("/api/backtests", auth, "POST", { symbol: "BTC-EUR", max_bars: 300, entry_order_type: entryOrderType }); await refresh(); } catch (e) { setJobError(String(e)); } finally { setRunning(false); } }}>{running ? "Running replay…" : "Run BTC-EUR historical replay"}</button>{jobError && <p role="alert">{jobError}</p>}</div><Table rows={data.backtests.runs ?? []} fields={["run_id", "symbol", "started_at", "completed_at", "payload_json"]} /></>;
  return <pre className="panel">{JSON.stringify(data.settings, null, 2)}</pre>;
}

if (typeof document !== "undefined" && document.getElementById("root")) createRoot(document.getElementById("root")!).render(<App />);
