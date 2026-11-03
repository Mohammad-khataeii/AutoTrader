import { useState } from "react";
import { errorMessage, useApi, useResource } from "./api";
import { Badge, Panel, ResourceState, Technical } from "./ui";

const path = "/api/perpetuals";
type Position = {
  side: number;
  qty: string;
  entry: string;
  notional: string;
  margin: string;
  stop: string;
  target: string;
  liquidation_mark: string;
  funding: string;
};
type Account = {
  leverage: number;
  equity: string;
  cash: string;
  realized: string;
  max_drawdown: string;
  closed: number;
  liquidations: number;
  halted: boolean;
  position: Position | null;
};
type LabEvent = {
  kind: string;
  minute: number;
  leverage?: number;
  net?: string;
  amount?: string;
};
type Lab = {
  available: boolean;
  data_fresh: boolean;
  feed_status: string;
  entries_enabled: boolean;
  mark: string | null;
  bar_closed_at: number | null;
  pending: { side: number; fill_at: number } | null;
  accounts: Account[];
  events: LabEvent[];
};

const amount = (value: string | null | undefined, digits = 2) =>
  value == null ? "—" : Number(value).toLocaleString(undefined, { maximumFractionDigits: digits, minimumFractionDigits: digits });
const usdt = (value: string | null | undefined) => value == null ? "—" : amount(value) + " USDT";
const at = (ms: number) => new Date(ms).toLocaleString();
const side = (value: number) => value === 1 ? "Long" : "Short";
const feedLabel: Record<string, string> = {
  DISABLED: "Disabled", WAITING: "Waiting for market data", CURRENT: "Market data current",
  STALE: "Market data stale", DEGRADED: "Market data unavailable or incomplete",
};
const eventLabel: Record<string, string> = {
  SIGNAL: "Signal queued", OPEN: "Opened", FUNDING: "Funding", STOP: "Stop",
  TARGET: "Target", TIME_EXIT: "Time exit", LIQUIDATION: "Liquidated", RISK_HALT: "Risk halt",
  ENTRY_SKIPPED: "Entry skipped", ENTRY_EXPIRED: "Entry expired",
  RESUME_ENTRIES: "Entries resumed", PAUSE_ENTRIES: "Entries paused",
};

export function Perpetuals() {
  const api = useApi();
  const resource = useResource(path, { poll: 12000 });
  const lab = resource.data as Lab | undefined;
  const [busy, setBusy] = useState(false);
  const [problem, setProblem] = useState("");
  async function change(enabled: boolean) {
    setBusy(true);
    setProblem("");
    try {
      await api.request(path + "/entries", "POST", { enabled });
      await api.refresh(path);
    } catch (error) {
      setProblem(errorMessage(error));
    } finally {
      setBusy(false);
    }
  }

  return <>
    <ResourceState resource={resource} label="Perpetuals lab" />
    {lab && <>
      <Panel>
        <h2>BTC/USDT perpetuals</h2>
        <p>Paper only · isolated margin · 1×, 3× and 10× accounts each start with 1,000 simulated USDT.</p>
        <p>The same breakout rules run across all three accounts. Position size follows a loss budget; 10× sets the margin requirement.</p>
        <Badge tone={lab.data_fresh && !resource.error ? "positive" : "warning"}>{feedLabel[lab.feed_status] ?? "Unknown"}</Badge>
        <p>Bybit mark: <strong>{usdt(lab.mark)}</strong>{lab.bar_closed_at && <> · Last processed minute closed {at(lab.bar_closed_at)}</>}</p>
        {lab.available ? <>
          <p>{lab.entries_enabled ? "New entries enabled" : "New entries paused"}. Pausing entries keeps protection running for open positions.</p>
          {lab.pending && <p>{side(lab.pending.side)} entry queued for the minute starting {at(lab.pending.fill_at)}.</p>}
          <button className="button" disabled={busy || (!lab.entries_enabled && (!lab.data_fresh || Boolean(resource.error)))}
            onClick={() => void change(!lab.entries_enabled)}>{lab.entries_enabled ? "Pause new entries" : "Enable paper entries"}</button>
        </> : <p>Enable the Perpetuals lab in the local or staging configuration to start receiving market data.</p>}
        {problem && <p role="alert" className="notice warning">{problem}</p>}
      </Panel>
      <div className="perp-accounts">
        {lab.accounts.map(a => <Panel key={a.leverage}>
          <h3>{a.leverage}× isolated</h3>
          <p>Equity <strong>{usdt(a.equity)}</strong></p>
          <p>Free cash {usdt(a.cash)} · Closed P&amp;L {usdt(a.realized)}</p>
          <p>{a.closed} closed · {a.liquidations} liquidated · {(Number(a.max_drawdown) * 100).toFixed(2)}% max drawdown</p>
          {a.halted && <Badge tone="warning">Drawdown limit reached; new entries halted</Badge>}
          {a.position ? <div>
            <p><strong>{side(a.position.side)}</strong> · {amount(a.position.qty, 6)} BTC · Entry {usdt(a.position.entry)}</p>
            <p>Notional {usdt(a.position.notional)} · Margin {usdt(a.position.margin)} · Funding {usdt(a.position.funding)}</p>
            <p>Stop {usdt(a.position.stop)} · Target {usdt(a.position.target)} · Model liquidation mark {usdt(a.position.liquidation_mark)}</p>
          </div> : <p>No open position.</p>}
        </Panel>)}
      </div>
      <Panel>
        <h2>Recent simulated activity</h2>
        {lab.events.length === 0 ? <p>No activity yet.</p> : <>
          <ul>{lab.events.slice(0, 20).map((event, index) => <li key={event.minute + ":" + index}>
            {at(event.minute)} · {event.leverage ? event.leverage + "× · " : ""}{eventLabel[event.kind] ?? event.kind}
            {event.net != null || event.amount != null ? " · " + usdt(event.net ?? event.amount) : ""}
          </li>)}</ul>
          <Technical value={lab.events} label="Last 60 event records" />
        </>}
      </Panel>
    </>}
  </>;
}
