import React, { useState } from "react";
import { ChevronLeft } from "lucide-react";
import { type Row, useResource } from "./api";
import {
  money,
  parse,
  percent,
  rejection,
  shortId,
  strategyName,
} from "./model";
import {
  Badge,
  CompactTable,
  Panel,
  Pnl,
  ResourceState,
  Technical,
} from "./ui";
import { AdvancedResearch } from "./advanced";
export function Research({ auth }: { auth: string }) {
  const data = useResource("/api/research/summary", { ttl: 300000 });
  const shadow = useResource("/api/shadow/summary", { ttl: 60000 });
  const [selected, setSelected] = useState<Row | null>(null);
  const [advanced, setAdvanced] = useState(false);
  const reports = [
    { kind: "Original", report: data.data?.latest },
    { kind: "Experimental", report: data.data?.experimental_latest },
  ];
  const rows: Row[] = reports.flatMap(({ kind, report }) =>
    Object.entries(report?.timeframes ?? {}).flatMap(
      ([timeframe, v]: [string, any]) =>
        Object.entries(v.strategies ?? {}).map(
          ([strategy_id, r]: [string, any]) => ({
            strategy_id,
            key: `${kind}:${timeframe}:${strategy_id}`,
            kind,
            timeframe,
            report,
            ...r,
          }),
        ),
    ),
  );
  const registry = [
    ...(data.data?.registry ?? []),
    ...(data.data?.experimental_registry ?? []),
  ];
  const matching = (id: string) =>
    (shadow.data?.experiments ?? []).filter(
      (e: Row) => e.manifest?.strategy_id === id,
    );
  if (advanced)
    return (
      <div className="page-stack">
        <button className="text-button" onClick={() => setAdvanced(false)}>
          <ChevronLeft size={16} /> Strategy comparison
        </button>
        <AdvancedResearch auth={auth} />
      </div>
    );
  if (selected) {
    const record = registry.find(
      (r: Row) => r.strategy_id === selected.strategy_id,
    );
    const running = matching(selected.strategy_id);
    const reasons = running.flatMap((e: Row) =>
      (e.latest_decision
        ? [
            {
              payload_json: JSON.stringify({
                rejected_reason: e.latest_decision.reason,
              }),
            },
          ]
        : (e.history?.decisions ?? [])
      )
        .map(
          (d: Row) =>
            parse(d.payload_json).rejected_reason ?? d.rejected_reason,
        )
        .filter(Boolean),
    );
    return (
      <div className="page-stack">
        <button className="text-button" onClick={() => setSelected(null)}>
          <ChevronLeft size={16} /> Strategy comparison
        </button>
        <Panel>
          <Badge>{selected.kind} historical evidence</Badge>
          <h2 className="page-title">{strategyName(selected.strategy_id)}</h2>
          <p>
            {record?.hypothesis ??
              "Inspect the frozen strategy evidence in Advanced Research for its recorded entry and exit rules."}
          </p>
          <div className="detail-metrics">
            <div>
              <span>Historical net P&L</span>
              <strong>
                <Pnl value={selected.out_of_sample?.net_profit} />
              </strong>
            </div>
            <div>
              <span>Closed positions</span>
              <strong>{selected.out_of_sample?.trades ?? "Unavailable"}</strong>
            </div>
            <div>
              <span>Maximum drawdown</span>
              <strong>{percent(selected.out_of_sample?.max_drawdown)}</strong>
            </div>
          </div>
          <h3>
            {selected.gates?.passed
              ? "Passed historical gates"
              : "Not validated"}
          </h3>
          <ul className="reason-list">
            {(selected.gates?.failure_reasons ?? []).map((s: string) => (
              <li key={s}>{rejection(s)}</li>
            ))}
          </ul>
          <h3>Shadow experiments</h3>
          {running.length ? (
            running.map((e: Row) => (
              <p key={e.experiment_id}>
                {shortId(e.experiment_id)} ·{" "}
                {e.state === "SHADOW_ACTIVE"
                  ? "Active"
                  : e.state === "PAUSED"
                    ? "Paused"
                    : "Not active"}
                . Shadow activity does not grant approval.
              </p>
            ))
          ) : (
            <p className="muted">
              This strategy is not registered in the current shadow accounts.
            </p>
          )}
          <h3>Recorded rejection reasons</h3>
          {reasons.length ? (
            <ul className="reason-list">
              {[...new Set<string>(reasons)].slice(0, 5).map((s) => (
                <li key={s}>{rejection(s)}</li>
              ))}
            </ul>
          ) : (
            <p className="muted">
              No strategy-specific rejection details are available in the
              returned decision history.
            </p>
          )}
          <Technical
            value={{
              run: selected.report?.run_id,
              source: selected.report?.source_fingerprint,
              parameters: selected.out_of_sample?.parameters,
              gates: selected.gates,
              walk_forward: selected.walk_forward,
              sensitivity: selected.sensitivity,
            }}
          />
        </Panel>
      </div>
    );
  }
  return (
    <div className="page-stack">
      <div className="section-heading">
        <div>
          <h2 className="page-title">Strategy comparison</h2>
          <p className="muted">
            Historical results, including losses. No outcome is a promise.
          </p>
        </div>
        <button onClick={() => setAdvanced(true)}>Advanced Research</button>
      </div>
      <ResourceState resource={data} label="Research" />
      <Panel>
        <div className="section-heading">
          <h2>Historical evidence</h2>
          <Badge>Previously examined data</Badge>
        </div>
        <p className="muted small">
          Historical backtests and live-market shadow experiments are different
          evidence categories. Shadow forward results are in Experiments.
        </p>
        <CompactTable
          label="Historical strategy comparison"
          rows={rows}
          columns={[
            {
              label: "Strategy",
              render: (r) => (
                <button className="table-link" onClick={() => setSelected(r)}>
                  <strong>{strategyName(r.strategy_id)}</strong>
                  <span className="muted small">
                    {r.kind} · {r.timeframe}
                  </span>
                </button>
              ),
            },
            {
              label: "Historical net P&L",
              render: (r) => <Pnl value={r.out_of_sample?.net_profit} />,
            },
            {
              label: "Activity",
              render: (r) => r.out_of_sample?.trades ?? "Unavailable",
            },
            {
              label: "Win rate",
              render: (r) => percent(r.out_of_sample?.win_rate),
            },
            {
              label: "Maximum drawdown",
              render: (r) => percent(r.out_of_sample?.max_drawdown),
            },
            {
              label: "Validation",
              render: (r) => (
                <Badge>
                  {r.gates?.passed
                    ? "Passed historical gates"
                    : "Not validated"}
                </Badge>
              ),
            },
          ]}
        />
      </Panel>
      <p className="small muted">
        D2 is a momentum quality filter, not a standalone portfolio. A strategy
        needs independent validation and approval before official-account
        activity.
      </p>
    </div>
  );
}
