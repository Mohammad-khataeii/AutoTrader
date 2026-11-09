import { useState } from "react";
import { Activity, BarChart3, Database, Lock, Pause, Play, RefreshCcw, ShieldCheck, TrendingUp, Wallet } from "lucide-react";
import { useApi, useResource } from "./api";
import { CryptoTradingOperations, CryptoTradingStatus } from "./TradingOperations";
import "./AlpacaCrypto.css";

type Row = Record<string, any>;
const num = (value: unknown): number => Number.isFinite(Number(value)) ? Number(value) : 0;
const integer = (value: unknown): string => num(value).toLocaleString("en-US");
const usd = (value: unknown): string => value == null || value === "" ? "—" :
  new Intl.NumberFormat("en-US", { style: "currency", currency: "USD", maximumFractionDigits: 2 }).format(num(value));
const when = (value: unknown): string => {
  if (typeof value !== "string" || !value) return "—";
  const parsed = new Date(value);
  return Number.isFinite(parsed.getTime()) ? parsed.toLocaleString() : "—";
};

export function AlpacaCrypto() {
  const api = useApi();
  const response = useResource("/api/stockswatch/alpaca-crypto", { poll: 15000, ttl: 7000 });
  const [working, setWorking] = useState(false);
  const [notice, setNotice] = useState("");
  const d: Row = response.data ?? {};
  const account: Row = d.broker_snapshot?.account ?? {};
  const assets: Row[] = Array.isArray(d.assets) ? d.assets : [];
  const jobs: Row[] = Array.isArray(d.history_jobs) ? d.history_jobs : [];
  const bars: Row[] = Array.isArray(d.history_bars) ? d.history_bars : [];
  const complete = jobs.filter(job => job.state === "COMPLETE").reduce((sum, job) => sum + num(job.n), 0);
  const total = jobs.reduce((sum, job) => sum + num(job.n), 0);
  const progress = total ? Math.min(100, 100 * complete / total) : 0;
  const eligible = assets.filter(asset => asset.eligible === 1).length;
  const barCount = (timeframe: string): number => bars.filter(bar => bar.timeframe === timeframe)
    .reduce((sum, bar) => sum + num(bar.n), 0);

  async function control(action: "pause" | "resume") {
    if (working) return;
    setWorking(true);
    setNotice("");
    try {
      await api.request("/api/stockswatch/alpaca-crypto/control", "POST", { action });
      await api.refresh("/api/stockswatch/alpaca-crypto");
      setNotice(action === "pause"
        ? "New paper orders paused; existing broker orders were not canceled."
        : "Resume request confirmed. Broker credentials, data quality and risk gates still apply.");
    } catch {
      setNotice("The change could not be confirmed. Check the broker status and server settings.");
    } finally {
      setWorking(false);
    }
  }

  return <main className="ac-root">
    <header className="ac-hero">
      <div className="ac-hero-copy">
        <div className="ac-label"><Activity size={16} /> 24/7 SPOT MARKET RESEARCH</div>
        <h2>AlpacaCrypto <span>Paper trading</span></h2>
        <p>Independent crypto strategy with its own Alpaca Paper account. Research continues even when order submission is disabled.</p>
      </div>
      <div className="ac-flags" aria-label="Trading limitations">
        <span><ShieldCheck size={14}/> Paper only</span>
        <span><Lock size={14}/> No leverage</span>
        <span><TrendingUp size={14}/> Long only</span>
      </div>
    </header>

    <CryptoTradingStatus dashboard={d} error={response.error}/>

    <section className="ac-stats" aria-label="Crypto data and account overview">
      <article><Database size={18}/><small>Historical observations</small><b>{integer(bars.reduce((sum, bar) => sum + num(bar.n), 0))}</b></article>
      <article><BarChart3 size={18}/><small>Backfill jobs complete</small><b>{integer(complete)} / {integer(total)}</b></article>
      <article><ShieldCheck size={18}/><small>Verified trading pairs</small><b>{integer(eligible)} / {assets.length || 10}</b></article>
      <article><Wallet size={18}/><small>Dedicated Paper equity</small><b>{account.equity == null ? "Not linked" : usd(account.equity)}</b></article>
    </section>

    <section className="ac-panel ac-data-panel" aria-label="Market data readiness and controls">
      <div className="ac-heading">
        <div><h3>Market data &amp; execution readiness</h3><p>Historical downloads do not mean orders are permitted.</p></div>
        <button type="button" onClick={() => void api.refresh("/api/stockswatch/alpaca-crypto")}>
          <RefreshCcw size={15}/> Refresh data
        </button>
      </div>
      <div className="ac-progress" role="progressbar" aria-valuemin={0} aria-valuemax={100}
        aria-valuenow={Math.round(progress)} aria-label="Historical backfill progress">
        <div style={{width:`${progress}%`}}/>
      </div>
      <div className="ac-grid">
        <div><small>Backfill completion</small><b>{progress.toFixed(1)}%</b></div>
        <div><small>Daily observations</small><b>{integer(barCount("1Day"))}</b></div>
        <div><small>Hourly observations</small><b>{integer(barCount("1Hour"))}</b></div>
        <div><small>Last strategy cycle</small><b>{when(d.last_cycle)}</b></div>
      </div>
      <div className="ac-control">
        <div>
          <strong>{!d.paper_orders_enabled ? "Research only — crypto paper orders disabled"
            : d.paused ? "Paper orders paused" : "Paper order admission enabled"}</strong>
          <small>A separate verified Alpaca Paper account is required. Resuming does not bypass risk checks.</small>
        </div>
        <div className="ac-buttons">
          <button type="button" disabled={working || d.paused !== false} onClick={() => void control("pause")}><Pause size={14}/> Pause</button>
          <button type="button" disabled={working || !d.paper_orders_enabled || !d.paused} onClick={() => void control("resume")}><Play size={14}/> Resume</button>
        </div>
      </div>
      {d.last_error && <p className="ac-warning">Worker diagnostic: {String(d.last_error)}</p>}
      {notice && <p role="status" className="ac-note">{notice}</p>}
      {response.error && <p role="alert" className="ac-warning">The crypto dashboard API is unavailable; no trading state is assumed.</p>}
    </section>

    <CryptoTradingOperations dashboard={d}/>
    <p className="ac-footnote">Paper trading only. Historical crypto bars are midpoint observations, not executable prices. Software exit thresholds cannot guarantee fills.</p>
  </main>;
}
