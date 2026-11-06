import React from "react";
import { BrainCircuit, CircleAlert, Clock3, RadioTower, ShieldCheck } from "lucide-react";
import { useResource } from "./api";
import { date } from "./model";
import "./AutoGemini.css";

type AutoState = {
  enabled?: boolean;
  model?: string;
  fresh?: boolean;
  age_seconds?: number | null;
  state?: { state?: string; reason?: string; checked_at?: string };
  quota_remaining?: { hour?: number; day?: number };
  latest?: {
    generated_at?: string;
    model?: string;
    source_scope?: string[];
    source_timestamps?: Record<string, string | number | null>;
    analysis?: {
      market_summary?: string;
      spot_context?: string;
      btc_perpetual_context?: string;
      multi_perpetual_context?: string;
      risk_warnings?: string[];
      next_conditions?: string[];
    };
  } | null;
};

const readableState: Record<string, string> = {
  STARTING: "Starting automatically",
  WAITING: "Waiting for fresh market data",
  ANALYZING: "AI reviewing market data",
  CURRENT: "Analysis saved",
  CACHED: "Monitoring for new setups",
  QUOTA_WAIT: "Free-tier usage paused",
  BACKOFF: "Google limit / retry later",
  ERROR: "Analysis temporarily unavailable",
  DISABLED: "Disabled",
};

export function AutoGemini({ scope = "spot" }: { scope?: "spot" | "perpetuals" }) {
  const resource = useResource("/api/gemini/auto", { poll: 45000 });
  const data = resource.data as AutoState | undefined;
  const last = data?.latest;
  const a = last?.analysis;
  const context = scope === "perpetuals" ? [
    { name: "BTC perpetuals", text: a?.btc_perpetual_context, present: last?.source_scope?.includes("btc_perpetual") },
    { name: "Multi-coin perpetuals", text: a?.multi_perpetual_context, present: last?.source_scope?.includes("multi_perpetual") },
  ] : [
    { name: "Spot market", text: a?.spot_context, present: last?.source_scope?.includes("spot") },
  ];
  const state = data?.state?.state || (resource.error ? "ERROR" : "STARTING");
  const quota = data?.quota_remaining;
  const timestamp = last?.generated_at;
  const status = data?.enabled === false ? "DISABLED" : state;
  return <section className="autogem" aria-label="Automatic Gemini research">
    <div className="autogem-header">
      <div className="autogem-brand">
        <span className="autogem-mark"><BrainCircuit size={21} aria-hidden="true"/></span>
        <div><div className="autogem-kicker">AUTOMATIC MARKET INTELLIGENCE</div><h2>Gemini Market Monitor</h2></div>
      </div>
      <div className="autogem-state">
        <span className={data?.fresh ? "autogem-live" : "autogem-dim"}><RadioTower size={14}/>{data?.fresh ? "Recent research" : "Awaiting fresh analysis"}</span>
        <span className="autogem-paper"><ShieldCheck size={13}/> Paper research · No order authority</span>
      </div>
    </div>
    <div className="autogem-metrics">
      <div><span>Scheduler</span><strong>{readableState[status] || "Checking"}</strong></div>
      <div><span>Gemini model</span><strong>{data?.model || "Connecting"}</strong></div>
      <div><span>Requests left (hour / day)</span><strong>{quota ? `${quota.hour ?? "—"} / ${quota.day ?? "—"}` : "Checking"}</strong></div>
      <div><span>Last analysis</span><strong>{timestamp ? date(timestamp, true) : "Not generated yet"}</strong></div>
    </div>
    {a ? <>
      <div className="autogem-summary"><span>Market overview</span><p>{a.market_summary}</p></div>
      <div className="autogem-content-grid">
        {context.map(item => <div key={item.name} className="autogem-context">
          <h3>{item.name}</h3><p>{item.present ? item.text || "No analysis provided." : "Awaiting fresh evidence from this market."}</p>
        </div>)}
      </div>
      <div className="autogem-lower">
        <div><h3><CircleAlert size={15}/> Risks to watch</h3>{a.risk_warnings?.length ? <ul>{a.risk_warnings.map((s, i) => <li key={i}>{s}</li>)}</ul> : <p>No risk remarks recorded.</p>}</div>
        <div><h3><Clock3 size={15}/> Conditions to monitor</h3>{a.next_conditions?.length ? <ul>{a.next_conditions.map((s, i) => <li key={i}>{s}</li>)}</ul> : <p>Waiting for a new observed setup.</p>}</div>
      </div>
    </> : <div className="autogem-empty"><BrainCircuit size={20}/><div><strong>AI research starts automatically.</strong><p>The backend reviews the scanner and perpetual markets when fresh evidence and request quota are available. You don't need to click anything.</p></div></div>}
    {state === "ERROR" && <p className="autogem-alert">Automatic analysis failed: {data?.state?.reason === "gemini_provider_rate_limit" ? "Google API free-tier quota reached" : data?.state?.reason === "gemini_model_or_schema_rejected" ? "The model or JSON response format was rejected" : data?.state?.reason === "gemini_response_invalid" ? "Google returned an incomplete analysis" : "External AI service temporarily unavailable"}. Trading continues independently.</p>}
    {resource.error && <p className="autogem-alert">The AI research service couldn't be refreshed. Trading and protective monitoring operate separately.</p>}
    <div className="autogem-footer">
      <span>Analysis is saved server-side and reused across pages. No credentials, balances, or order quantities are sent to Google.</span>
      <span>Not investment advice; predictions and trading edge are unverified.</span>
    </div>
  </section>;
}
