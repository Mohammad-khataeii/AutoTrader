import React, { useEffect, useMemo, useState } from "react";
import { createRoot } from "react-dom/client";
import { Activity, Bell, Brain, Gauge, LineChart, Settings, Shield, Wallet } from "lucide-react";
import { Area, AreaChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import "./styles.css";

type ScannerResponse = {
  status: string;
  scanned: number;
  duration_ms: string;
  rejected: Array<Record<string, unknown>>;
  provider_errors: string[];
  candidates: Array<Record<string, unknown>>;
  features: Record<string, string | number | null | object>;
  signals: Array<Record<string, unknown>>;
  ai: Record<string, unknown>;
  decision: Record<string, unknown>;
};

const tabs = [
  ["Overview", Wallet],
  ["Market Scanner", Activity],
  ["Opportunities", LineChart],
  ["Portfolio", Gauge],
  ["Backtesting", LineChart],
  ["AI Intelligence", Brain],
  ["Risk Center", Shield],
  ["Settings", Settings],
] as const;

function App() {
  const [active, setActive] = useState("Overview");
  const [scanner, setScanner] = useState<ScannerResponse | null>(null);
  const [overview, setOverview] = useState<Record<string, unknown> | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const headers = new Headers();
    headers.set("Authorization", `Basic ${btoa("admin:change-me")}`);
    Promise.all([
      fetch("/api/overview", { headers }).then((response) => response.json()),
      fetch("/api/scanner", { headers }).then((response) => response.json()),
    ])
      .then(([overviewPayload, scannerPayload]) => {
        setOverview(overviewPayload);
        setScanner(scannerPayload);
      })
      .catch((reason) => setError(String(reason)));
  }, []);

  const chartData = useMemo(() => {
    const portfolio = (overview?.portfolio ?? {}) as Record<string, string>;
    const available = Number(portfolio.available_cash ?? 0);
    const reserved = Number(portfolio.reserved_cash ?? 0);
    const exposure = Number(portfolio.open_exposure ?? 0);
    const equity = available + reserved + exposure;
    return [
      { time: "previous", equity, exposure },
      { time: "current", equity, exposure },
    ];
  }, [overview]);

  return (
    <main>
      <aside>
        <div className="brand">Revolut X AutoTrader</div>
        <nav>
          {tabs.map(([label, Icon]) => (
            <button key={label} className={active === label ? "active" : ""} onClick={() => setActive(label)} title={label}>
              <Icon size={18} />
              <span>{label}</span>
            </button>
          ))}
        </nav>
      </aside>
      <section className="workspace">
        <header>
          <div>
            <h1>{active}</h1>
            <p>Paper trading only. Market decisions require fresh Revolut X observations.</p>
          </div>
          <div className="status"><Bell size={16} /> Paper mode</div>
        </header>
        {error ? <div className="panel danger">{error}</div> : null}
        <Dashboard active={active} chartData={chartData} overview={overview} scanner={scanner} />
      </section>
    </main>
  );
}

