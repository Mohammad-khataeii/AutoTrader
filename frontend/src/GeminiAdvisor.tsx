import React, { useState } from "react";
import { BrainCircuit, CheckCircle2, Clock, ShieldCheck, Sparkles } from "lucide-react";
import { errorMessage, useApi, useResource } from "./api";
import { date } from "./model";

export function GeminiAdvisor() {
  const api = useApi();
  const state = useResource("/api/gemini/status", { poll: 60000 });
  const d = state.data;
  const symbols: string[] = d?.symbols ?? [];
  const [selected, setSelected] = useState("");
  const [working, setWorking] = useState(false);
  const [error, setError] = useState("");
  const [result, setResult] = useState<any>(null);
  const symbol = symbols.includes(selected) ? selected : symbols[0] ?? "";
  const ready = d?.enabled && d?.market_snapshot_fresh && symbol && !state.error &&
    d?.remaining && d.remaining.hour > 0 && d.remaining.day > 0;
  async function analyze() {
    if (!ready || working) return;
    setWorking(true); setError(""); setResult(null);
    try {
      const response = await api.request("/api/gemini/analyze", "POST", { symbol });
      setResult(response); await api.refresh("/api/gemini/status");
    } catch (e) { setError(errorMessage(e)); }
    finally { setWorking(false); }
  }
  const a = result?.analysis;
  return <section className="gemini-panel" aria-label="Gemini market insights">
    <div className="gemini-heading">
      <div className="gemini-title"><span className="gemini-icon"><BrainCircuit size={22}/></span><div>
        <p className="eyebrow">Optional AI commentary</p><h2>Gemini Market Insights</h2>
      </div></div>
      <span className="gemini-tag"><ShieldCheck size={13}/> Advisory only · Paper mode</span>
    </div>
    <div className="gemini-toolbar">
      <div className="gemini-stat"><span>Connection</span><strong className={d?.enabled && !state.error ? "gemini-positive" : ""}>{d?.enabled && !state.error ? "Ready" : "Unavailable"}</strong></div>
      <div className="gemini-stat"><span>Market data</span><strong>{d?.market_snapshot_fresh ? "Current" : "Waiting for fresh scan"}</strong></div>
      <div className="gemini-stat"><span>Local usage cap</span><strong>{d?.remaining ? `${d.remaining.hour} hourly / ${d.remaining.day} daily left` : "Limiter unavailable"}</strong></div>
      <div className="gemini-stat"><span>Model</span><strong>{d?.model ?? "Checking"}</strong></div>
    </div>
    <div className="gemini-actions">
      <label htmlFor="gemini-coin">Market</label>
      <select id="gemini-coin" value={symbol} onChange={e => setSelected(e.target.value)} disabled={!symbols.length || working}>
        {!symbols.length && <option value="">No recent markets</option>}
        {symbols.map(s => <option key={s} value={s}>{s}</option>)}
      </select>
      <button className="primary" disabled={!ready || working} onClick={() => void analyze()}><Sparkles size={16}/>{working ? "Analyzing…" : "Analyze market"}</button>
      <span className="gemini-timestamp"><Clock size={13}/>{d?.market_snapshot_at ? `Scanner ${date(d.market_snapshot_at, true)}` : "Scanner unavailable"}</span>
    </div>
    {state.error && <p role="alert" className="notice warning">{state.error}</p>}
    {error && <p role="alert" className="notice warning">{error}</p>}
    {a && <div className="gemini-output" aria-live="polite">
      <div className="gemini-output-heading"><CheckCircle2 size={17}/><strong>{result.symbol} · Market reading</strong><span>{result.model}</span></div>
      <div className="gemini-insights"><div><small>What the data says</small><p>{a.market_summary}</p></div>
        <div><small>Signal quality</small><p>{a.signal_quality}</p></div>
        <div><small>What to watch next</small><p>{a.next_condition_to_watch}</p></div></div>
      <div className="gemini-columns"><div><h3>Risks</h3><ul>{(a.risk_factors ?? []).map((x: string,i: number) => <li key={i}>{x}</li>)}</ul></div>
        <div><h3>Missing evidence</h3><ul>{(a.missing_evidence ?? []).map((x: string,i: number) => <li key={i}>{x}</li>)}</ul></div></div>
    </div>}
    <p className="gemini-footnote">Uses only the latest saved market-scanner evidence. No portfolio details are sent. AI cannot place trades or change risk controls. Google free-tier limits depend on your project; billing status cannot be verified here.</p>
  </section>;
}
