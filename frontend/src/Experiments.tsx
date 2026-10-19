import React, { useState } from "react";
import {
  ChevronLeft,
  Download,
  MoreHorizontal,
  Pause,
  Play,
  Plus,
} from "lucide-react";
import { type Row, useApi, useResource, errorMessage } from "./api";
import {
  dataKind,
  date,
  humanize,
  isOpen,
  lastEvaluation,
  money,
  number,
  percent,
  shortId,
  rejection,
  decisionSummary,
  stateName,
  strategyName,
} from "./model";
import {
  Badge,
  CompactTable,
  Confirm,
  Empty,
  EquityChart,
  Panel,
  Pnl,
  ResourceState,
  Technical,
} from "./ui";
import { DecisionTimeline } from "./DecisionTimeline";
export function Exports({ experiment }: { experiment: Row }) {
  const api = useApi();
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  return (
    <div>
      <details className="action-menu">
        <summary>
          <Download size={15} /> Export
        </summary>
        <div className="menu-options">
          {["Financial report", "Orders", "Fills", "Journal", "Equity"].map(
            (label) => (
              <button
                disabled={busy}
                key={label}
                onClick={async () => {
                  setBusy(true);
                  setError("");
                  const kind = label.toLowerCase();
                  try {
                    await api.download(
                      `/api/shadow/${experiment.experiment_id}/${label === "Financial report" ? "export" : `history/${kind}`}`,
                      `shadow-${experiment.experiment_id}-${label === "Financial report" ? "report.json" : kind + ".ndjson"}`,
                    );
                  } catch (e) {
                    setError(errorMessage(e));
                  } finally {
                    setBusy(false);
                  }
                }}
              >
                {label}
              </button>
            ),
          )}
        </div>
      </details>
      {error && (
        <p role="alert" className="loss">
          {error}
        </p>
      )}
    </div>
  );
}
export function ExperimentAction({
  experiment,
  onChanged,
}: {
  experiment: Row;
  onChanged: () => Promise<void>;
}) {
  const api = useApi();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  if (!["SHADOW_ACTIVE", "PAUSED"].includes(experiment.state)) return null;
  const action = experiment.state === "PAUSED" ? "resume" : "pause";
  return (
    <>
      <button
        className="secondary"
        aria-label={`${humanize(action)} experiment ${shortId(experiment.experiment_id)}`}
        disabled={busy}
        onClick={async () => {
          setBusy(true);
          setError("");
          try {
            await api.request(
              `/api/shadow/${experiment.experiment_id}/${action}`,
              "POST",
            );
            await onChanged();
          } catch (e) {
            setError(errorMessage(e));
          } finally {
            setBusy(false);
          }
        }}
      >
        {action === "pause" ? <Pause size={14} /> : <Play size={14} />}{" "}
        {humanize(action)}
      </button>
      {error && (
        <p role="alert" className="loss">
          {error}
        </p>
      )}
    </>
  );
}
export function Experiments() {
  const api = useApi();
  const resource = useResource("/api/shadow/summary", { poll: 20000 });
  const data = resource.data;
  const [showArchive, setShowArchive] = useState(false);
  const archive = useResource("/api/shadow/summary?archived=true", {
    enabled: showArchive,
    ttl: 30000,
  });
  const [deleting, setDeleting] = useState(false);
  const [selected, setSelected] = useState("");
  const [create, setCreate] = useState(false);
  const [stop, setStop] = useState(false);
  const [name, setName] = useState("");
  const [strategy, setStrategy] = useState("B2_CONFIRMED_COMPRESSION");
  const [review, setReview] = useState(false);
  const [requestId, setRequestId] = useState("");
  const experiments: Row[] = data?.experiments ?? [];
  const maximum = number(data?.maximum_experiments);
  const occupied = data?.occupied_slots ?? experiments.length;
  const full = maximum != null && occupied >= maximum;
  const detail = useResource(`/api/shadow/${selected}/view`, {
    enabled: Boolean(selected),
    poll: selected ? 30000 : 0,
  });
  const experiment = selected ? detail.data : undefined;
  const refresh = () => api.refreshVisible();
  const beginCreate = () => {
    setCreate(true);
    setName("");
    setRequestId(crypto.randomUUID());
  };
  if (selected && !experiment)
    return (
      <div className="page-stack">
        <button onClick={() => setSelected("")}>All experiments</button>
        <ResourceState resource={detail} label="Experiment details" />
      </div>
    );
  if (experiment)
    return (
      <div className="page-stack">
        <ResourceState resource={resource} label="Strategies" />
        {selected && (
          <ResourceState resource={detail} label="Experiment details" />
        )}
        <div className="section-heading">
          <button className="text-button" onClick={() => setSelected("")}>
            <ChevronLeft size={16} /> All experiments
          </button>
          <span className="muted small">
            Virtual account · {dataKind(experiment.manifest?.data_kind)}
          </span>
        </div>
        <div className="section-heading">
          <div>
            <h2 className="page-title">
              {strategyName(experiment.manifest?.strategy_id)}
            </h2>
            <p className="muted">
              {experiment.name} · Instance {shortId(selected)} · Started{" "}
              {date(experiment.created_at, true)}
            </p>
          </div>
          <Badge
            tone={experiment.state === "SHADOW_ACTIVE" ? "positive" : "neutral"}
          >
            {stateName(experiment.state)}
          </Badge>
        </div>
        {experiment.source_matches === false && (
          <div className="notice warning" role="alert">
            The frozen strategy configuration has changed. New entries are
            blocked; protective exits continue.
          </div>
        )}
        <div className="toolbar">
          {!experiment.archived_at && (
            <ExperimentAction experiment={experiment} onChanged={refresh} />
          )}
          <Exports experiment={experiment} />
          {!experiment.archived_at &&
            ["SHADOW_ACTIVE", "PAUSED"].includes(experiment.state) && (
              <details className="action-menu">
                <summary aria-label="More experiment actions">
                  <MoreHorizontal size={18} />
                </summary>
                <div className="menu-options">
                  <button className="loss" onClick={() => setStop(true)}>
                    Stop permanently
                  </button>
                </div>
              </details>
            )}
        </div>
        {experiment.archived_at && (
          <p className="notice">
            Archived {date(experiment.archived_at, true)}. The original account
            and complete exports are preserved; this account cannot resume.
          </p>
        )}
        {experiment.archive_enabled === true && !experiment.archived_at &&
          ["PAUSED", "STOPPED"].includes(experiment.state) && (
            <details className="action-menu">
              <summary>Manage experiment</summary>
              <button className="loss" onClick={() => setDeleting(true)}>
                Delete experiment
              </button>
            </details>
          )}
        {deleting && (
          <Confirm
            title="Delete this experiment from the workspace?"
            action="Archive and free slot"
            danger
            onCancel={() => setDeleting(false)}
            onConfirm={async () => {
              await api.request(
                `/api/shadow/${selected}?confirm=${encodeURIComponent(selected)}`,
                "DELETE",
              );
              setSelected("");
              setDeleting(false);
              await refresh();
            }}
          >
            <p>
              This permanently stops this instance, archives its complete
              financial history, and frees one slot for a new independent
              account. Its identity, balance and history are never reset or
              reused.
            </p>
            <p>
              Open positions or unsettled orders prevent deletion. Archived
              accounts cannot resume; their records and exports remain
              accessible.
            </p>
          </Confirm>
        )}
        <div className="detail-metrics">
          <div>
            <span>Virtual equity</span>
            <strong>{money(experiment.portfolio?.equity)}</strong>
          </div>
          <div>
            <span>Net profit / loss</span>
            <strong>
              <Pnl value={experiment.performance?.net_pnl} />
            </strong>
          </div>
          <div>
            <span>Closed positions</span>
            <strong>
              {experiment.performance?.closed_trades ?? "Unavailable"}
            </strong>
          </div>
          <div>
            <span>Fees paid</span>
            <strong>{money(experiment.performance?.fees)}</strong>
          </div>
        </div>
        <EquityChart
          rows={experiment.history?.equity ?? []}
          caption="This experiment only"
        />
        <DecisionTimeline key={selected} identity={selected} />
        <Panel>
          <h2>Strategy approach</h2>
          <p>
            {data?.presets?.find(
              (p: Row) => p.strategy_id === experiment.manifest?.strategy_id,
            )?.hypothesis ??
              "The frozen strategy explanation is available in Research."}
          </p>
          <p className="muted">
            Unvalidated experiment. This account never grants approval to the
            official paper portfolio.
          </p>
          {lastEvaluation(experiment) && (
            <p className="small muted">
              Last evaluated {date(lastEvaluation(experiment), true)}
            </p>
          )}
        </Panel>
        <Panel>
          <div className="section-heading">
            <h2>Positions</h2>
            <span className="muted small">All simulated</span>
          </div>
          <CompactTable
            label="Experiment positions"
            rows={experiment.positions ?? []}
            columns={[
              { label: "Coin", render: (r) => r.symbol },
              {
                label: "Quantity",
                render: (r) =>
                  number(r.quantity)?.toLocaleString("en-GB", {
                    maximumFractionDigits: 8,
                  }) ?? "Unavailable",
              },
              { label: "Entry", render: (r) => money(r.average_entry_price) },
              {
                label: "Realized P&L",
                render: (r) => <Pnl value={r.realized_pnl} />,
              },
              {
                label: "Status",
                render: (r) => (isOpen(r) ? "Open" : "Closed"),
              },
            ]}
          />
        </Panel>
        <details className="disclosure panel">
          <summary>Orders and partial executions</summary>
          <CompactTable
            label="Experiment orders"
            rows={experiment.orders ?? []}
            columns={[
              { label: "Coin", render: (r) => r.symbol },
              { label: "Side", render: (r) => humanize(r.side) },
              { label: "Status", render: (r) => humanize(r.status) },
              { label: "Quantity", render: (r) => r.quantity },
              { label: "Filled", render: (r) => r.filled_quantity },
            ]}
          />
          <h3>Confirmed fills</h3>
          <CompactTable
            label="Experiment fills"
            rows={experiment.fills ?? []}
            columns={[
              { label: "Side", render: (r) => humanize(r.side) },
              { label: "Quantity", render: (r) => r.quantity },
              { label: "Price", render: (r) => money(r.price) },
              { label: "Fee", render: (r) => money(r.fee) },
            ]}
          />
        </details>
        <details className="disclosure panel">
          <summary>Performance and financial integrity</summary>
          <dl className="facts">
            <div>
              <dt>Win rate</dt>
              <dd>{percent(experiment.performance?.win_rate)}</dd>
            </div>
            <div>
              <dt>Profit factor</dt>
              <dd>{experiment.performance?.profit_factor ?? "Unavailable"}</dd>
            </div>
            <div>
              <dt>Maximum drawdown</dt>
              <dd>{percent(experiment.performance?.max_drawdown)}</dd>
            </div>
            <div>
              <dt>Financial records</dt>
              <dd>
                {Array.isArray(experiment.reconciliation)
                  ? experiment.reconciliation.length
                    ? "Review required"
                    : "Financial records consistent"
                  : "Not checked"}
              </dd>
            </div>
          </dl>
          {experiment.reconciliation?.length > 0 && (
            <p role="alert" className="notice warning">
              Financial records need review. Inspect the technical report before
              taking further action.
            </p>
          )}
          <p className="small muted">
            Recent details and chart show up to{" "}
            {experiment.history_window_limit ?? 500} records. Complete exports
            have no row limit. Headline fees and maximum drawdown use full
            history.
          </p>
        </details>
        <Technical
          value={{
            experiment_id: selected,
            manifest: experiment.manifest,
            source_matches: experiment.source_matches,
            history: experiment.history,
            positions: experiment.positions,
            orders: experiment.orders,
            fills: experiment.fills,
            targets: experiment.targets,
            reconciliation: experiment.reconciliation,
          }}
        />
        {stop && (
          <Confirm
            title="Stop this experiment permanently?"
            action="Stop permanently"
            danger
            onCancel={() => setStop(false)}
            onConfirm={async () => {
              await api.request(`/api/shadow/${selected}/stop`, "POST");
              await refresh();
            }}
          >
            <p>
              Instance {shortId(selected)} cannot be resumed after stopping.
              Protective exits remain active for open positions.
            </p>
            <p>
              Its full history is preserved. Stopping does not free an
              experiment slot.
            </p>
          </Confirm>
        )}
      </div>
    );
  return (
    <div className="page-stack">
      <div className="section-heading">
        <div>
          <h2 className="page-title">Your virtual strategies</h2>
          <p className="muted">Independent virtual accounts. No real money.</p>
        </div>
        {data && !full && data.enabled && maximum != null && (
          <button
            className="primary"
            disabled={Boolean(resource.error) || resource.loading}
            onClick={beginCreate}
          >
            <Plus size={16} /> New experiment
          </button>
        )}
      </div>
      <ResourceState resource={resource} label="Strategies" />
      {full && (
        <div className="slot-note">
          {experiments.length} of {maximum} experiment slots used. Existing
          experiment histories are preserved, including stopped experiments.
          Archiving is disabled during this investigation. Preserve existing history and
          free a slot.
        </div>
      )}
      {data && !data.enabled && (
        <div className="notice warning">
          New experiments are disabled by the server.
        </div>
      )}
      <div className="experiment-grid">
        {experiments
          .filter((e) => e.state !== "STOPPED")
          .map((e) => (
            <article className="experiment-card" key={e.experiment_id}>
              <button
                className="card-open"
                aria-label={`Open ${strategyName(e.manifest?.strategy_id)} ${shortId(e.experiment_id)}`}
                onClick={() => setSelected(e.experiment_id)}
              >
                <div className="section-heading">
                  <span className="strategy-letter">
                    {(e.manifest?.strategy_id ?? "?").split("_")[0]}
                  </span>
                  <Badge
                    tone={e.state === "SHADOW_ACTIVE" ? "positive" : "neutral"}
                  >
                    {stateName(e.state)}
                  </Badge>
                </div>
                <h3>{strategyName(e.manifest?.strategy_id)}</h3>
                <p className="muted small">
                  {e.manifest?.strategy_id?.split("_")[0]} · Instance{" "}
                  {shortId(e.experiment_id)}
                </p>
                <div className="card-equity">
                  <span>Virtual equity</span>
                  <strong>{money(e.portfolio?.equity)}</strong>
                </div>
                <div className="card-stats">
                  <div>
                    <span>Net P&L</span>
                    <strong>
                      <Pnl value={e.performance?.net_pnl} />
                    </strong>
                  </div>
                  <div>
                    <span>Closed positions</span>
                    <strong>
                      {e.performance?.closed_trades ?? "Unavailable"}
                    </strong>
                  </div>
                  <div>
                    <span>Open positions</span>
                    <strong>{e.portfolio?.positions ?? "Unavailable"}</strong>
                  </div>
                </div>
                <p className="muted small">
                  Started {date(e.created_at, true)}
                </p>
                {lastEvaluation(e) && (
                  <p className="muted small">
                    Last evaluated {date(lastEvaluation(e), true)}
                  </p>
                )}
                {e.latest_decision && (
                  <p className="small muted">
                    Latest:{" "}
                    {decisionSummary(e.latest_decision)}
                  </p>
                )}
                {e.source_matches === false && (
                  <p className="warning-text">
                    Configuration changed · new entries blocked
                  </p>
                )}
              </button>
              <div className="card-footer">
                <span className="muted small">
                  {dataKind(e.manifest?.data_kind)}
                </span>
                <ExperimentAction experiment={e} onChanged={refresh} />
              </div>
            </article>
          ))}
      </div>
      {experiments.some((e) => e.state === "STOPPED") && (
        <Panel>
          <h2>Stopped experiments</h2>
          <p className="muted small">
            History is retained. Stopping alone does not free a slot.
          </p>
          {experiments
            .filter((e) => e.state === "STOPPED")
            .map((e) => (
              <div
                className="section-heading historical-experiment"
                key={e.experiment_id}
              >
                <div>
                  <strong>
                    {strategyName(e.manifest?.strategy_id)} ·{" "}
                    {shortId(e.experiment_id)}
                  </strong>
                  <p className="small muted">
                    Stopped · Started {date(e.created_at, true)} · Net P&amp;L{" "}
                    <Pnl value={e.performance?.net_pnl} />
                  </p>
                </div>
                <button
                  aria-label={`Open ${strategyName(e.manifest?.strategy_id)} ${shortId(e.experiment_id)}`}
                  onClick={() => setSelected(e.experiment_id)}
                >
                  View history
                </button>
              </div>
            ))}
        </Panel>
      )}
      <details
        className="panel disclosure"
        onToggle={(e) => setShowArchive(e.currentTarget.open)}
      >
        <summary>Archived experiments ({data?.archived_count ?? 0})</summary>
        {showArchive && (
          <>
            <ResourceState resource={archive} label="Archived experiments" />
            {(archive.data?.experiments ?? []).map((e: Row) => (
              <div
                className="section-heading historical-experiment"
                key={e.experiment_id}
              >
                <div>
                  <strong>
                    {strategyName(e.manifest?.strategy_id)} ·{" "}
                    {shortId(e.experiment_id)}
                  </strong>
                  <p className="small muted">
                    Archived {date(e.archived_at, true)}
                  </p>
                </div>
                <button onClick={() => setSelected(e.experiment_id)}>
                  View archived history
                </button>
              </div>
            ))}
          </>
        )}
      </details>
      {data && !experiments.length && (
        <Panel>
          <Empty title="No experiments yet.">
            Create an explicitly unvalidated virtual account when you are ready.
            Each workspace account uses one slot. Archive a paused or stopped
            flat account to free it while retaining its history.
          </Empty>
        </Panel>
      )}
      {create && (
        <Panel>
          <h2>New experiment</h2>
          <p className="muted">
            Each experiment receives its own €500 virtual account. Histories are
            permanent.
          </p>
          <div className="form-grid">
            <label>
              Experiment name
              <input
                value={name}
                onChange={(e) => setName(e.target.value)}
                maxLength={128}
              />
            </label>
            <label>
              Shadow strategy
              <select
                value={strategy}
                onChange={(e) => setStrategy(e.target.value)}
              >
                {(data?.presets ?? []).map((p: Row) => (
                  <option value={p.strategy_id} key={p.strategy_id}>
                    {strategyName(p.strategy_id)}
                  </option>
                ))}
              </select>
            </label>
          </div>
          <div className="toolbar">
            <button onClick={() => setCreate(false)}>Cancel</button>
            <button
              className="primary"
              disabled={!name.trim() || full}
              onClick={() => setReview(true)}
            >
              Review experiment
            </button>
          </div>
        </Panel>
      )}
      {review && (
        <Confirm
          title="Create a permanent research account?"
          action="Create experiment"
          onCancel={() => setReview(false)}
          onConfirm={async () => {
            if (full)
              throw new Error("All retained experiment slots are occupied.");
            const result = await api.request("/api/shadow", "POST", {
              request_id: requestId,
              name: name.trim(),
              strategy_id: strategy,
            });
            await refresh();
            setSelected(result.experiment_id);
            setCreate(false);
          }}
        >
          <p>
            {strategyName(strategy)} · {name}
          </p>
          <p>
            This creates an unvalidated €500 simulation using one of {maximum}{" "}
            workspace slots. Stopping alone does not free the slot; explicitly
            deleting a paused or stopped flat account archives its history and
            frees it.
          </p>
        </Confirm>
      )}
    </div>
  );
}
