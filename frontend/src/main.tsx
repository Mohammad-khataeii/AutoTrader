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
import { Badge } from "./ui";
import { Overview } from "./Overview";
import { Experiments } from "./Experiments";
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
  { name: "Experiments", icon: FlaskConical },
  { name: "Trades", icon: ArrowRightLeft },
  { name: "Research", icon: BarChart3 },
];
function Workspace({ auth, onLogout }: { auth: string; onLogout: () => void }) {
  const api = useApi();
  const [active, setActive] = useState("Overview");
  const [advanced, setAdvanced] = useState("Official Account Controls");
  const menu = useRef<HTMLDetailsElement>(null);
  const overview = useResource("/api/overview");
  const system = useResource("/api/system", { poll: 15000 });
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
            AutoTrader<span>Virtual markets</span>
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
              <span>Advanced</span>
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
          <p className="build-label">Interface 4.3 · Paper trading</p>
        </div>
      </aside>
      <main id="workspace" className="workspace">
        <header className="app-header">
          <div>
            <p className="eyebrow">
              {active === "Advanced"
                ? "Workspace / Advanced"
                : "Your trading workspace"}
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
                const paths = [
                  "/api/system",
                  "/api/overview",
                  "/readyz",
                  ...(active === "Overview" ||
                  active === "Experiments" ||
                  active === "Trades"
                    ? ["/api/shadow"]
                    : []),
                  ...(active === "Research" ? ["/api/research"] : []),
                  ...(active === "Advanced"
                    ? ({
                        "Official Account Controls": [],
                        "Market monitor": ["/api/scanner"],
                        "Decision journal": ["/api/history"],
                        "Execution diagnostics": ["/api/execution"],
                        "AI & budgets": ["/api/ai", "/api/scanner"],
                        "Risk & recovery": ["/api/settings", "/api/history"],
                        "System & data health": ["/api/market-data/health"],
                        "Paper pilot": ["/api/pilots"],
                        Settings: ["/api/settings"],
                      }[advanced] ?? [])
                    : []),
                ];
                try {
                  await api.refresh(...paths);
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
        {active === "Overview" && (
          <Overview
            system={system}
            onExperiments={() => setActive("Experiments")}
          />
        )}{" "}
        {active === "Experiments" && <Experiments />}
        {active === "Trades" && <Trades />}
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
              ? "Real-money trading disabled"
              : "Simulated workspace · trading-mode check unavailable"}
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
        <span>AutoTrader</span>
      </div>
      <section className="login-card">
        <p className="eyebrow">Your virtual trading workspace</p>
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
              const data = await api.load("/api/overview", true);
              if (!data?.portfolio)
                throw new Error(
                  api.entry("/api/overview").snapshot.error ??
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
          Paper trading and isolated simulations. No real-money trading.
        </p>
      </section>
    </main>
  );
}
if (typeof document !== "undefined" && document.getElementById("root"))
  createRoot(document.getElementById("root")!).render(<App />);