function Dashboard({
  active,
  chartData,
  overview,
  scanner,
}: {
  active: string;
  chartData: Array<{ time: string; equity: number; exposure: number }>;
  overview: Record<string, unknown> | null;
  scanner: ScannerResponse | null;
}) {
  const portfolio = (overview?.portfolio ?? {}) as Record<string, string>;
  const decision = scanner?.decision ?? {};
  const signals = scanner?.signals ?? [];
  const candidates = scanner?.candidates ?? [];
  const rejected = scanner?.rejected ?? [];
  const providerErrors = scanner?.provider_errors ?? [];

  if (active === "Overview") {
    return (
      <>
        <div className="metrics">
          <Metric label="Available Cash" value={`EUR ${portfolio.available_cash ?? "500"}`} />
          <Metric label="Reserved Cash" value={`EUR ${portfolio.reserved_cash ?? "0"}`} />
          <Metric label="Open Exposure" value={`EUR ${portfolio.open_exposure ?? "0"}`} />
          <Metric label="Positions" value={portfolio.positions ?? "0"} />
        </div>
        <Chart data={chartData} />
        <ScannerHealth scanner={scanner} />
        <Decision decision={decision} />
      </>
    );
  }
  if (active === "Market Scanner" || active === "Opportunities") {
    return (
      <>
        <ScannerHealth scanner={scanner} />
        <div className="grid">
          {candidates.map((candidate, index) => (
            <article className="panel" key={String(candidate.symbol ?? index)}>
              <strong>{String(candidate.symbol)}</strong>
              <span className="score">{String(candidate.score)}</span>
              <p>{String(((candidate.decision as Record<string, unknown> | undefined) ?? {}).explanation ?? "No decision explanation.")}</p>
            </article>
          ))}
          {signals.map((signal, index) => (
            <article className="panel" key={String(signal.signal_id ?? index)}>
              <strong>{String(signal.strategy_id)}</strong>
              <span className="score">{String(signal.score)}</span>
              <p>{String(signal.explanation)}</p>
            </article>
          ))}
          {candidates.length === 0 && signals.length === 0 ? (
            <article className="panel">
              <strong>No accepted candidates</strong>
              <p>{providerErrors[0] ?? String(rejected[0]?.reasons ?? scanner?.status ?? "Waiting for scan data.")}</p>
            </article>
          ) : null}
        </div>
      </>
    );
  }
  if (active === "Portfolio") {
    return <pre className="panel">{JSON.stringify(overview?.positions ?? [], null, 2)}</pre>;
  }
  if (active === "Backtesting") {
    return (
      <>
        <Chart data={chartData} />
        <div className="panel">Backtests reuse the strategy, decision, risk, portfolio, and paper execution engines.</div>
      </>
    );
  }
  if (active === "AI Intelligence") {
    return <pre className="panel">{JSON.stringify(scanner?.ai ?? {}, null, 2)}</pre>;
  }
  if (active === "Risk Center") {
    return <Decision decision={decision} />;
  }
  return <div className="panel">Configuration is environment-driven. Edit risk limits, AI provider, model, and notification settings in `.env`.</div>;
}

function ScannerHealth({ scanner }: { scanner: ScannerResponse | null }) {
  return (
    <div className="metrics compact">
      <Metric label="Scanner Status" value={scanner?.status ?? "WAITING"} />
      <Metric label="Markets Scanned" value={String(scanner?.scanned ?? 0)} />
      <Metric label="Candidates" value={String(scanner?.candidates?.length ?? 0)} />
      <Metric label="Provider Errors" value={String(scanner?.provider_errors?.length ?? 0)} />
    </div>
  );
}

function Metric({ label, value }: { label: string; value: string }) {
  return (
    <div className="metric">
      <span>{label}</span>
      <strong>{value}</strong>
    </div>
  );
}

function Chart({ data }: { data: Array<{ time: string; equity: number; exposure: number }> }) {
  return (
    <div className="chart">
      <ResponsiveContainer width="100%" height={260}>
        <AreaChart data={data}>
          <XAxis dataKey="time" />
          <YAxis />
          <Tooltip />
          <Area dataKey="equity" stroke="#0f766e" fill="#99f6e4" />
          <Area dataKey="exposure" stroke="#be123c" fill="#fecdd3" />
        </AreaChart>
      </ResponsiveContainer>
    </div>
  );
}

function Decision({ decision }: { decision: Record<string, unknown> }) {
  return (
    <div className="panel">
      <strong>Latest Decision: {String(decision.action ?? "WAIT")}</strong>
      <p>{String(decision.explanation ?? "Waiting for scanner data.")}</p>
      <span className={decision.accepted ? "ok" : "blocked"}>{decision.accepted ? "Accepted" : "Rejected or waiting"}</span>
    </div>
  );
}

createRoot(document.getElementById("root")!).render(<App />);
