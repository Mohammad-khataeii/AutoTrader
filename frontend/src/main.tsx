import React, { Suspense, lazy, useEffect, useRef, useState } from "react";
import { createRoot } from "react-dom/client";
import {
  Activity,
  ArrowRightLeft,
  BarChart3,
  ChevronDown,
  FlaskConical,
  LayoutDashboard,
  LogOut,
  RefreshCw,
  SlidersHorizontal,
} from "lucide-react";
import {
  ApiClient,
  ApiContext,
  errorMessage,
  useApi,
  useResource,
} from "./api";
import { systemStatus } from "./model";
import { Badge, ResourceState } from "./ui";
const TradeGates = lazy(() => import("./TradeGates").then(m => ({ default: m.TradeGates })));
import { Overview } from "./Overview";
import { Dashboard } from "./Dashboard";
import { PersonalPaper } from "./PersonalPaper";
const Opportunities = lazy(() => import("./Opportunities").then(m => ({ default: m.Opportunities })));
const StrategiesWorkspace = lazy(() => import("./Opportunities").then(m => ({ default: m.StrategiesWorkspace })));
const Trades = lazy(() => import("./Trades").then(m => ({ default: m.Trades })));
const Research = lazy(() => import("./Research").then(m => ({ default: m.Research })));
import { advancedItems } from "./navigation";
const AdvancedScreen = lazy(() => import("./advanced").then(m => ({ default: m.AdvancedScreen })));
import "./styles.css";
// Retained public formatter for existing callers; primary screens use localized EUR formatting.
export function displayMoney(value: unknown): string {
  return value === "" || value == null || !Number.isFinite(Number(value))
    ? "Unavailable"
    : `EUR ${Number(value).toFixed(2)}`;
}
const navigation = [
  { name: "Dashboard", icon: LayoutDashboard },
  { name: "Opportunities", icon: Activity },
  { name: "Strategies", icon: FlaskConical },
  { name: "Activity", icon: ArrowRightLeft },
  { name: "Research", icon: BarChart3 },
  { name: "Decision Insights", icon: Activity },
];
function Workspace({ auth, onLogout }: { auth: string; onLogout: () => void }) {
  const api = useApi();
  const [active, setActive] = useState("Dashboard");
  const [advanced, setAdvanced] = useState("Official Account Controls");
  const menu = useRef<HTMLDetailsElement>(null);
  const overview = useResource("/api/overview/summary");
  const system = useResource("/api/monitoring/summary", { poll: 15000 });
  const primary = useResource("/api/personal-paper", { poll: 15000 });
  const readiness = useResource("/readyz", { ttl: 60000 });
  const [refreshing, setRefreshing] = useState(false);
  const legacyStatus = systemStatus(
    system.data,
    overview.data?.portfolio?.control,
    Boolean(system.error || overview.error),
  );
  const primaryStatus = primary.error ? "Unavailable" : !primary.data?.portfolio ? "Checking" : primary.data?.reconciliation?.length || primary.data?.portfolio?.risk_state !== "HEALTHY" ? "Needs attention" : primary.data?.portfolio?.control !== "RUNNING" ? "Paused" : primary.data?.state === "PAPER_EXPERIMENTAL_ACTIVE" && primary.data?.worker_health?.fresh ? "Running" : primary.data?.runtime_matches === false ? "Entry suspended" : "Data syncing";
  const status = active === "Advanced" ? legacyStatus : primaryStatus;
  return (
    <div className="app-shell">
      <a className="skip-link" href="#workspace">
        Skip to content
      </a>
      <aside className="sidebar">
        <div className="brand">
          <span className="brand-mark">
            <Activity size={20} />
          </span>
          <div>
            Personal Plan<span>Private portfolio</span>
          </div>
        </div>
        <nav aria-label="Primary navigation">
          {navigation.map(({ name, icon: Icon }) => (
            <button
              key={name}
              aria-current={active === name ? "page" : undefined}
              onClick={() => setActive(name)}
            >
              <Icon size={18} />
              <span>{name}</span>
            </button>
          ))}
        </nav>
        <div className="sidebar-footer">
          <details ref={menu} className="advanced-menu">
            <summary>
              <SlidersHorizontal size={17} />
              <span>Settings</span>
              <ChevronDown size={14} />
            </summary>
            <div className="advanced-options">
              {advancedItems.map((name) => (
                <button
                  key={name}
                  onClick={() => {
                    setAdvanced(name);
                    setActive("Advanced");
                    if (menu.current) menu.current.open = false;
                  }}
                >
                  {name}
                </button>
              ))}
            </div>
          </details>
          <p className="build-label">Interface 4.8.0 · Simulated Mode</p>
        </div>
      </aside>
      <main id="workspace" className="workspace">
        <header className="app-header">
          <div>
            <p className="eyebrow">
              {active === "Advanced"
                ? "Workspace / Settings"
                : "Your personal portfolio"}
            </p>
            <h1>{active === "Advanced" ? advanced : active}</h1>
          </div>
          <div className="header-actions">
            <Badge
              tone={
                status === "Running"
                  ? "positive"
                  : status === "Checking"
                    ? "neutral"
                    : "warning"
              }
            >
              {status}
            </Badge>
            <button
              className="icon-button"
              aria-label="Refresh current view"
              title="Refresh current view"
              disabled={refreshing}
              onClick={async () => {
                setRefreshing(true);
                try {
                  await api.refreshVisible();
                } finally {
                  setRefreshing(false);
                }
              }}
            >
              <RefreshCw size={17} />
            </button>
            <button
              className="icon-button"
              aria-label="Sign out"
              title="Sign out"
              onClick={onLogout}
            >
              <LogOut size={17} />
            </button>
          </div>
        </header>
        {legacyStatus !== "Running" && <details className="legacy-health"><summary>Separate official / legacy account status: {legacyStatus}</summary><p>The €7,000 primary portfolio has its own health checks. Historical shadow runtime incompatibilities suspend their entries independently. Open Settings for the full legacy account diagnostics.</p></details>}
        {readiness.error && (
          <ResourceState
            resource={readiness}
            label="Execution-mode verification"
          />
        )}
        {readiness.data?.live_trading_enabled === true && (
          <div role="alert" className="notice warning">
            Unexpected real-money configuration. Stop and review the server
            configuration.
          </div>
        )}
        {system.error && active !== "Dashboard" && (
          <div className="notice warning" role="alert">
            Status refresh unavailable. Displayed information is from the last
            successful update.
          </div>
        )}
        <Suspense fallback={<div className="loading" role="status">Loading workspace…</div>}>
        {active === "Decision Insights" && <><PersonalPaper view="monitor"/><TradeGates /></>}
        {active === "Dashboard" && <Dashboard/>}
        {active === "Opportunities" && <><PersonalPaper view="opportunities"/><Opportunities /></>}
        {active === "Strategies" && <><PersonalPaper view="strategies"/><StrategiesWorkspace /></>}
        {active === "Activity" && <><PersonalPaper view="activity"/><Trades /></>}
        {active === "Research" && <><PersonalPaper view="research"/><Research auth={auth} /></>}{" "}
        {active === "Advanced" && (
          advanced === "Accounts overview" ? <Overview system={system} onExperiments={() => setActive("Strategies")}/> : <AdvancedScreen key={advanced} page={advanced} auth={auth} />
        )}
        </Suspense>
        <footer className="workspace-footer">
          <span>
            Official paper account and shadow experiments are separate.
          </span>
          <span>
            {readiness.data?.live_trading_enabled === false
              ? "Real-money execution disabled"
              : "Simulated workspace · execution-mode check unavailable"}
          </span>
        </footer>
      </main>
    </div>
  );
}
function App() {
  const [session, setSession] = useState<{
    api: ApiClient;
    auth: string;
  } | null>(null);
  const [username, setUsername] = useState("admin"),
    [password, setPassword] = useState(""),
    [error, setError] = useState(""),
    [busy, setBusy] = useState(false);
  const [restoring, setRestoring] = useState(true);
  const [restoreError, setRestoreError] = useState("");
  const enter = (csrf: string) => {
    const api = new ApiClient("");
    api.csrfToken = csrf;
    api.onUnauthorized = () => {
      api.dispose(); setSession(null); setError("Your session expired. Please sign in again.");
    };
    setSession({api, auth: ""});
  };
  const restore = async () => {
    setRestoreError("");
    try {
      const response = await fetch("/api/session", {credentials: "same-origin", cache: "no-store"});
      if (response.status === 401) { setRestoring(false); return; }
      if (!response.ok) throw new Error("The server is temporarily unavailable. Retry to restore your session.");
      const body = await response.json();
      if (!body.csrf_token) throw new Error("The session response could not be verified.");
      enter(body.csrf_token); setRestoring(false);
    } catch (e) { setRestoreError(errorMessage(e)); }
  };
  useEffect(() => { void restore(); }, []);
  if (restoring) return <main className="login-page"><section className="login-card"><h1>Opening your dashboard</h1>{restoreError ? <><p role="alert">{restoreError}</p><button onClick={() => void restore()}>Retry connection</button></> : <p role="status">Restoring your session…</p>}</section></main>;
  if (session)
    return (
      <ApiContext.Provider value={session.api}>
        <Workspace
          auth={session.auth}
          onLogout={async () => {
            try { await session.api.request("/api/session", "DELETE"); }
            catch (e) { setError(errorMessage(e)); return; }
            session.api.dispose(); setSession(null); setError("");
          }}
        />
      </ApiContext.Provider>
    );
  return (
    <main className="login-page">
      <div className="login-brand">
        <Activity size={24} />
        <span>Personal Plan</span>
      </div>
      <section className="login-card">
        <p className="eyebrow">Your simulated portfolio workspace</p>
        <h1>Welcome back</h1>
        <p className="muted">
          Sign in to follow your strategies and virtual accounts.
        </p>
        <form
          onSubmit={async (e) => {
            e.preventDefault();
            if (busy) return;
            setBusy(true);
            setError("");
            const credential = `Basic ${btoa(String.fromCharCode(...new TextEncoder().encode(`${username}:${password}`)))}`;
            const api = new ApiClient(credential);
            try {
              const data = await api.request("/api/session", "POST");
              if (!data?.csrf_token) throw new Error("The session response could not be verified.");
              api.dispose();
              enter(data.csrf_token);
              setPassword("");
            } catch (reason) {
              api.dispose();
              setError(errorMessage(reason));
            } finally {
              setBusy(false);
            }
          }}
        >
          <label>
            Username
            <input
              autoComplete="username"
              value={username}
              onChange={(e) => setUsername(e.target.value)}
              required
            />
          </label>
          <label>
            Password
            <input
              type="password"
              autoComplete="current-password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              required
            />
          </label>
          {error && (
            <p role="alert" className="notice warning">
              {error}
            </p>
          )}
          <button className="primary" type="submit" disabled={busy}>
            {busy ? "Signing in…" : "Sign in"}
          </button>
        </form>
        <p className="small muted login-footnote">
          Simulated orders and isolated portfolios. Real-money execution is disabled.
        </p>
      </section>
    </main>
  );
}
if (typeof document !== "undefined" && document.getElementById("root"))
  createRoot(document.getElementById("root")!).render(<App />);
