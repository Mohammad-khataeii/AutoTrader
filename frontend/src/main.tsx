import React, { useRef, useState } from "react";
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
import { TradeGates } from "./TradeGates";
import { Overview } from "./Overview";
import { Opportunities, StrategiesWorkspace } from "./Opportunities";
import { Trades } from "./Trades";
import { Research } from "./Research";
import { AdvancedScreen, advancedItems } from "./advanced";
import "./styles.css";
// Retained public formatter for existing callers; primary screens use localized EUR formatting.
export function displayMoney(value: unknown): string {
  return value === "" || value == null || !Number.isFinite(Number(value))
    ? "Unavailable"
    : `EUR ${Number(value).toFixed(2)}`;
}
const navigation = [
  { name: "Overview", icon: LayoutDashboard },
  { name: "Opportunities", icon: Activity },
  { name: "Strategies", icon: FlaskConical },
  { name: "Activity", icon: ArrowRightLeft },
  { name: "Research", icon: BarChart3 },
  { name: "Decision Insights", icon: Activity },
];
function Workspace({ auth, onLogout }: { auth: string; onLogout: () => void }) {
  const api = useApi();
  const [active, setActive] = useState("Overview");
  const [advanced, setAdvanced] = useState("Official Account Controls");
  const menu = useRef<HTMLDetailsElement>(null);
  const overview = useResource("/api/overview/summary");
  const system = useResource("/api/monitoring/summary", { poll: 15000 });
  const readiness = useResource("/readyz", { ttl: 60000 });
  const [refreshing, setRefreshing] = useState(false);
  const status = systemStatus(
    system.data,
    overview.data?.portfolio?.control,
    Boolean(system.error || overview.error),
  );
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
          <p className="build-label">Interface 4.6 · Simulated Mode</p>
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
        {system.error && active !== "Overview" && (
          <div className="notice warning" role="alert">
            Status refresh unavailable. Displayed information is from the last
            successful update.
          </div>
        )}
        {active === "Decision Insights" && <TradeGates />}
        {active === "Overview" && (
          <Overview
            system={system}
            onExperiments={() => setActive("Strategies")}
          />
        )}{" "}
        {active === "Opportunities" && <Opportunities />}
        {active === "Strategies" && <StrategiesWorkspace />}
        {active === "Activity" && <Trades />}
        {active === "Research" && <Research auth={auth} />}{" "}
        {active === "Advanced" && (
          <AdvancedScreen key={advanced} page={advanced} auth={auth} />
        )}
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
  if (session)
    return (
      <ApiContext.Provider value={session.api}>
        <Workspace
          auth={session.auth}
          onLogout={() => {
            session.api.dispose();
            setSession(null);
            setError("");
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
              const data = await api.load("/api/overview/summary", true);
              if (!data?.portfolio)
                throw new Error(
                  api.entry("/api/overview/summary").snapshot.error ??
                    "Account data is unavailable.",
                );
              setSession({ api, auth: credential });
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
